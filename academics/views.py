from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re
import uuid

from django.db import DatabaseError, transaction
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

class AdminStudentViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("students")]
    serializer_class = StudentSerializer
    queryset = Student.objects.select_related("school_class", "fee_balance", "parent").prefetch_related(
        "uploaded_documents",
        Prefetch("payment_notices", queryset=PaymentNotice.objects.order_by("-date", "-id")),
    ).all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _save_documents(self, student, request):
        from assignments.attachment_utils import validate_uploaded_file

        names = request.data.getlist("documentNames") if hasattr(request.data, "getlist") else []
        files = request.FILES.getlist("documentFiles") if hasattr(request.FILES, "getlist") else []
        if not names and not files:
            return
        # Align lengths (ignore extra files or names)
        for i in range(min(len(names), len(files))):
            name = str(names[i]).strip() or "وثيقة"
            uploaded = files[i]
            validate_uploaded_file(uploaded)
            StudentDocument.objects.create(student=student, name=name, file=uploaded)

    def perform_create(self, serializer):
        student = serializer.save()
        self._save_documents(student, self.request)
        StudentFeeBalance.objects.get_or_create(student=student, defaults={"total": 0, "paid": 0})
        apply_plan_to_student(student)

    def perform_update(self, serializer):
        student = serializer.save()
        self._save_documents(student, self.request)
        apply_plan_to_student(student)

    def perform_destroy(self, instance):
        parent = instance.parent
        instance.delete()
        if parent:
            parent.delete()

    def _serialize_document(self, doc, request):
        from config.media_access import build_media_url

        url = build_media_url(request, doc.file) if doc.file else None
        return {"id": str(doc.id), "name": doc.name, "url": url}

    def _student_documents_payload(self, student, request):
        return StudentSerializer(student, context={"request": request}).data.get("documents", [])

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, pk=None):
        student = self.get_object()
        if request.method == "POST":
            self._save_documents(student, request)
        student = Student.objects.filter(id=student.id).first()
        return Response(self._student_documents_payload(student, request))

    @action(detail=True, methods=["patch", "delete"], url_path=r"documents/(?P<doc_id>[^/.]+)")
    def document_detail(self, request, pk=None, doc_id=None):
        student = self.get_object()
        doc = StudentDocument.objects.filter(id=doc_id, student=student).first()
        if not doc:
            return Response({"detail": "الوثيقة غير موجودة"}, status=status.HTTP_404_NOT_FOUND)

        if request.method == "DELETE":
            if doc.file:
                doc.file.delete(save=False)
            doc.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        name = request.data.get("name")
        if name is not None:
            cleaned = str(name).strip()
            if cleaned:
                doc.name = cleaned
        new_file = request.FILES.get("file")
        if new_file:
            doc.file = new_file
        doc.save()
        return Response(self._serialize_document(doc, request))

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        student = self.get_object()
        if not student.parent_id:
            return Response({"detail": "لا يوجد حساب ولي أمر مرتبط بهذا الطالب"}, status=status.HTTP_400_BAD_REQUEST)
        new_password = generate_secure_password()
        student.parent.set_password(new_password)
        student.parent.save(update_fields=["password"])
        return Response(
            {
                "studentId": str(student.id),
                "name": student.name,
                "username": student.parent.username,
                "password": new_password,
            }
        )

    @action(detail=True, methods=["post"], url_path="fee-access")
    def fee_access(self, request, pk=None):
        student = self.get_object()
        days = int(request.data.get("days", request.data.get("hours", 24)))
        if "hours" in request.data and "days" not in request.data:
            days = max(1, round(int(request.data.get("hours", 24)) / 24))
        balance, _ = StudentFeeBalance.objects.get_or_create(student=student)
        balance.access_override_until = timezone.now() + timedelta(days=days)
        balance.save(update_fields=["access_override_until"])
        return Response({"accessOverrideUntil": balance.access_override_until.isoformat()})



class AdminClassViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminClassPermission]
    queryset = SchoolClass.objects.all()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return SchoolClassWriteSerializer
        return SchoolClassSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        names = {}
        for grade in Grade.objects.only("id", "name"):
            grade_id = str(grade.id)
            names[grade.name] = grade_id
            names[(grade.name or "").strip()] = grade_id
        context["_grade_ids_by_name"] = names
        return context

    @action(detail=True, methods=["get", "patch"], url_path="detail")
    def class_detail(self, request, pk=None):
        school_class = self.get_object()

        if request.method == "PATCH":
            teacher_id = request.data.get("homeroomTeacherId")
            if teacher_id in ("", None):
                school_class.homeroom_teacher = None
                school_class.save(update_fields=["homeroom_teacher"])
            else:
                teacher = TeacherProfile.objects.filter(id=teacher_id).first()
                if not teacher:
                    return Response({"detail": "المعلم غير موجود"}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    validate_homeroom_teacher(teacher, school_class)
                except ValidationError as exc:
                    detail = exc.detail
                    if isinstance(detail, dict):
                        message = detail.get("detail", detail)
                    else:
                        message = detail
                    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)
                school_class.homeroom_teacher = teacher
                school_class.save(update_fields=["homeroom_teacher"])

        students = Student.objects.filter(school_class=school_class, is_active=True).order_by("name")
        return Response(
            {
                "class": SchoolClassSerializer(school_class, context={"request": request}).data,
                "students": StudentSerializer(students, many=True, context={"request": request}).data,
            }
        )

    def perform_destroy(self, instance):
        grade_level = instance.grade_level
        instance.delete()
        _sync_grade_sections_count(grade_level)


SECTION_LABELS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح", "ط", "ي", "ك", "ل", "م", "ن", "س", "ع", "ف", "ص", "ق", "ر"]



class AdminGradeViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminGradePermission]
    serializer_class = GradeSerializer
    queryset = Grade.objects.select_related("promotion_policy").order_by("sort_order", "id")

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except DatabaseError:
            queryset = Grade.objects.order_by("sort_order", "id")
            return Response(GradeSerializer(queryset, many=True).data)

    def perform_create(self, serializer):
        from academics.academic_services import get_promotion_policy_for_grade

        max_order = Grade.objects.aggregate(Max("sort_order"))["sort_order__max"] or 0
        grade = serializer.save(sort_order=max_order + 1)
        _sync_grade_sections(grade)
        get_promotion_policy_for_grade(grade)

    def perform_update(self, serializer):
        grade = serializer.save()
        _sync_grade_sections(grade)

    @action(detail=True, methods=["patch"], url_path="promotion-policy")
    def update_promotion_policy(self, request, pk=None):
        from academics.academic_serializers import PromotionPolicySerializer
        from academics.academic_services import get_promotion_policy_for_grade

        grade = self.get_object()
        policy = get_promotion_policy_for_grade(grade)
        serializer = PromotionPolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        grade.refresh_from_db()
        return Response(GradeSerializer(grade).data)

    @action(detail=True, methods=["delete"], url_path="promotion-policy")
    def reset_promotion_policy(self, request, pk=None):
        from academics.academic_services import _default_promotion_policy_fields, get_promotion_policy_for_grade

        grade = self.get_object()
        policy = get_promotion_policy_for_grade(grade)
        for key, value in _default_promotion_policy_fields().items():
            setattr(policy, key, value)
        policy.evaluation_term = None
        policy.is_configured = False
        policy.save()
        grade.refresh_from_db()
        return Response(GradeSerializer(grade).data)

    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request):
        order = request.data.get("order")
        if not isinstance(order, list) or not order:
            return Response({"detail": "يجب إرسال ترتيب الفصول"}, status=status.HTTP_400_BAD_REQUEST)

        ids = [str(item) for item in order]
        grades = {str(g.id): g for g in Grade.objects.filter(id__in=ids)}
        if len(grades) != len(set(ids)):
            return Response({"detail": "معرّفات الفصول غير صالحة"}, status=status.HTTP_400_BAD_REQUEST)

        for index, grade_id in enumerate(ids):
            grades[grade_id].sort_order = index
        Grade.objects.bulk_update(grades.values(), ["sort_order"])

        ordered = Grade.objects.order_by("sort_order", "id")
        return Response(GradeSerializer(ordered, many=True).data)

    def destroy(self, request, *args, **kwargs):
        grade = self.get_object()
        SchoolClass.objects.filter(grade_level=grade.name).delete()
        return super().destroy(request, *args, **kwargs)



class AdminSubjectViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics")]
    queryset = Subject.objects.prefetch_related("class_assignments").all()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return SubjectWriteSerializer
        return SubjectSerializer

    @action(detail=True, methods=["post"], url_path="assign-teacher")
    def assign_teacher(self, request, pk=None):
        subject = self.get_object()
        teacher_id = request.data.get("teacherId")
        if not teacher_id:
            return Response(
                {"detail": "يجب اختيار معلم"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            teacher = TeacherProfile.objects.prefetch_related(
                "teaching_subjects", "class_assignments", "homeroom_classes"
            ).get(pk=teacher_id)
        except (TeacherProfile.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "المعلم غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        current_ids = list(teacher.teaching_subjects.values_list("id", flat=True))
        already_has_subject = subject.id in current_ids

        requested_class_ids = request.data.get("classIds")
        if requested_class_ids is not None:
            class_ids = [int(class_id) for class_id in requested_class_ids if class_id is not None]
        else:
            class_ids = []

        assignable_class_ids, conflicts = collect_subject_class_conflicts(
            teacher, subject.id, class_ids
        )
        if class_ids and not assignable_class_ids:
            return Response(
                {
                    "detail": (
                        conflicts[0]
                        if len(conflicts) == 1
                        else "؛ ".join(conflicts)
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not already_has_subject:
            teacher.teaching_subjects.add(subject)
        for class_id in assignable_class_ids:
            TeacherClassAssignment.objects.get_or_create(
                teacher=teacher, school_class_id=class_id
            )
        teacher = TeacherProfile.objects.prefetch_related(
            "class_assignments", "teaching_subjects", "homeroom_classes"
        ).get(pk=teacher.pk)
        data = TeacherProfileSerializer(teacher, context={"request": request}).data
        data["assignedClassIds"] = [str(class_id) for class_id in assignable_class_ids]
        data["skippedConflicts"] = conflicts
        return Response(data)

    @action(detail=True, methods=["post"], url_path="sync-sections")
    def sync_sections(self, request, pk=None):
        subject = self.get_object()
        sections = request.data.get("sections")
        if not isinstance(sections, list):
            return Response(
                {"detail": "صيغة الشعب غير صحيحة"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            affected_teacher_ids = sync_subject_section_teachers(subject, sections)
        except TeacherProfile.DoesNotExist:
            return Response({"detail": "المعلم غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        except (TypeError, ValueError):
            return Response(
                {"detail": "صيغة الشعب غير صحيحة"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subject = Subject.objects.prefetch_related("class_assignments").get(pk=subject.pk)
        teachers = TeacherProfile.objects.filter(id__in=affected_teacher_ids).prefetch_related(
            "class_assignments", "teaching_subjects", "homeroom_classes"
        )
        return Response(
            {
                "subject": SubjectSerializer(subject, context={"request": request}).data,
                "teachers": TeacherProfileSerializer(
                    teachers, many=True, context={"request": request}
                ).data,
            }
        )



class AdminGradeSchemeTemplateView(APIView):
    permission_classes = [AdminScopePermission("academics")]

    def get(self, request):
        from academics.academic_services import get_current_academic_term, serialize_academic_context
        from academics.grade_scheme_services import (
            get_grade_scheme_template,
            serialize_grade_scheme_template,
        )

        term = get_current_academic_term()
        template = get_grade_scheme_template(term=term) if term else None
        return Response(
            {
                "scheme": serialize_grade_scheme_template(template),
                "academicContext": serialize_academic_context(),
            }
        )

    def put(self, request):
        from academics.academic_services import serialize_academic_context
        from academics.grade_scheme_services import (
            normalize_components,
            serialize_grade_scheme_template,
            upsert_grade_scheme_template,
        )
        from rest_framework.exceptions import ValidationError as DRFValidationError

        components = normalize_components(request.data.get("components") or [])
        max_score = request.data.get("maxScore", 100)
        try:
            template = upsert_grade_scheme_template(max_score, components)
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)

        return Response(
            {
                "scheme": serialize_grade_scheme_template(template),
                "academicContext": serialize_academic_context(),
            }
        )



class AdminAnalyticsView(CachedAPIViewMixin, APIView):
    permission_classes = [IsAdmin]
    cache_prefix = "admin:analytics"
    cache_ttl = 120

    def get(self, request):
        from config.cache_utils import get_or_set, stable_query_key, versioned_key

        role = getattr(request.user, "role", "") or "anon"
        key = versioned_key(self.cache_prefix, role, stable_query_key(request))
        data = get_or_set(key, lambda: self._build_payload(request), self.cache_ttl)
        return Response(data)

    def _build_payload(self, request=None):
        """Build analytics payload.

        Optional ``section`` query param limits work to one slice so the UI can
        lazy-load tabs without computing students + grades + fees together:
        meta | students | grades | fees | alerts | badge
        """
        from academics.academic_services import get_current_academic_term, term_display_name
        from academics.analytics_services import average_grade_percent, student_enrollment_analytics

        role = getattr(getattr(request, "user", None), "role", "") if request else ""
        section = ""
        if request is not None:
            section = (request.query_params.get("section") or "").strip().lower()

        can_students = role_has_scope(role, "students")
        can_academics = role_has_scope(role, "academics")
        can_finance = role_has_scope(role, "finance")
        can_content = role_has_scope(role, "content")

        want_all = section in ("", "all")
        want_meta = want_all or section == "meta"
        want_students = want_all or section == "students"
        want_grades = want_all or section == "grades"
        want_fees = want_all or section == "fees"
        want_alerts = want_all or section == "alerts"
        want_badge = section == "badge"

        out = {
            "avgGrade": 0,
            "feesCollected": 0,
            "pendingPayments": 0,
            "inactiveStudents": 0,
            "blockedStudents": 0,
            "overdueInstallments": 0,
            "pendingAdmissions": 0,
            "newMessages": 0,
            "registeredStudents": 0,
            "previousYearRegisteredStudents": 0,
            "studentsGrowthPercent": None,
            "academicYear": None,
            "academicTerm": None,
            "previousAcademicYear": None,
            "activeStudents": 0,
            "totalStudents": 0,
            "urgentTasks": [],
            "gradeChart": [],
            "feesChart": [],
            "studentsChart": [],
            "yearlyStudentsChart": [],
            "section": section or "all",
        }

        if want_badge:
            pending_count = (
                PaymentNotice.objects.filter(status="pending").count() if can_finance else 0
            )
            out["pendingPayments"] = pending_count
            return out

        if want_students:
            enrollment = student_enrollment_analytics()
            term = get_current_academic_term()
            out["academicYear"] = enrollment.get("academicYear")
            out["academicTerm"] = term_display_name(term) if term else None
            out["registeredStudents"] = enrollment["registeredStudents"]
            out["previousYearRegisteredStudents"] = enrollment["previousYearRegisteredStudents"]
            out["studentsGrowthPercent"] = (
                enrollment["studentsGrowthPercent"] if can_students else None
            )
            out["previousAcademicYear"] = (
                enrollment["previousAcademicYear"] if can_students else None
            )
            out["activeStudents"] = enrollment["activeStudents"]
            out["totalStudents"] = enrollment["totalStudents"]
            out["studentsChart"] = enrollment["studentsChart"] if can_students else []
            out["yearlyStudentsChart"] = (
                enrollment["yearlyStudentsChart"] if can_students else []
            )
        elif want_meta:
            from academics.academic_services import get_active_academic_year

            year = get_active_academic_year()
            term = get_current_academic_term()
            out["academicYear"] = year.name if year else None
            out["academicTerm"] = term_display_name(term) if term else None

        if want_grades and can_academics:
            out["avgGrade"] = average_grade_percent()
            out["gradeChart"] = _build_grade_chart()

        if want_fees and can_finance:
            balances = StudentFeeBalance.objects.all()
            total_fees = balances.aggregate(t=Sum("total"))["t"] or 0
            paid_fees = balances.aggregate(p=Sum("paid"))["p"] or 0
            out["feesCollected"] = (
                round(float(paid_fees) / float(total_fees) * 100, 1) if total_fees else 0
            )
            out["feesChart"] = _build_fees_chart()
            out["pendingPayments"] = PaymentNotice.objects.filter(status="pending").count()

        if want_alerts:
            pending_count = (
                PaymentNotice.objects.filter(status="pending").count() if can_finance else 0
            )
            inactive_students = (
                Student.objects.filter(is_active=False).count() if can_students else 0
            )
            pending_admissions = (
                AdmissionApplication.objects.filter(status="pending").count()
                if can_students
                else 0
            )
            new_messages = (
                ContactMessage.objects.filter(status="new").count() if can_content else 0
            )
            # Never call build_fee_status per-student with DB writes here —
            # that previously held Passenger workers open long enough to blow NPROC.
            blocked_students = count_fee_blocked_students() if can_finance else 0

            out["pendingPayments"] = pending_count
            out["inactiveStudents"] = inactive_students
            out["blockedStudents"] = blocked_students
            out["overdueInstallments"] = blocked_students
            out["pendingAdmissions"] = pending_admissions
            out["newMessages"] = new_messages

            urgent_tasks = []
            if pending_count:
                urgent_tasks.append(
                    {
                        "id": "t1",
                        "text": f"{pending_count} إشعارات دفع تنتظر الموافقة",
                        "type": "finance",
                    }
                )
            if blocked_students:
                urgent_tasks.append(
                    {
                        "id": "t_blocked",
                        "text": f"{blocked_students} طلاب محجوبون بسبب الرسوم",
                        "type": "fees_blocked",
                    }
                )
            if inactive_students:
                urgent_tasks.append(
                    {
                        "id": "t_inactive",
                        "text": f"{inactive_students} طلاب غير نشطين ينتظرون التفعيل",
                        "type": "students_inactive",
                    }
                )
            if pending_admissions:
                urgent_tasks.append(
                    {
                        "id": "t_admissions",
                        "text": f"{pending_admissions} طلبات قبول/تسجيل جديدة",
                        "type": "admissions",
                    }
                )
            if new_messages:
                urgent_tasks.append(
                    {
                        "id": "t_messages",
                        "text": f"{new_messages} رسائل جديدة من تواصل معنا",
                        "type": "messages",
                    }
                )
            out["urgentTasks"] = urgent_tasks

        return out



class AdminAnalyticsDetailsView(APIView):
    permission_classes = [AdminScopePermission("academics", "finance", "students")]

    def get(self, request):
        try:
            data = self._build_payload(request)
        except Exception:
            data = self._empty_payload(request)
        return Response(data)

    def _empty_payload(self, request):
        grade_level = (request.query_params.get("gradeLevel") or "").strip()
        section = (request.query_params.get("section") or "").strip().lower()
        from_raw = (request.query_params.get("from") or "").strip()
        to_raw = (request.query_params.get("to") or "").strip()
        return {
            "avgGrade": 0,
            "feesCollected": 0,
            "pendingAdmissions": 0,
            "registeredStudents": 0,
            "previousYearRegisteredStudents": 0,
            "studentsGrowthPercent": None,
            "academicYear": None,
            "previousAcademicYear": None,
            "activeStudents": 0,
            "inactiveStudents": 0,
            "totalStudents": 0,
            "urgentTasks": [],
            "gradeChart": [],
            "feesChart": [],
            "studentsChart": [],
            "yearlyStudentsChart": [],
            "section": section or "all",
            "filters": {
                "gradeLevel": grade_level or None,
                "from": from_raw or None,
                "to": to_raw or None,
            },
        }

    def _build_payload(self, request):
        grade_level = (request.query_params.get("gradeLevel") or "").strip()
        from_raw = (request.query_params.get("from") or "").strip()
        to_raw = (request.query_params.get("to") or "").strip()
        section = (request.query_params.get("section") or "").strip().lower()
        want_all = section in ("", "all")
        want_students = want_all or section == "students"
        want_grades = want_all or section == "grades"
        want_fees = want_all or section == "fees"

        from_date = None
        to_date = None
        try:
            from_date = date.fromisoformat(from_raw) if from_raw else None
        except ValueError:
            from_date = None
        try:
            to_date = date.fromisoformat(to_raw) if to_raw else None
        except ValueError:
            to_date = None

        from academics.analytics_services import (
            average_grade_percent,
            grade_chart_by_level,
            student_enrollment_analytics,
        )

        role = getattr(request.user, "role", "")
        can_students = role_has_scope(role, "students")
        can_academics = role_has_scope(role, "academics")
        can_finance = role_has_scope(role, "finance")

        out = {
            "avgGrade": 0,
            "feesCollected": 0,
            "pendingAdmissions": 0,
            "registeredStudents": 0,
            "previousYearRegisteredStudents": 0,
            "studentsGrowthPercent": None,
            "academicYear": None,
            "previousAcademicYear": None,
            "activeStudents": 0,
            "inactiveStudents": 0,
            "totalStudents": 0,
            "urgentTasks": [],
            "gradeChart": [],
            "feesChart": [],
            "studentsChart": [],
            "yearlyStudentsChart": [],
            "section": section or "all",
            "filters": {
                "gradeLevel": grade_level or None,
                "from": str(from_date) if from_date else None,
                "to": str(to_date) if to_date else None,
            },
        }

        if want_grades and can_academics:
            grades_qs = SubjectGrade.objects.select_related("student")
            if grade_level:
                grades_qs = grades_qs.filter(student__grade_level=grade_level)
            out["gradeChart"] = grade_chart_by_level(grades_qs)
            out["avgGrade"] = average_grade_percent(grades_qs)

        if want_fees and can_finance:
            balances_qs = StudentFeeBalance.objects.select_related("student")
            if grade_level:
                balances_qs = balances_qs.filter(student__grade_level=grade_level)

            fees_chart = []
            balance_rows = (
                balances_qs.values("student__grade_level")
                .annotate(total=Sum("total"), paid=Sum("paid"))
                .order_by("student__grade_level")
            )

            paid_by_grade = {row["student__grade_level"]: (row["paid"] or 0) for row in balance_rows}
            total_by_grade = {row["student__grade_level"]: (row["total"] or 0) for row in balance_rows}

            if from_date or to_date:
                notices = PaymentNotice.objects.filter(status="approved").select_related("student")
                if grade_level:
                    notices = notices.filter(student__grade_level=grade_level)
                if from_date:
                    notices = notices.filter(date__gte=from_date)
                if to_date:
                    notices = notices.filter(date__lte=to_date)

                notice_rows = (
                    notices.values("student__grade_level")
                    .annotate(paid=Sum("amount"))
                    .order_by("student__grade_level")
                )
                paid_by_grade = {row["student__grade_level"]: (row["paid"] or 0) for row in notice_rows}

            for gl, total in total_by_grade.items():
                if not gl:
                    continue
                paid = paid_by_grade.get(gl, 0)
                pct = round(float(paid) / float(total) * 100, 1) if total else 0
                fees_chart.append({"label": gl, "value": pct})

            total_fees = balances_qs.aggregate(t=Sum("total"))["t"] or 0
            paid_fees = balances_qs.aggregate(p=Sum("paid"))["p"] or 0
            if from_date or to_date:
                notices = PaymentNotice.objects.filter(status="approved").select_related("student")
                if grade_level:
                    notices = notices.filter(student__grade_level=grade_level)
                if from_date:
                    notices = notices.filter(date__gte=from_date)
                if to_date:
                    notices = notices.filter(date__lte=to_date)
                paid_fees = notices.aggregate(p=Sum("amount"))["p"] or 0

            out["feesChart"] = fees_chart
            out["feesCollected"] = (
                round(float(paid_fees) / float(total_fees) * 100, 1) if total_fees else 0
            )

        if want_students:
            enrollment = (
                student_enrollment_analytics(grade_level)
                if can_students
                else {
                    "registeredStudents": 0,
                    "previousYearRegisteredStudents": 0,
                    "studentsGrowthPercent": None,
                    "academicYear": None,
                    "previousAcademicYear": None,
                    "activeStudents": 0,
                    "inactiveStudents": 0,
                    "totalStudents": 0,
                    "studentsChart": [],
                    "yearlyStudentsChart": [],
                }
            )
            pending_qs = AdmissionApplication.objects.filter(status="pending")
            if grade_level:
                pending_qs = pending_qs.filter(grade=grade_level)
            pending_admissions = pending_qs.count() if can_students else 0

            out["pendingAdmissions"] = pending_admissions
            out["registeredStudents"] = enrollment["registeredStudents"]
            out["previousYearRegisteredStudents"] = enrollment["previousYearRegisteredStudents"]
            out["studentsGrowthPercent"] = enrollment["studentsGrowthPercent"]
            out["academicYear"] = enrollment["academicYear"]
            out["previousAcademicYear"] = enrollment["previousAcademicYear"]
            out["activeStudents"] = enrollment["activeStudents"]
            out["inactiveStudents"] = enrollment["inactiveStudents"]
            out["totalStudents"] = enrollment["totalStudents"]
            out["studentsChart"] = enrollment["studentsChart"]
            out["yearlyStudentsChart"] = enrollment["yearlyStudentsChart"]

        return out



class AdminInactiveStudentsView(APIView):
    permission_classes = [AdminScopePermission("students")]

    def get(self, request):
        rows = [
            {
                "id": str(s.id),
                "name": s.name,
                "studentNumber": s.student_number,
                "nationalId": s.national_id or "",
                "grade": s.grade_level,
                "section": s.section or "",
                "createdAt": s.created_at.isoformat(),
            }
            for s in Student.objects.filter(is_active=False).order_by("-created_at", "name")
        ]
        return Response(rows)



class AdminScheduleViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics", "students")]
    serializer_class = ScheduleSerializer
    queryset = Schedule.objects.prefetch_related("school_classes").all()
    parser_classes = [JSONParser]

    def get_queryset(self):
        qs = super().get_queryset()
        schedule_type = (self.request.query_params.get("type") or "").strip()
        if schedule_type in ("exam", "class"):
            qs = qs.filter(schedule_type=schedule_type)

        scope = (self.request.query_params.get("scope") or "current").strip().lower()
        if scope == "previous":
            from academics.schedule_rollover_services import get_previous_operational_term

            previous_term = get_previous_operational_term()
            if not previous_term:
                return qs.none()
            return qs.filter(academic_term=previous_term)
        return _scope_operational_term(qs)

    @action(detail=False, methods=["get"], url_path="rollover-context")
    def rollover_context(self, request):
        from academics.schedule_rollover_services import serialize_schedule_rollover_context

        schedule_type = (request.query_params.get("type") or "").strip()
        if schedule_type not in ("exam", "class"):
            schedule_type = None
        return Response(serialize_schedule_rollover_context(schedule_type))

    @action(detail=False, methods=["post"], url_path="adopt")
    def adopt(self, request):
        from academics.schedule_rollover_services import adopt_schedules, normalize_schedule_rollover_mode
        from rest_framework.exceptions import ValidationError as DRFValidationError

        schedule_type = str(request.data.get("scheduleType") or "class").strip()
        if schedule_type not in ("exam", "class"):
            raise DRFValidationError({"scheduleType": "نوع الجدول غير صالح"})

        raw_class_ids = request.data.get("classIds") or []
        if not isinstance(raw_class_ids, list):
            raw_class_ids = [raw_class_ids]
        class_ids = [int(class_id) for class_id in raw_class_ids if str(class_id).strip()]

        mode = normalize_schedule_rollover_mode(request.data.get("mode"))
        try:
            results = adopt_schedules(class_ids, schedule_type, mode)
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)

        from config.serializers import ScheduleSerializer

        created_ids = [item["scheduleId"] for item in results if item.get("scheduleId")]
        created_schedules = Schedule.objects.filter(id__in=created_ids).prefetch_related("school_classes")
        return Response(
            {
                "results": results,
                "schedules": ScheduleSerializer(created_schedules, many=True).data,
            }
        )



class TeacherClassesView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])
        from staff.assignment_validation import teacher_school_classes

        return Response(SchoolClassSerializer(teacher_school_classes(teacher), many=True).data)



class TeacherClassDetailView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request, class_id):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        school_class, err = _teacher_school_class_or_response(teacher, class_id)
        if err:
            return err

        students = list(Student.objects.filter(school_class=school_class, is_active=True).order_by("name"))
        entries_by_student = {
            entry.student_id: entry
            for entry in ClassGradebook.objects.filter(
                school_class=school_class,
                student_id__in=[s.id for s in students],
            )
        }
        result = []
        for student in students:
            entry = entries_by_student.get(student.id)
            result.append({
                "id": str(student.id),
                "name": student.name,
                "nationalId": student.national_id or "",
                "grade": float(entry.score) if entry and entry.score is not None else "",
                "note": entry.note if entry else "",
            })
        return Response(ClassStudentSerializer(result, many=True).data)

    def patch(self, request, class_id):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        school_class, err = _teacher_school_class_or_response(teacher, class_id)
        if err:
            return err

        entries = request.data if isinstance(request.data, list) else request.data.get("entries", [])
        student_ids = []
        for entry in entries:
            sid = entry.get("studentId") or entry.get("id")
            if sid is not None:
                student_ids.append(str(sid))

        allowed_ids = set(
            str(sid)
            for sid in Student.objects.filter(
                school_class=school_class, is_active=True, id__in=student_ids
            ).values_list("id", flat=True)
        )

        with transaction.atomic():
            for entry in entries:
                student_id = entry.get("studentId") or entry.get("id")
                if student_id is None:
                    continue
                if str(student_id) not in allowed_ids:
                    return Response(
                        {"detail": f"الطالب {student_id} لا ينتمي لهذا الصف"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                score, score_err = _parse_gradebook_score(entry.get("grade"))
                if score_err:
                    return score_err
                ClassGradebook.objects.update_or_create(
                    student_id=student_id,
                    school_class_id=class_id,
                    defaults={
                        "score": score,
                        "note": entry.get("note", ""),
                        "teacher": teacher,
                    },
                )
        return self.get(request, class_id)



class TeacherGradeSchemeView(APIView):
    permission_classes = [IsTeacher]

    def _parse_class_ids(self, values, fallback=None):
        ids: list[str] = []
        if isinstance(values, list):
            for value in values:
                if value is None:
                    continue
                text = str(value).strip()
                if not text:
                    continue
                if "," in text:
                    ids.extend(part.strip() for part in text.split(",") if part.strip())
                else:
                    ids.append(text)
        elif values:
            text = str(values).strip()
            if text:
                ids.extend(part.strip() for part in text.split(",") if part.strip())
        if not ids and fallback:
            text = str(fallback).strip()
            if text:
                ids.append(text)
        return ids

    def _parse_subjects(self, values, fallback=None):
        if isinstance(values, list):
            return [str(value).strip() for value in values if str(value).strip()]
        if values:
            text = str(values).strip()
            return [text] if text else []
        if fallback:
            text = str(fallback).strip()
            return [text] if text else []
        return []

    def _school_classes_for_teacher(self, teacher, class_ids):
        from academics.grade_scheme_services import teacher_teachable_class_ids

        allowed_ids = set(teacher_teachable_class_ids(teacher))
        school_classes = []
        for class_id in class_ids:
            school_class = SchoolClass.objects.filter(id=class_id).first()
            if not school_class:
                raise ValidationError({"classIds": f"الفصل {class_id} غير موجود"})
            if school_class.id not in allowed_ids:
                raise ValidationError({"classIds": f"لا تدرّس في فصل {school_class.name}"})
            school_classes.append(school_class)
        return school_classes

    def get(self, request):
        from academics.grade_scheme_services import (
            ensure_teacher_schemes_for_classes,
            get_grade_scheme_template,
            pick_representative_scheme,
            serialize_entries_for_classes,
            serialize_grade_scheme,
            serialize_grade_scheme_template,
            teacher_subjects_for_classes,
        )
        from academics.academic_services import serialize_academic_context

        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        class_ids = self._parse_class_ids(
            request.query_params.getlist("classIds"),
            request.query_params.get("classId") or request.query_params.get("classIds"),
        )
        subject = (request.query_params.get("subject") or "").strip()

        if not class_ids:
            return Response(
                {
                    "availableSubjects": [],
                    "scheme": None,
                    "entries": [],
                    "classIds": [],
                    "subjects": [],
                }
            )

        school_classes = self._school_classes_for_teacher(teacher, class_ids)
        available_subjects = teacher_subjects_for_classes(teacher, school_classes)
        template = get_grade_scheme_template()

        schemes = []
        if subject and template:
            schemes = ensure_teacher_schemes_for_classes(teacher, school_classes, subject, template)
        elif subject:
            academic_term = require_current_academic_term()
            class_ids_int = [school_class.id for school_class in school_classes]
            found = {
                scheme.school_class_id: scheme
                for scheme in SubjectGradeScheme.objects.filter(
                    teacher=teacher,
                    school_class_id__in=class_ids_int,
                    subject=subject,
                    academic_term=academic_term,
                ).select_related("school_class")
            }
            schemes = [found.get(school_class.id) for school_class in school_classes]

        representative = pick_representative_scheme(schemes)
        if representative:
            scheme_payload = serialize_grade_scheme(representative)
        elif template:
            scheme_payload = serialize_grade_scheme_template(template)
        else:
            scheme_payload = None
        return Response(
            {
                "availableSubjects": available_subjects,
                "scheme": scheme_payload,
                "entries": serialize_entries_for_classes(teacher, school_classes, subject),
                "classIds": [str(school_class.id) for school_class in school_classes],
                "subjects": [subject] if subject else [],
                "academicContext": serialize_academic_context(),
            }
        )

    def put(self, request):
        return Response(
            {"detail": "تقسيمة العلامات تُدار من قبل الإدارة فقط"},
            status=status.HTTP_403_FORBIDDEN,
        )

    def patch(self, request):
        from academics.academic_services import serialize_academic_context
        from academics.grade_scheme_services import (
            pick_representative_scheme,
            save_scheme_entries_for_subjects,
            serialize_entries_for_classes,
            serialize_grade_scheme,
        )
        from rest_framework.exceptions import ValidationError as DRFValidationError

        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        class_ids = self._parse_class_ids(request.data.get("classIds"), request.data.get("classId"))
        subjects = self._parse_subjects(request.data.get("subjects"), request.data.get("subject"))
        if not class_ids or not subjects:
            raise ValidationError({"detail": "اختر الفصول والمواد"})

        school_classes = self._school_classes_for_teacher(teacher, class_ids)
        entries = request.data.get("entries") or []
        try:
            schemes = save_scheme_entries_for_subjects(teacher, school_classes, subjects, entries)
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)

        representative = pick_representative_scheme(schemes)
        representative = SubjectGradeScheme.objects.select_related("school_class").get(pk=representative.pk)
        active_subject = request.data.get("activeSubject") or subjects[0]
        if active_subject not in subjects:
            active_subject = subjects[0]
        return Response(
            {
                "scheme": serialize_grade_scheme(representative),
                "entries": serialize_entries_for_classes(teacher, school_classes, active_subject),
                "classIds": [str(school_class.id) for school_class in school_classes],
                "subjects": subjects,
                "academicContext": serialize_academic_context(),
            }
        )



class TeacherSchedulesView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])

        teacher_name = _normalize_teacher_name(teacher.name)
        qs = _scope_operational_term(
            Schedule.objects.filter(is_published=True, schedule_type="class")
            .prefetch_related("school_classes")
            .order_by("-updated_at", "-id")
        )

        rows = []
        for schedule in qs:
            class_labels = [_school_class_label(school_class) for school_class in schedule.school_classes.all()]
            class_label = " · ".join(class_labels)
            for index, entry in enumerate(schedule.entries or []):
                if not isinstance(entry, dict):
                    continue
                entry_teacher = _normalize_teacher_name(entry.get("teacher") or "")
                if not entry_teacher or entry_teacher != teacher_name:
                    continue
                subject = _schedule_entry_text(entry.get("subject"))
                if not subject:
                    continue
                day = _schedule_entry_text(entry.get("day"))
                period = _schedule_entry_text(entry.get("period"))
                time = _schedule_entry_text(entry.get("time"))
                duration = _schedule_entry_text(entry.get("duration"), "60")
                rows.append(
                    {
                        "id": f"{schedule.id}-{index}-{day}-{time}-{subject}",
                        "scheduleId": str(schedule.id),
                        "scheduleName": schedule.name,
                        "day": day,
                        "period": period,
                        "time": time,
                        "duration": duration,
                        "subject": subject,
                        "classLabel": class_label,
                    }
                )

        def sort_key(row):
            day_index = (
                WEEK_DAYS_ORDER.index(row["day"]) if row["day"] in WEEK_DAYS_ORDER else 99
            )
            return (day_index, row["time"])

        rows.sort(key=sort_key)
        return Response(rows)



class ParentChildView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)
        data = ParentChildSerializer({
            "parentUserId": str(request.user.id),
            "studentId": str(child.id),
            "classId": str(child.school_class_id) if child.school_class_id else "",
            "name": child.name,
        }).data
        return Response(data)



class ParentStudentView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        linked = _linked_student_for_parent(request.user)
        if not linked:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)

        fee_status = build_fee_status(linked, link_plan=False)
        payload = StudentSerializer(linked, context={"request": request}).data
        access_restricted = bool(fee_status.get("blocked"))
        if access_restricted:
            payload["accessRestricted"] = True
            payload["accessRestrictionReason"] = "fees"
            payload["accessRestrictionMessage"] = fee_status.get("message") or (
                "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم المستحقة. "
                "يرجى تسديد المبلغ المطلوب أو زيارة صفحة المالية."
            )
        elif not linked.is_active:
            payload["accessRestricted"] = True
            payload["accessRestrictionReason"] = "inactive"
            payload["accessRestrictionMessage"] = (
                "حساب الطالب بانتظار التفعيل من الإدارة. يرجى التواصل مع المدرسة."
            )
        return Response(payload)



class ParentGradesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.grade_scheme_services import (
            mark_parent_grades_seen,
            serialize_parent_subject_grades,
        )

        child = _child_for_parent(request.user)
        if not child:
            return Response([])
        mark_parent_grades_seen(request.user, child)
        return Response(serialize_parent_subject_grades(child))



class ParentGradesNotificationView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.grade_scheme_services import get_parent_grades_notification

        child = _child_for_parent(request.user)
        if not child:
            return Response({"hasNew": False, "count": 0})
        return Response(get_parent_grades_notification(child, request.user))



class ParentCertificatesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.certificate_services import serialize_parent_current_certificates

        child = _child_for_parent(request.user)
        if not child:
            return Response({"published": False, "message": "لا يوجد طالب مرتبط", "certificate": None})
        return Response(serialize_parent_current_certificates(child))



class ParentAssessmentsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response([])

        items = []

        from academics.academic_services import get_current_academic_term

        current_term = get_current_academic_term()
        hw_subs = HomeworkSubmission.objects.filter(
            student=child,
            homework__grades_visible=True,
            score__isnull=False,
        )
        if current_term:
            hw_subs = hw_subs.filter(homework__academic_term=current_term)
        hw_subs = hw_subs.select_related("homework").order_by("-graded_at", "-submitted_at")
        for sub in hw_subs:
            at = sub.graded_at or sub.submitted_at
            items.append(
                {
                    "id": str(sub.id),
                    "kind": "homework",
                    "refId": str(sub.homework_id),
                    "title": sub.homework.title,
                    "subject": sub.homework.subject or "عام",
                    "score": float(sub.score),
                    "maxScore": float(sub.homework.max_score),
                    "teacherNote": sub.teacher_note or "",
                    "at": at.isoformat() if at else None,
                }
            )

        quiz_subs = QuizSubmission.objects.filter(student=child, quiz__grades_visible=True)
        if current_term:
            quiz_subs = quiz_subs.filter(quiz__academic_term=current_term)
        quiz_subs = quiz_subs.select_related("quiz").prefetch_related("quiz__questions").order_by(
            "-score", "-attempt_number"
        )
        from assignments.quiz_services import quiz_submission_fully_graded

        seen_quiz_ids = set()
        for sub in quiz_subs:
            if sub.quiz_id in seen_quiz_ids:
                continue
            seen_quiz_ids.add(sub.quiz_id)
            questions = list(sub.quiz.questions.all())
            if not quiz_submission_fully_graded(sub, questions):
                continue
            items.append(
                {
                    "id": str(sub.id),
                    "kind": "quiz",
                    "refId": str(sub.quiz_id),
                    "title": sub.quiz.title,
                    "subject": sub.quiz.subject or "عام",
                    "score": float(sub.score),
                    "maxScore": float(sub.max_score),
                    "teacherNote": sub.teacher_note or "",
                    "at": sub.graded_at.isoformat() if sub.graded_at else sub.submitted_at.isoformat(),
                }
            )

        items.sort(key=lambda row: row.get("at") or "", reverse=True)
        return Response(items)



class ParentSchedulesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])

        schedule_type = (request.query_params.get("type") or "").strip()
        qs = _scope_operational_term(Schedule.objects.filter(is_published=True).prefetch_related("school_classes"))
        if schedule_type in ("exam", "class"):
            qs = qs.filter(schedule_type=schedule_type)

        qs = qs.filter(school_classes__id=child.school_class_id).distinct().order_by("-updated_at", "-id")
        return Response(ScheduleSerializer(qs, many=True).data)


WEEK_DAYS_ORDER = [
    "السبت",
    "الأحد",
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
]



class AcademicContextView(CachedAPIViewMixin, APIView):
    permission_classes = [IsAuthenticated]
    cache_prefix = "academic:context"
    cache_ttl = 120

    def get(self, request):
        return self.get_cached(request, serialize_academic_context)



class AdminAcademicYearViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics")]
    serializer_class = AcademicYearWriteSerializer
    queryset = AcademicYear.objects.prefetch_related("terms").all()

    def get_object(self):
        from rest_framework.exceptions import NotFound

        try:
            return super().get_object()
        except NotFound as exc:
            raise NotFound("السنة الدراسية غير موجودة. حدّث الصفحة وحاول مرة أخرى.") from exc

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        year = self.get_object()
        set_active_academic_year(year)
        return Response(serialize_academic_year(year))

    def destroy(self, request, *args, **kwargs):
        year = self.get_object()
        if year.is_active:
            return Response(
                {"detail": "لا يمكن حذف السنة الدراسية النشطة"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="set-current-term")
    def set_current_term(self, request, pk=None):
        year = self.get_object()
        term_id = str(request.data.get("termId") or "").strip()
        if not term_id:
            return Response({"detail": "يجب تحديد الفصل الدراسي"}, status=status.HTTP_400_BAD_REQUEST)
        term = AcademicTerm.objects.filter(id=term_id, academic_year=year).first()
        if not term:
            return Response({"detail": "الفصل الدراسي غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        if term.is_closed:
            return Response({"detail": "لا يمكن تعيين فصل مُغلق كفصل حالي"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            set_current_academic_term(term)
        except serializers.ValidationError as exc:
            from rest_framework.exceptions import ValidationError as DRFValidationError
            raise DRFValidationError(exc.detail)
        return Response(serialize_academic_year(year))

    @action(detail=True, methods=["get"], url_path="term-end-preview")
    def term_end_preview(self, request, pk=None):
        from academics.term_end_services import preview_term_end
        from rest_framework.exceptions import ValidationError as DRFValidationError

        year = self.get_object()
        term_id = str(request.query_params.get("termId") or "").strip() or None
        try:
            return Response(preview_term_end(year, term_id=term_id))
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)

    @action(detail=True, methods=["post"], url_path="execute-term-end")
    def execute_term_end(self, request, pk=None):
        from academics.academic_services import serialize_academic_year
        from academics.term_end_services import execute_term_end
        from rest_framework.exceptions import ValidationError as DRFValidationError

        year = self.get_object()
        term_id = str(request.data.get("termId") or "").strip() or None
        publish_certs = request.data.get("publishCertificates", True)
        try:
            result = execute_term_end(
                year,
                request.user,
                term_id=term_id,
                publish_certs=bool(publish_certs),
            )
            year.refresh_from_db()
            result["academicYear"] = serialize_academic_year(year)
            return Response(result)
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)

    @action(detail=True, methods=["get", "post"], url_path="promotion-preview")
    def promotion_preview(self, request, pk=None):
        from academics.promotion_services import preview_year_end

        year = self.get_object()
        overrides = {}
        if request.method == "POST" and isinstance(request.data.get("decisions"), list):
            for item in request.data["decisions"]:
                if not isinstance(item, dict):
                    continue
                student_id = str(item.get("studentId") or item.get("id") or "").strip()
                action = str(item.get("action") or "").strip()
                if student_id and action in {"promote", "repeat", "graduate"}:
                    overrides[student_id] = action
        return Response(preview_year_end(year, overrides=overrides))

    @action(detail=True, methods=["post"], url_path="execute-rollover")
    def execute_rollover(self, request, pk=None):
        from academics.promotion_services import execute_year_end
        from rest_framework.exceptions import ValidationError as DRFValidationError

        year = self.get_object()
        try:
            result = execute_year_end(
                year,
                request.user,
                decisions=request.data.get("decisions"),
                publish_certs=bool(request.data.get("publishCertificates", True)),
            )
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)
        return Response(result)

    @action(detail=True, methods=["get", "patch"], url_path="certificate-config")
    def certificate_config(self, request, pk=None):
        from academics.certificate_services import (
            get_or_create_certificate_config,
            serialize_certificate_config,
            update_certificate_config,
        )

        year = self.get_object()
        config = get_or_create_certificate_config(year)
        if request.method == "PATCH":
            config = update_certificate_config(year, request.data)
        return Response(serialize_certificate_config(config))

    @action(detail=True, methods=["post"], url_path="publish-certificates")
    def publish_certificates(self, request, pk=None):
        from academics.certificate_services import publish_certificates, serialize_certificate_config
        from rest_framework.exceptions import ValidationError as DRFValidationError

        year = self.get_object()
        try:
            config = publish_certificates(year, request.user, term_id=request.data.get("termId"))
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)
        return Response(serialize_certificate_config(config))

    @action(detail=True, methods=["post"], url_path="unpublish-certificates")
    def unpublish_certificates(self, request, pk=None):
        from academics.certificate_services import serialize_certificate_config, unpublish_certificates

        year = self.get_object()
        config = unpublish_certificates(year)
        return Response(serialize_certificate_config(config))

    @action(detail=True, methods=["get", "post"], url_path="certificate-preview")
    def certificate_preview(self, request, pk=None):
        from academics.certificate_services import preview_certificates
        from rest_framework.exceptions import ValidationError as DRFValidationError

        year = self.get_object()
        overrides = {}
        if request.method == "POST" and isinstance(request.data, dict):
            for key in (
                "termId",
                "issuanceScope",
                "honorsEnabled",
                "honorsMinAverage",
                "honorsTitle",
                "honorsMessage",
                "certificateTitle",
            ):
                if key in request.data:
                    overrides[key] = request.data[key]
        try:
            return Response(preview_certificates(year, overrides=overrides or None))
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)



class ParentArchiveView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.archive_services import serialize_parent_archive_overview

        child = _child_for_parent(request.user)
        if not child:
            return Response({"years": []})
        return Response({"years": serialize_parent_archive_overview(child)})



class ParentArchiveTermGradesView(APIView):
    permission_classes = [IsParent]

    def get(self, request, term_id):
        from academics.archive_services import serialize_parent_archive_term_grades
        from rest_framework.exceptions import ValidationError as DRFValidationError

        child = _child_for_parent(request.user)
        if not child:
            return Response([])
        term = AcademicTerm.objects.select_related("academic_year").filter(id=term_id).first()
        if not term:
            return Response({"detail": "الفصل غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Response(serialize_parent_archive_term_grades(child, term))
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)



class ParentArchiveCertificatesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.certificate_services import serialize_parent_archived_certificates

        child = _child_for_parent(request.user)
        if not child:
            return Response(
                {
                    "published": False,
                    "message": "لا يوجد طالب مرتبط",
                    "config": None,
                    "certificate": None,
                    "certificates": [],
                }
            )
        return Response(serialize_parent_archived_certificates(child))



class TeacherArchiveView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        from academics.archive_services import serialize_teacher_archive_overview

        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"years": []})
        return Response({"years": serialize_teacher_archive_overview(teacher)})



class TeacherArchiveTermClassesView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request, term_id):
        from academics.archive_services import serialize_teacher_archive_term_classes

        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])
        term = AcademicTerm.objects.select_related("academic_year").filter(id=term_id).first()
        if not term:
            return Response({"detail": "الفصل غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_teacher_archive_term_classes(teacher, term))



class TeacherArchiveClassGradesView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request, term_id, class_id):
        from academics.archive_services import serialize_teacher_archive_class_grades

        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"subjects": [], "students": []})
        term = AcademicTerm.objects.select_related("academic_year").filter(id=term_id).first()
        school_class = SchoolClass.objects.filter(id=class_id).first()
        if not term or not school_class:
            return Response({"detail": "العنصر غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        subject = str(request.query_params.get("subject") or "").strip() or None
        return Response(
            serialize_teacher_archive_class_grades(teacher, term, school_class, subject=subject)
        )
