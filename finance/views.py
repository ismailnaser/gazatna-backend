from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re
import uuid

from django.db import transaction
from django.db.models import Avg, Count, Max, Prefetch, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import (
    AcademicTerm,
    AcademicYear,
    ClassGradebook,
    ClassSubjectAssignment,
    Grade,
    ParentDismissedAlert,
    PromotionPolicy,
    SchoolClass,
    Student,
    StudentDocument,
    Subject,
    SubjectGrade,
    SubjectGradeScheme,
    SubjectGradeSchemeEntry,
)
from academics.academic_serializers import AcademicYearWriteSerializer, PromotionPolicySerializer
from academics.academic_services import (
    require_current_academic_term,
    serialize_academic_context,
    serialize_academic_year,
    set_active_academic_year,
    set_current_academic_term,
)
from accounts.models import User
from accounts.roles import ADMIN_ROLES, role_has_scope
from accounts.serializers import UserCreateSerializer, UserSerializer
from accounts.utils import generate_secure_password
from assignments.models import (
    Homework,
    HomeworkSubmission,
    QuestionType,
    Quiz,
    QuizQuestion,
    QuizSubmission,
    SubjectAnnouncement,
    SubjectMaterial,
)
from assignments.attachment_utils import (
    add_attachments_to_homework,
    add_attachments_to_material,
    collect_quiz_essay_files,
    collect_uploaded_files,
    copy_attachments_from_homework,
    copy_attachments_from_material,
    remove_attachments,
    remove_material_attachments,
    save_quiz_answer_attachments,
    _file_bytes_list,
)
from assignments.services import homework_is_open
from config.media_access import build_media_url
from config.throttling import PublicPostRateThrottle
from config.permissions import (
    AdminClassPermission,
    AdminGradePermission,
    AdminScopePermission,
    IsAdmin,
    IsParent,
    IsSuperAdmin,
    IsTeacher,
)
from config.cache_mixins import CachedAPIViewMixin, CachedReadOnlyViewSetMixin
from config.events import emit
from config.serializers import (
    ClassGradebookSerializer,
    ClassStudentSerializer,
    FeePlanSerializer,
    FinanceNoticeSerializer,
    HomeworkSerializer,
    HomeworkSubmissionSerializer,
    NewsItemSerializer,
    ParentChildSerializer,
    PaymentNoticeSerializer,
    ProgramSerializer,
    QuizSerializer,
    QuizSubmissionSerializer,
    SubjectAnnouncementSerializer,
    SubjectMaterialSerializer,
    SchoolClassSerializer,
    SchoolClassWriteSerializer,
    GradeSerializer,
    SchoolStatSerializer,
    SchoolValueSerializer,
    StudentSerializer,
    SubjectGradeSerializer,
    SubjectSerializer,
    SubjectWriteSerializer,
    TeacherProfileSerializer,
    TeacherWriteSerializer,
    StaffTypeSerializer,
    ParentAlertSerializer,
    ScheduleSerializer,
)
from content.models import (
    AdmissionApplication,
    AdmissionStatus,
    ContactMessage,
    NewsImage,
    NewsItem,
    Program,
    SchoolStat,
    SchoolValue,
    Schedule,
    SiteSettings,
)
from finance.models import FeePlan, PaymentNotice, PaymentSource, PaymentStatus, StudentFeeBalance
from finance.services import (
    apply_plan_to_student,
    apply_plan_to_students,
    build_fee_status,
    count_fee_blocked_students,
    load_active_fee_plans_by_grade,
    restore_student_access_after_fees,
)
from staff.models import StaffType, TeacherClassAssignment, TeacherProfile, TeacherReadAlert
from staff.assignment_validation import (
    class_subject_assignments,
    collect_subject_class_conflicts,
    sync_subject_section_teachers,
    school_class_id_for_student,
    validate_homeroom_teacher,
    validate_teacher_subject_class_assignments,
)



from config.api_helpers import *  # noqa: F401,F403

class AdminFeePlanViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("finance")]
    serializer_class = FeePlanSerializer
    queryset = FeePlan.objects.prefetch_related("grades", "installments").all()

    def perform_create(self, serializer):
        plan = serializer.save()
        apply_plan_to_students(plan)

    def perform_update(self, serializer):
        plan = serializer.save()
        apply_plan_to_students(plan)



class AdminFinanceViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("finance")]
    serializer_class = PaymentNoticeSerializer
    queryset = PaymentNotice.objects.select_related("student").all()

    def get_serializer_class(self):
        return PaymentNoticeSerializer

    def list(self, request, *args, **kwargs):
        notices = (
            PaymentNotice.objects.select_related("student", "reviewed_by")
            .order_by("-date", "-id")[:500]
        )
        data = FinanceNoticeSerializer(
            [
                {
                    "id": str(n.id),
                    "studentId": str(n.student_id),
                    "studentName": n.student.name,
                    "declaredAmount": float(n.declared_amount or n.amount),
                    "amount": float(n.amount),
                    "status": n.status,
                    "date": str(n.date),
                    "note": n.note or "",
                    "receiptUrl": build_media_url(request, n.receipt) if n.receipt else None,
                    "source": n.source,
                    "reviewedByName": n.reviewed_by.display_name if n.reviewed_by else None,
                }
                for n in notices
            ],
            many=True,
        ).data
        return Response(data)

    @staticmethod
    def _parse_positive_amount(raw, fallback=None):
        try:
            amount = Decimal(str(raw if raw is not None else fallback))
        except (InvalidOperation, TypeError, ValueError):
            return None, Response({"detail": "المبلغ غير صالح"}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return None, Response(
                {"detail": "المبلغ يجب أن يكون أكبر من صفر"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return amount, None

    def partial_update(self, request, *args, **kwargs):
        notice = self.get_object()
        old_status = notice.status
        new_status = request.data.get("status")
        if new_status:
            with transaction.atomic():
                locked = (
                    PaymentNotice.objects.select_for_update()
                    .select_related("student")
                    .get(pk=notice.pk)
                )
                old_status = locked.status
                if new_status == PaymentStatus.APPROVED and old_status != PaymentStatus.APPROVED:
                    approve_amount, err = self._parse_positive_amount(
                        request.data.get("amount"), locked.amount
                    )
                    if err:
                        return err
                    locked.amount = approve_amount
                    balance, _ = StudentFeeBalance.objects.select_for_update().get_or_create(
                        student=locked.student
                    )
                    balance.paid += approve_amount
                    balance.save(update_fields=["paid"])
                    locked.status = new_status
                    locked.reviewed_by = request.user
                    locked.save()
                    restore_student_access_after_fees(locked.student)
                elif (
                    new_status in (PaymentStatus.PENDING, PaymentStatus.REJECTED)
                    and old_status == PaymentStatus.APPROVED
                ):
                    balance, _ = StudentFeeBalance.objects.select_for_update().get_or_create(
                        student=locked.student
                    )
                    balance.paid = max(Decimal("0"), balance.paid - locked.amount)
                    balance.save(update_fields=["paid"])
                    locked.status = new_status
                    locked.reviewed_by = request.user
                    locked.save()
                else:
                    locked.status = new_status
                    locked.reviewed_by = request.user
                    locked.save(update_fields=["status", "reviewed_by"])
                notice = locked
        elif "amount" in request.data and notice.status == PaymentStatus.PENDING:
            amount, err = self._parse_positive_amount(request.data["amount"])
            if err:
                return err
            notice.amount = amount
            notice.save(update_fields=["amount"])
        return Response(PaymentNoticeSerializer(notice, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        notice = self.get_object()
        if notice.source != PaymentSource.MANUAL:
            return Response(
                {"detail": "يمكن إلغاء الدفعات اليدوية فقط من هذا السجل"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            locked = PaymentNotice.objects.select_for_update().select_related("student").get(pk=notice.pk)
            if locked.status == PaymentStatus.APPROVED:
                balance, _ = StudentFeeBalance.objects.select_for_update().get_or_create(
                    student=locked.student
                )
                balance.paid = max(Decimal("0"), balance.paid - locked.amount)
                balance.save(update_fields=["paid"])
            locked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get", "post"], url_path="manual")
    def manual_payments(self, request):
        if request.method == "GET":
            notices = (
                PaymentNotice.objects.filter(source=PaymentSource.MANUAL, status=PaymentStatus.APPROVED)
                .select_related("student", "reviewed_by")
                .order_by("-date", "-id")[:200]
            )
            data = [
                {
                    "id": str(n.id),
                    "studentId": str(n.student_id),
                    "studentName": n.student.name,
                    "studentNumber": n.student.student_number,
                    "amount": float(n.amount),
                    "date": str(n.date),
                    "note": n.note or "",
                    "reviewedByName": n.reviewed_by.display_name if n.reviewed_by else "—",
                }
                for n in notices
            ]
            return Response(data)

        student_id = request.data.get("studentId")
        note = str(request.data.get("note", "")).strip() or "دفع يدوي — خارج المنصة"

        if not student_id:
            return Response({"detail": "يجب اختيار الطالب"}, status=status.HTTP_400_BAD_REQUEST)

        amount, err = self._parse_positive_amount(request.data.get("amount"))
        if err:
            return err

        student = Student.objects.filter(id=student_id).select_related("fee_balance").first()
        if not student:
            return Response({"detail": "الطالب غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        today = timezone.now().date()
        with transaction.atomic():
            notice = PaymentNotice.objects.create(
                student=student,
                declared_amount=amount,
                amount=amount,
                date=today,
                status=PaymentStatus.APPROVED,
                source=PaymentSource.MANUAL,
                note=note,
                reviewed_by=request.user,
            )
            balance, _ = StudentFeeBalance.objects.select_for_update().get_or_create(
                student=student, defaults={"total": 0, "paid": 0}
            )
            balance.paid += amount
            balance.save(update_fields=["paid"])
            restore_student_access_after_fees(student)

        payload = {
            "id": str(notice.id),
            "studentId": str(student.id),
            "studentName": student.name,
            "declaredAmount": float(notice.declared_amount),
            "amount": float(notice.amount),
            "status": notice.status,
            "date": str(notice.date),
            "note": notice.note,
            "receiptUrl": None,
            "reviewedByName": request.user.display_name,
            "balance": {
                "total": float(balance.total),
                "paid": float(balance.paid),
                "remaining": float(balance.remaining),
            },
        }
        return Response(payload, status=status.HTTP_201_CREATED)



class ParentFeesView(APIView):
    permission_classes = [IsParent]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        child = _linked_student_for_parent(request.user)
        if not child:
            return Response({"student": None, "notices": [], "feeStatus": None})
        notices = PaymentNotice.objects.filter(student=child).order_by("-date", "-id")
        return Response({
            "student": StudentSerializer(child, context={"request": request}).data,
            "notices": PaymentNoticeSerializer(notices, many=True, context={"request": request}).data,
            "feeStatus": build_fee_status(child, link_plan=False),
        })

    def post(self, request):
        child = _linked_student_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)
        amount_raw = request.data.get("amount")
        if amount_raw in (None, ""):
            return Response({"detail": "المبلغ مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            return Response({"detail": "مبلغ غير صالح"}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({"detail": "المبلغ يجب أن يكون أكبر من صفر"}, status=status.HTTP_400_BAD_REQUEST)
        receipt = request.FILES.get("receipt")
        if receipt:
            from assignments.attachment_utils import validate_uploaded_file

            validate_uploaded_file(receipt)
        notice = PaymentNotice.objects.create(
            student=child,
            declared_amount=amount,
            amount=amount,
            date=date.today(),
            note=str(request.data.get("note", "")).strip(),
            receipt=receipt,
        )
        return Response(
            PaymentNoticeSerializer(notice, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )



class AdminBlockedStudentsView(CachedAPIViewMixin, APIView):
    permission_classes = [AdminScopePermission("finance")]
    cache_prefix = "admin:blocked-students"
    cache_ttl = 60

    def get(self, request):
        return self.get_cached(request, self._build_rows)

    def _build_rows(self):
        rows = []
        # Read-only: never link/mutate balances on a list endpoint (signal storms).
        plans_by_grade = load_active_fee_plans_by_grade()
        students = (
            Student.objects.select_related("fee_balance")
            .filter(is_active=True)
            .order_by("name")
            .iterator(chunk_size=200)
        )
        for student in students:
            status = build_fee_status(
                student,
                link_plan=False,
                plans_by_grade=plans_by_grade,
                detail=True,
            )
            if not status.get("blocked"):
                continue
            balance = getattr(student, "fee_balance", None)
            current = status.get("currentInstallment") or {}
            total_fees = float(balance.total) if balance else 0
            inst_amount = float(current.get("amount") or 0)
            due = current.get("remaining")
            if due is None:
                due = status.get("requiredAmount", 0)
            due = float(due)
            if inst_amount > 0 and due >= total_fees:
                due = inst_amount
            order = int(current.get("order") or 1)
            if order == 1:
                message = (
                    f"يجب دفع مبلغ الدفعة الأولى فقط ({int(due)} ₪) لاستئناف الوصول — "
                    f"وليس المبلغ الكلي ({int(total_fees)} ₪)."
                )
            else:
                end_date = current.get("endDate") or ""
                message = (
                    f"يجب دفع مبلغ الدفعة رقم {order} فقط ({int(due)} ₪) لاستئناف الوصول — "
                    f"وليس المبلغ الكلي ({int(total_fees)} ₪)."
                    + (f" (آخر موعد: {end_date})" if end_date else "")
                )
            rows.append({
                "id": str(student.id),
                "name": student.name,
                "studentNumber": student.student_number,
                "nationalId": student.national_id or "",
                "grade": student.grade_level,
                "section": student.section or "",
                "requiredAmount": due,
                "installmentOrder": order,
                "installmentAmount": inst_amount or None,
                "installmentRemaining": due,
                "message": message,
                "totalFees": total_fees,
                "paidFees": float(balance.paid) if balance else 0,
                "currentInstallment": status.get("currentInstallment"),
            })
        return rows


