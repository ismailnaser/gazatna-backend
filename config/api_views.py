from datetime import date, timedelta
from decimal import Decimal
import re
import uuid

from django.db.models import Avg, Count, Max, Sum
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
    ensure_default_academic_calendar,
    require_current_academic_term,
    serialize_academic_context,
    serialize_academic_year,
    set_active_academic_year,
    set_current_academic_term,
)
from accounts.models import User
from accounts.roles import ADMIN_ROLES
from accounts.serializers import UserCreateSerializer, UserSerializer
from accounts.utils import generate_five_digit_password
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
from config.jobs import enqueue_job, run_async
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
    restore_student_access_after_fees,
)
from staff.models import TeacherClassAssignment, TeacherProfile, TeacherReadAlert
from staff.assignment_validation import (
    class_subject_assignments,
    collect_subject_class_conflicts,
    sync_subject_section_teachers,
    school_class_id_for_student,
    validate_homeroom_teacher,
    validate_teacher_subject_class_assignments,
)


def _teacher_for_user(user):
    return TeacherProfile.objects.filter(user=user).first()


def _parse_class_ids(data):
    if hasattr(data, "getlist"):
        ids = data.getlist("classIds")
        if ids:
            return [str(x) for x in ids if x]
    raw = data.get("classIds")
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if data.get("classId"):
        return [str(data.get("classId"))]
    return []


def _publish_homework_grades(homework):
    if homework.grades_visible:
        return
    if homework.group_id:
        Homework.objects.filter(group_id=homework.group_id).update(grades_visible=True)
    else:
        homework.grades_visible = True
        homework.save(update_fields=["grades_visible"])


def _publish_quiz_grades(quiz):
    if quiz.grades_visible:
        return
    if quiz.group_id:
        Quiz.objects.filter(group_id=quiz.group_id).update(grades_visible=True)
    else:
        quiz.grades_visible = True
        quiz.save(update_fields=["grades_visible"])


AR_MONTHS = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
}


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    month += offset
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def _build_fees_chart() -> list[dict]:
    total_fees = StudentFeeBalance.objects.aggregate(t=Sum("total"))["t"] or 0
    if not total_fees:
        return []

    today = date.today()
    fees_chart = []
    for offset in range(-5, 1):
        year, month = _shift_month(today.year, today.month, offset)
        approved = PaymentNotice.objects.filter(
            status="approved",
            date__year=year,
            date__month=month,
        ).aggregate(s=Sum("amount"))["s"] or 0
        if not approved:
            continue
        pct = round(float(approved) / float(total_fees) * 100, 1)
        fees_chart.append({"label": AR_MONTHS[month], "value": pct})
    return fees_chart


def _build_grade_chart() -> list[dict]:
    from academics.analytics_services import grade_chart_by_level

    return grade_chart_by_level()


def _linked_student_for_parent(user):
    return (
        Student.objects.filter(parent=user)
        .select_related("school_class", "fee_balance")
        .order_by("-is_active", "-id")
        .first()
    )


def _child_for_parent(user):
    student = _linked_student_for_parent(user)
    if not student:
        return None
    if build_fee_status(student).get("blocked"):
        return None
    return student


def _subject_label(value):
    label = (value or "").strip()
    return label or "عام"


def _subject_homework_q(subject_label):
    from django.db.models import Q

    if subject_label == "عام":
        return Q(subject="") | Q(subject__isnull=True) | Q(subject="عام")
    return Q(subject=subject_label)


def _subject_quiz_q(subject_label):
    from django.db.models import Q

    if subject_label == "عام":
        return Q(subject="") | Q(subject__isnull=True) | Q(subject="عام")
    return Q(subject=subject_label)


def _subject_announcement_q(subject_label):
    from django.db.models import Q

    if subject_label == "عام":
        return Q(subject="") | Q(subject__isnull=True) | Q(subject="عام")
    return Q(subject=subject_label)


def _subject_material_q(subject_label):
    from django.db.models import Q

    if subject_label == "عام":
        return Q(subject="") | Q(subject__isnull=True) | Q(subject="عام")
    return Q(subject=subject_label)


class PublicNewsViewSet(CachedReadOnlyViewSetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = NewsItemSerializer
    queryset = NewsItem.objects.filter(is_published=True).prefetch_related("images")
    cache_prefix = "public:news"


class PublicProgramViewSet(CachedReadOnlyViewSetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = ProgramSerializer
    queryset = Program.objects.all()
    cache_prefix = "public:programs"


class PublicStatsView(CachedAPIViewMixin, APIView):
    permission_classes = [AllowAny]
    cache_prefix = "public:stats"

    def get(self, request):
        return self.get_cached(
            request,
            lambda: SchoolStatSerializer(SchoolStat.objects.all(), many=True).data,
        )


class PublicSchoolValuesView(CachedAPIViewMixin, APIView):
    permission_classes = [AllowAny]
    cache_prefix = "public:values"

    def get(self, request):
        return self.get_cached(
            request,
            lambda: SchoolValueSerializer(SchoolValue.objects.all(), many=True).data,
        )


class PublicTeachersViewSet(CachedReadOnlyViewSetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = TeacherProfileSerializer
    queryset = TeacherProfile.objects.filter(is_public=True).prefetch_related(
        "teaching_subjects",
        "class_assignments",
        "homeroom_classes",
    )
    cache_prefix = "public:teachers"


class AdminUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    queryset = User.objects.filter(role__in=ADMIN_ROLES).order_by("id")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserCreateSerializer
        return UserSerializer

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = generate_five_digit_password()
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return Response(
            {
                "userId": str(user.id),
                "name": user.display_name,
                "username": user.username,
                "password": new_password,
            }
        )


class AdminStudentViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("students")]
    serializer_class = StudentSerializer
    queryset = Student.objects.select_related("school_class", "fee_balance").all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _save_documents(self, student, request):
        names = request.data.getlist("documentNames") if hasattr(request.data, "getlist") else []
        files = request.FILES.getlist("documentFiles") if hasattr(request.FILES, "getlist") else []
        if not names and not files:
            return
        # Align lengths (ignore extra files or names)
        for i in range(min(len(names), len(files))):
            name = str(names[i]).strip() or "وثيقة"
            StudentDocument.objects.create(student=student, name=name, file=files[i])

    def perform_create(self, serializer):
        student = serializer.save()
        self._save_documents(student, self.request)
        StudentFeeBalance.objects.get_or_create(student=student, defaults={"total": 0, "paid": 0})
        apply_plan_to_student(student)

    def perform_destroy(self, instance):
        parent = instance.parent
        instance.delete()
        if parent:
            parent.delete()

    def _serialize_document(self, doc, request):
        url = doc.file.url if doc.file else None
        if url and request:
            url = request.build_absolute_uri(url)
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
        new_password = generate_five_digit_password()
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


def _sync_grade_sections(grade: Grade):
    desired = int(grade.sections_count or 0)
    desired = max(1, min(desired, len(SECTION_LABELS)))
    grade.sections_count = desired
    grade.save(update_fields=["sections_count"])

    existing = list(SchoolClass.objects.filter(grade_level=grade.name).order_by("id"))
    existing_by_section = {c.section: c for c in existing if c.section}

    desired_sections = SECTION_LABELS[:desired]

    # Create missing sections
    for sec in desired_sections:
        if sec in existing_by_section:
            cls = existing_by_section[sec]
            expected_name = f"{grade.name} - {sec}"
            if cls.name != expected_name:
                cls.name = expected_name
                cls.save(update_fields=["name"])
        else:
            SchoolClass.objects.create(
                grade_level=grade.name,
                section=sec,
                name=f"{grade.name} - {sec}",
            )

    # Remove extra sections (students are unlinked via SET_NULL on school_class)
    for cls in existing:
        if cls.section and cls.section not in desired_sections:
            cls.delete()


def _sync_grade_sections_count(grade_name: str):
    grade = Grade.objects.filter(name=grade_name).first()
    if not grade:
        return
    remaining = SchoolClass.objects.filter(grade_level=grade_name).count()
    if remaining == 0:
        grade.delete()
    elif remaining != grade.sections_count:
        grade.sections_count = remaining
        grade.save(update_fields=["sections_count"])


class AdminGradeViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminGradePermission]
    serializer_class = GradeSerializer
    queryset = Grade.objects.prefetch_related("promotion_policy").order_by("sort_order", "id")

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


class AdminTeacherViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("staff")]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            permission_classes = [AdminScopePermission("staff", "academics")]
        else:
            permission_classes = [AdminScopePermission("staff")]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        return TeacherProfile.objects.prefetch_related(
            "class_assignments", "teaching_subjects", "homeroom_classes"
        ).all()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TeacherWriteSerializer
        return TeacherProfileSerializer

    def perform_destroy(self, instance):
        user = instance.user
        instance.delete()
        if user:
            user.delete()

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        teacher = self.get_object()
        if not teacher.user_id:
            return Response({"detail": "لا يوجد حساب مرتبط بهذا المعلم"}, status=status.HTTP_400_BAD_REQUEST)
        new_password = generate_five_digit_password()
        teacher.user.set_password(new_password)
        teacher.user.save(update_fields=["password"])
        return Response(
            {
                "teacherId": str(teacher.id),
                "name": teacher.name,
                "username": teacher.user.username,
                "password": new_password,
            }
        )


class AdminFeePlanViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("finance")]
    serializer_class = FeePlanSerializer
    queryset = FeePlan.objects.prefetch_related("grades", "installments").all()

    def perform_create(self, serializer):
        plan = serializer.save()
        run_async(apply_plan_to_students, plan)

    def perform_update(self, serializer):
        plan = serializer.save()
        run_async(apply_plan_to_students, plan)


class AdminFinanceViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("finance")]
    serializer_class = PaymentNoticeSerializer
    queryset = PaymentNotice.objects.select_related("student").all()

    def get_serializer_class(self):
        return PaymentNoticeSerializer

    def list(self, request, *args, **kwargs):
        notices = PaymentNotice.objects.select_related("student", "reviewed_by").order_by("-date", "-id")
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
                    "receiptUrl": request.build_absolute_uri(n.receipt.url) if n.receipt else None,
                    "source": n.source,
                    "reviewedByName": n.reviewed_by.display_name if n.reviewed_by else None,
                }
                for n in notices
            ],
            many=True,
        ).data
        return Response(data)

    def partial_update(self, request, *args, **kwargs):
        notice = self.get_object()
        old_status = notice.status
        new_status = request.data.get("status")
        if new_status:
            if new_status == PaymentStatus.APPROVED and old_status != PaymentStatus.APPROVED:
                approve_amount = Decimal(str(request.data.get("amount", notice.amount)))
                notice.amount = approve_amount
                balance, _ = StudentFeeBalance.objects.get_or_create(student=notice.student)
                balance.paid += approve_amount
                balance.save(update_fields=["paid"])
                restore_student_access_after_fees(notice.student)
            elif new_status in (PaymentStatus.PENDING, PaymentStatus.REJECTED) and old_status == PaymentStatus.APPROVED:
                balance, _ = StudentFeeBalance.objects.get_or_create(student=notice.student)
                balance.paid = max(Decimal("0"), balance.paid - notice.amount)
                balance.save(update_fields=["paid"])
            notice.status = new_status
            notice.reviewed_by = request.user
            notice.save()
        elif "amount" in request.data and notice.status == PaymentStatus.PENDING:
            notice.amount = Decimal(str(request.data["amount"]))
            notice.save(update_fields=["amount"])
        return Response(PaymentNoticeSerializer(notice, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        notice = self.get_object()
        if notice.source != PaymentSource.MANUAL:
            return Response(
                {"detail": "يمكن إلغاء الدفعات اليدوية فقط من هذا السجل"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if notice.status == PaymentStatus.APPROVED:
            balance, _ = StudentFeeBalance.objects.get_or_create(student=notice.student)
            balance.paid = max(Decimal("0"), balance.paid - notice.amount)
            balance.save(update_fields=["paid"])
        notice.delete()
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
        amount_raw = request.data.get("amount")
        note = str(request.data.get("note", "")).strip() or "دفع يدوي — خارج المنصة"

        if not student_id:
            return Response({"detail": "يجب اختيار الطالب"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            return Response({"detail": "المبلغ غير صالح"}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= 0:
            return Response({"detail": "المبلغ يجب أن يكون أكبر من صفر"}, status=status.HTTP_400_BAD_REQUEST)

        student = Student.objects.filter(id=student_id).select_related("fee_balance").first()
        if not student:
            return Response({"detail": "الطالب غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        today = timezone.now().date()
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
        balance, _ = StudentFeeBalance.objects.get_or_create(student=student, defaults={"total": 0, "paid": 0})
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


class AdminAnalyticsView(CachedAPIViewMixin, APIView):
    permission_classes = [IsAdmin]
    cache_prefix = "admin:analytics"
    cache_ttl = 120

    def get(self, request):
        return self.get_cached(request, lambda: self._build_payload())

    def _build_payload(self):
        from academics.analytics_services import average_grade_percent

        avg_grade = average_grade_percent()
        balances = StudentFeeBalance.objects.all()
        total_fees = balances.aggregate(t=Sum("total"))["t"] or 0
        paid_fees = balances.aggregate(p=Sum("paid"))["p"] or 0
        fees_collected = round(float(paid_fees) / float(total_fees) * 100, 1) if total_fees else 0

        pending_count = PaymentNotice.objects.filter(status="pending").count()

        inactive_students = Student.objects.filter(is_active=False).count()
        pending_admissions = AdmissionApplication.objects.filter(status="pending").count()
        new_messages = ContactMessage.objects.filter(status="new").count()

        # Only active students can be blocked from platform access
        active_students = Student.objects.filter(is_active=True).select_related("fee_balance")
        blocked_students = 0
        overdue_students = 0
        for s in active_students.iterator():
            st = build_fee_status(s)
            if st.get("blocked"):
                blocked_students += 1
                overdue_students += 1

        urgent_tasks = []
        if pending_count:
            urgent_tasks.append({
                "id": "t1",
                "text": f"{pending_count} إشعارات دفع تنتظر الموافقة",
                "type": "finance",
            })
        if blocked_students:
            urgent_tasks.append({
                "id": "t_blocked",
                "text": f"{blocked_students} طلاب محجوبون بسبب الرسوم",
                "type": "fees_blocked",
            })
        if inactive_students:
            urgent_tasks.append({
                "id": "t_inactive",
                "text": f"{inactive_students} طلاب غير نشطين ينتظرون التفعيل",
                "type": "students_inactive",
            })
        if pending_admissions:
            urgent_tasks.append({
                "id": "t_admissions",
                "text": f"{pending_admissions} طلبات قبول/تسجيل جديدة",
                "type": "admissions",
            })
        if new_messages:
            urgent_tasks.append({
                "id": "t_messages",
                "text": f"{new_messages} رسائل جديدة من تواصل معنا",
                "type": "messages",
            })

        grade_chart = _build_grade_chart()
        fees_chart = _build_fees_chart()

        return {
            "avgGrade": avg_grade,
            "feesCollected": fees_collected,
            "pendingPayments": pending_count,
            "inactiveStudents": inactive_students,
            "blockedStudents": blocked_students,
            "overdueInstallments": overdue_students,
            "pendingAdmissions": pending_admissions,
            "newMessages": new_messages,
            "urgentTasks": urgent_tasks,
            "gradeChart": grade_chart,
            "feesChart": fees_chart,
        }


class AdminAnalyticsDetailsView(APIView):
    permission_classes = [AdminScopePermission("academics", "finance")]

    def get(self, request):
        grade_level = (request.query_params.get("gradeLevel") or "").strip()
        from_raw = (request.query_params.get("from") or "").strip()
        to_raw = (request.query_params.get("to") or "").strip()

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

        grades_qs = SubjectGrade.objects.select_related("student")
        balances_qs = StudentFeeBalance.objects.select_related("student")

        if grade_level:
            grades_qs = grades_qs.filter(student__grade_level=grade_level)
            balances_qs = balances_qs.filter(student__grade_level=grade_level)

        # Success rate chart by grade level (or a single grade if filtered)
        from academics.analytics_services import average_grade_percent, grade_chart_by_level

        grade_chart = grade_chart_by_level(grades_qs)

        # Fees collected % chart by grade level (or a single grade if filtered)
        balance_rows = (
            balances_qs.values("student__grade_level")
            .annotate(total=Sum("total"), paid=Sum("paid"))
            .order_by("student__grade_level")
        )

        paid_by_grade = {row["student__grade_level"]: (row["paid"] or 0) for row in balance_rows}
        total_by_grade = {row["student__grade_level"]: (row["total"] or 0) for row in balance_rows}

        # If a date range is provided, use approved payments in that window for the "paid" numerator.
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

        fees_chart = []
        for gl, total in total_by_grade.items():
            if not gl:
                continue
            paid = paid_by_grade.get(gl, 0)
            pct = round(float(paid) / float(total) * 100, 1) if total else 0
            fees_chart.append({"label": gl, "value": pct})

        # Summary tiles for the current filter
        avg_grade = average_grade_percent(grades_qs)
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

        fees_collected = round(float(paid_fees) / float(total_fees) * 100, 1) if total_fees else 0

        return Response(
            {
                "avgGrade": avg_grade,
                "feesCollected": fees_collected,
                "urgentTasks": [],
                "gradeChart": grade_chart,
                "feesChart": fees_chart,
                "filters": {
                    "gradeLevel": grade_level or None,
                    "from": str(from_date) if from_date else None,
                    "to": str(to_date) if to_date else None,
                },
            }
        )


class AdminNewsViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("content")]
    serializer_class = NewsItemSerializer
    queryset = NewsItem.objects.prefetch_related("images").all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _clear_other_featured(self, item):
        NewsItem.objects.exclude(pk=item.pk).filter(featured=True).update(featured=False)

    def _sync_legacy_cover(self, item):
        cover = item.images.filter(is_cover=True).first() or item.images.order_by("order", "id").first()
        if cover and cover.file:
            item.image = cover.file
            item.save(update_fields=["image"])
        elif not item.images.exists():
            item.image = None
            item.save(update_fields=["image"])

    def _handle_gallery_images(self, item, request):
        delete_ids = request.data.getlist("deleteImageIds") if hasattr(request.data, "getlist") else []
        for image_id in delete_ids:
            img = item.images.filter(id=image_id).first()
            if not img:
                continue
            if img.file:
                img.file.delete(save=False)
            img.delete()

        files = request.FILES.getlist("galleryImages") if hasattr(request.FILES, "getlist") else []
        new_image_ids = []
        base_order = item.images.count()
        for index, uploaded in enumerate(files):
            created = NewsImage.objects.create(
                news_item=item,
                file=uploaded,
                is_cover=False,
                order=base_order + index,
            )
            new_image_ids.append(created.id)

        cover_image_id = request.data.get("coverImageId")
        cover_new_index = request.data.get("coverNewIndex")

        if cover_image_id:
            item.images.update(is_cover=False)
            item.images.filter(id=cover_image_id).update(is_cover=True)
        elif cover_new_index not in (None, "") and new_image_ids:
            try:
                idx = int(cover_new_index)
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(new_image_ids):
                item.images.update(is_cover=False)
                item.images.filter(id=new_image_ids[idx]).update(is_cover=True)
        elif files and not item.images.filter(is_cover=True).exists():
            first = item.images.order_by("order", "id").first()
            if first:
                first.is_cover = True
                first.save(update_fields=["is_cover"])

        legacy_image = request.FILES.get("image")
        if legacy_image and not files:
            if item.images.filter(is_cover=True).exists():
                item.images.filter(is_cover=True).update(is_cover=False)
            NewsImage.objects.create(
                news_item=item,
                file=legacy_image,
                is_cover=True,
                order=item.images.count(),
            )

        self._sync_legacy_cover(item)

    def perform_create(self, serializer):
        item = serializer.save()
        self._handle_gallery_images(item, self.request)
        if item.featured:
            self._clear_other_featured(item)

    def perform_update(self, serializer):
        item = serializer.save()
        self._handle_gallery_images(item, self.request)
        if item.featured:
            self._clear_other_featured(item)


class TeacherClassesView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])
        from staff.assignment_validation import teacher_school_classes

        return Response(SchoolClassSerializer(teacher_school_classes(teacher), many=True).data)


class TeacherProfileView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response(
                {"detail": "لم يتم ربط حسابك بملف معلم"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(TeacherProfileSerializer(teacher, context={"request": request}).data)


class TeacherClassDetailView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request, class_id):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        school_class = SchoolClass.objects.filter(id=class_id).first()
        if not school_class:
            return Response({"detail": "الصف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        students = Student.objects.filter(school_class=school_class, is_active=True)
        result = []
        for student in students:
            entry = ClassGradebook.objects.filter(student=student, school_class=school_class).first()
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
        entries = request.data if isinstance(request.data, list) else request.data.get("entries", [])
        for entry in entries:
            student_id = entry.get("studentId") or entry.get("id")
            ClassGradebook.objects.update_or_create(
                student_id=student_id,
                school_class_id=class_id,
                defaults={
                    "score": entry.get("grade") or None,
                    "note": entry.get("note", ""),
                    "teacher": teacher,
                },
            )
        return self.get(request, class_id)


class TeacherHomeworkViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]
    serializer_class = HomeworkSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return Homework.objects.none()
        qs = Homework.objects.filter(teacher=teacher).select_related("school_class", "teacher").prefetch_related(
            "attachment_files"
        )
        class_id = self.request.query_params.get("classId")
        if class_id:
            qs = qs.filter(school_class_id=class_id)
        return qs.order_by("-created_at")

    def _homework_defaults(self, request):
        from django.utils.dateparse import parse_datetime

        data = request.data
        start_at = parse_datetime(str(data.get("startAt", ""))) if data.get("startAt") else None
        end_at = parse_datetime(str(data.get("endAt", ""))) if data.get("endAt") else None
        due_raw = data.get("dueDate")
        if not due_raw and end_at:
            due_raw = end_at.date().isoformat()
        grades_visible = str(data.get("gradesVisible", "false")).lower() in ("1", "true", "yes")
        max_score_raw = data.get("maxScore", "100")
        try:
            max_score = Decimal(str(max_score_raw))
        except Exception:
            max_score = Decimal("100")
        if max_score <= 0:
            max_score = Decimal("100")
        payload = {
            "subject": str(data.get("subject", "")).strip(),
            "title": str(data.get("title", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "due_date": due_raw,
            "start_at": start_at,
            "end_at": end_at,
            "grades_visible": grades_visible,
            "max_score": max_score,
            "status": data.get("status", "active"),
        }
        return payload

    def perform_create(self, serializer):
        teacher = _teacher_for_user(self.request.user)
        serializer.save(teacher=teacher)

    def create(self, request, *args, **kwargs):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "لم يتم ربط حسابك بملف معلم"}, status=status.HTTP_403_FORBIDDEN)

        class_ids = request.data.getlist("classIds") if hasattr(request.data, "getlist") else []
        if not class_ids and request.data.get("classId"):
            class_ids = [request.data.get("classId")]

        fields = self._homework_defaults(request)
        if not fields["title"] or not fields["description"] or not fields["due_date"]:
            return Response({"detail": "يرجى تعبئة العنوان والتعليمات وموعد الانتهاء"}, status=status.HTTP_400_BAD_REQUEST)

        if class_ids:
            batch_group_id = uuid.uuid4()
            uploaded = collect_uploaded_files(request)
            file_items = _file_bytes_list(uploaded)
            created = []
            for class_id in class_ids:
                hw = Homework.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    **fields,
                )
                if file_items:
                    add_attachments_to_homework(hw, file_items)
                created.append(hw)
            return Response(
                HomeworkSerializer(created, many=True, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()
        apply_group = str(data.get("applyToGroup", "false")).lower() in ("1", "true", "yes")
        targets = (
            Homework.objects.filter(group_id=instance.group_id)
            if apply_group and instance.group_id
            else Homework.objects.filter(id=instance.id)
        )

        patch_fields = {}
        for key, attr in [
            ("subject", "subject"),
            ("title", "title"),
            ("description", "description"),
            ("dueDate", "due_date"),
            ("status", "status"),
        ]:
            if key in data:
                patch_fields[attr] = data[key]

        from django.utils.dateparse import parse_datetime

        if "startAt" in data:
            patch_fields["start_at"] = parse_datetime(str(data["startAt"])) if data["startAt"] else None
        if "endAt" in data:
            patch_fields["end_at"] = parse_datetime(str(data["endAt"])) if data["endAt"] else None
        if "gradesVisible" in data:
            patch_fields["grades_visible"] = str(data["gradesVisible"]).lower() in ("1", "true", "yes")
        if "maxScore" in data:
            try:
                max_score = Decimal(str(data.get("maxScore", "100")))
            except Exception:
                max_score = Decimal("100")
            if max_score > 0:
                patch_fields["max_score"] = max_score

        attachment = request.FILES.get("attachment")
        uploaded = collect_uploaded_files(request)
        file_items = _file_bytes_list(uploaded)
        remove_ids = request.data.getlist("removeAttachmentIds") if hasattr(request.data, "getlist") else []
        class_ids = request.data.getlist("classIds") if hasattr(request.data, "getlist") else []
        sync_classes = str(data.get("syncClasses", "false")).lower() in ("1", "true", "yes")

        if remove_ids:
            remove_attachments(instance, remove_ids, apply_to_group=apply_group)

        if sync_classes and class_ids and instance.group_id:
            try:
                self._sync_group_targets(instance, class_ids, patch_fields, file_items)
                if "max_score" in patch_fields:
                    HomeworkSubmission.objects.filter(homework__group_id=instance.group_id).update(
                        max_score=patch_fields["max_score"]
                    )
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            for hw in targets:
                for attr, value in patch_fields.items():
                    setattr(hw, attr, value)
                hw.save()
                if file_items:
                    start = hw.attachment_files.count()
                    add_attachments_to_homework(hw, file_items, start_order=start)
                elif attachment:
                    hw.attachment = attachment
                    hw.save(update_fields=["attachment"])
            if "max_score" in patch_fields:
                HomeworkSubmission.objects.filter(homework__in=targets).update(
                    max_score=patch_fields["max_score"]
                )

        instance.refresh_from_db()
        return Response(HomeworkSerializer(instance, context={"request": request}).data)

    def _sync_group_targets(self, instance, class_ids, patch_fields, file_items):
        group_id = instance.group_id
        teacher = instance.teacher
        existing_qs = Homework.objects.filter(group_id=group_id).select_related("school_class").prefetch_related(
            "attachment_files"
        )
        existing_map = {str(hw.school_class_id): hw for hw in existing_qs}
        desired = {str(class_id) for class_id in class_ids}

        for class_id, hw in list(existing_map.items()):
            if class_id not in desired:
                if hw.submissions.exists():
                    raise ValueError(f"لا يمكن إزالة شعبة {hw.school_class.name} لوجود تسليمات")
                hw.delete()

        base_fields = {
            "subject": patch_fields.get("subject", instance.subject),
            "title": patch_fields.get("title", instance.title),
            "description": patch_fields.get("description", instance.description),
            "due_date": patch_fields.get("due_date", instance.due_date),
            "start_at": patch_fields.get("start_at", instance.start_at),
            "end_at": patch_fields.get("end_at", instance.end_at),
            "grades_visible": patch_fields.get("grades_visible", instance.grades_visible),
            "max_score": patch_fields.get("max_score", instance.max_score),
            "status": patch_fields.get("status", instance.status),
        }

        for class_id in desired:
            if class_id in existing_map:
                hw = existing_map[class_id]
                for attr, value in {**base_fields, **patch_fields}.items():
                    setattr(hw, attr, value)
                hw.save()
                if file_items:
                    start = hw.attachment_files.count()
                    add_attachments_to_homework(hw, file_items, start_order=start)
            else:
                hw = Homework.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=group_id,
                    **base_fields,
                )
                copy_attachments_from_homework(instance, hw)
                if file_items:
                    start = hw.attachment_files.count()
                    add_attachments_to_homework(hw, file_items, start_order=start)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.query_params.get("group") == "true" and instance.group_id:
            Homework.objects.filter(group_id=instance.group_id).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"], url_path="submissions")
    def submissions(self, request, pk=None):
        homework = self.get_object()
        rows = homework.submissions.select_related("student", "homework").order_by("-submitted_at")
        return Response(
            HomeworkSubmissionSerializer(
                rows,
                many=True,
                context={"request": request, "hide_grades_from_student": False},
            ).data
        )

    @action(detail=True, methods=["patch"], url_path=r"submissions/(?P<submission_id>[^/.]+)/grade")
    def grade_submission(self, request, pk=None, submission_id=None):
        homework = self.get_object()
        submission = HomeworkSubmission.objects.filter(id=submission_id, homework=homework).first()
        if not submission:
            return Response({"detail": "التسليم غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        if "score" in request.data:
            score_raw = request.data.get("score")
            submission.score = None if score_raw in (None, "") else Decimal(str(score_raw))
            if submission.score is not None and submission.score > homework.max_score:
                return Response(
                    {"detail": f"العلامة لا يمكن أن تتجاوز {homework.max_score}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            submission.graded_at = timezone.now() if submission.score is not None else None
        if "teacherNote" in request.data:
            submission.teacher_note = str(request.data.get("teacherNote", "")).strip()
        submission.max_score = homework.max_score

        if submission.score is not None:
            _publish_homework_grades(homework)

        submission.save()
        return Response(
            HomeworkSubmissionSerializer(
                submission,
                context={"request": request, "hide_grades_from_student": False},
            ).data
        )


class TeacherAssessmentsView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])

        homework = (
            Homework.objects.filter(teacher=teacher)
            .select_related("school_class", "teacher")
            .prefetch_related("submissions__student")
            .order_by("-created_at")
        )
        grouped: dict[str, list] = {}
        for hw in homework:
            key = str(hw.group_id)
            grouped.setdefault(key, []).append(hw)

        data = []
        for rows in grouped.values():
            primary = rows[0]
            subs = []
            targets = []
            for hw in rows:
                targets.append(
                    {
                        "id": str(hw.id),
                        "classId": str(hw.school_class_id),
                        "className": hw.school_class.name,
                        "submissionCount": hw.submissions.count(),
                    }
                )
                subs.extend(list(hw.submissions.all()))
            data.append(
                {
                    "groupId": str(primary.group_id),
                    "homework": HomeworkSerializer(primary, context={"request": request}).data,
                    "targets": targets,
                    "submissions": HomeworkSubmissionSerializer(
                        subs,
                        many=True,
                        context={"request": request, "hide_grades_from_student": False},
                    ).data,
                }
            )
        data.sort(key=lambda row: row["homework"].get("createdAt", ""), reverse=True)
        return Response(data)


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
            pick_representative_scheme,
            serialize_entries_for_classes,
            serialize_grade_scheme,
            teacher_subjects_for_classes,
        )
        from academics.academic_services import ensure_default_academic_calendar, serialize_academic_context

        ensure_default_academic_calendar()
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

        schemes = []
        if subject:
            academic_term = require_current_academic_term()
            for school_class in school_classes:
                scheme = (
                    SubjectGradeScheme.objects.filter(
                        teacher=teacher,
                        school_class=school_class,
                        subject=subject,
                        academic_term=academic_term,
                    )
                    .select_related("school_class")
                    .first()
                )
                schemes.append(scheme)

        representative = pick_representative_scheme(schemes)
        return Response(
            {
                "availableSubjects": available_subjects,
                "scheme": serialize_grade_scheme(representative) if representative else None,
                "entries": serialize_entries_for_classes(teacher, school_classes, subject),
                "classIds": [str(school_class.id) for school_class in school_classes],
                "subjects": [subject] if subject else [],
                "academicContext": serialize_academic_context(),
            }
        )

    def put(self, request):
        from academics.academic_services import serialize_academic_context
        from academics.grade_scheme_services import (
            normalize_components,
            serialize_entries_for_classes,
            serialize_grade_scheme,
            upsert_grade_schemes_for_subjects,
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
        components = normalize_components(request.data.get("components") or [])
        max_score = request.data.get("maxScore", 100)

        try:
            schemes = upsert_grade_schemes_for_subjects(
                teacher, school_classes, subjects, max_score, components
            )
        except serializers.ValidationError as exc:
            raise DRFValidationError(exc.detail)

        primary = schemes[0]
        primary = SubjectGradeScheme.objects.select_related("school_class").get(pk=primary.pk)
        active_subject = subjects[0]
        return Response(
            {
                "scheme": serialize_grade_scheme(primary),
                "entries": serialize_entries_for_classes(teacher, school_classes, active_subject),
                "classIds": [str(school_class.id) for school_class in school_classes],
                "subjects": subjects,
                "academicContext": serialize_academic_context(),
            }
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


class TeacherAlertsView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        from assignments.quiz_services import (
            quiz_has_manual_questions,
            quiz_submission_fully_graded,
        )

        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])

        read_keys = set(
            TeacherReadAlert.objects.filter(teacher=request.user).values_list("alert_key", flat=True)
        )

        alerts = []

        hw_subs = (
            HomeworkSubmission.objects.filter(homework__teacher=teacher)
            .select_related("student", "homework", "homework__school_class")
            .order_by("-submitted_at")[:40]
        )
        for sub in hw_subs:
            graded = sub.score is not None
            alert_key = f"homework_submission-{sub.id}"
            alerts.append(
                {
                    "id": str(sub.id),
                    "submissionId": str(sub.id),
                    "type": "homework_submission",
                    "text": f"سلّم {sub.student.name} واجب «{sub.homework.title}» — {sub.homework.school_class.name}",
                    "homeworkId": str(sub.homework_id),
                    "groupId": str(sub.homework.group_id),
                    "homeworkTitle": sub.homework.title,
                    "studentName": sub.student.name,
                    "className": sub.homework.school_class.name,
                    "submittedAt": sub.submitted_at.isoformat(),
                    "graded": graded,
                    "needsGrading": not graded,
                    "opened": alert_key in read_keys,
                }
            )

        qz_subs = (
            QuizSubmission.objects.filter(quiz__teacher=teacher)
            .select_related("student", "quiz", "quiz__school_class")
            .prefetch_related("quiz__questions")
            .order_by("-submitted_at")[:40]
        )
        for sub in qz_subs:
            questions = list(sub.quiz.questions.all())
            has_manual = quiz_has_manual_questions(questions)
            fully_graded = quiz_submission_fully_graded(sub, questions)
            needs_grading = has_manual and not fully_graded
            alert_key = f"quiz_submission-{sub.id}"
            alerts.append(
                {
                    "id": str(sub.id),
                    "submissionId": str(sub.id),
                    "type": "quiz_submission",
                    "text": f"قدّم {sub.student.name} اختبار «{sub.quiz.title}» — {sub.quiz.school_class.name}",
                    "quizId": str(sub.quiz_id),
                    "groupId": str(sub.quiz.group_id),
                    "quizTitle": sub.quiz.title,
                    "studentName": sub.student.name,
                    "className": sub.quiz.school_class.name,
                    "submittedAt": sub.submitted_at.isoformat(),
                    "graded": fully_graded,
                    "needsGrading": needs_grading,
                    "opened": alert_key in read_keys,
                }
            )

        alerts.sort(key=lambda row: row["submittedAt"], reverse=True)
        return Response(alerts[:40])


class TeacherAlertReadView(APIView):
    permission_classes = [IsTeacher]

    def post(self, request):
        alert_key = str(request.data.get("alertKey", "")).strip()
        if not alert_key:
            return Response({"detail": "معرّف الإشعار مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        TeacherReadAlert.objects.get_or_create(teacher=request.user, alert_key=alert_key)
        return Response({"ok": True})


class TeacherQuizViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]
    serializer_class = QuizSerializer

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return Quiz.objects.none()
        qs = (
            Quiz.objects.filter(teacher=teacher)
            .select_related("school_class", "teacher")
            .prefetch_related("questions")
        )
        class_id = self.request.query_params.get("classId")
        if class_id:
            qs = qs.filter(school_class_id=class_id)
        return qs.order_by("-created_at")

    def _quiz_defaults(self, request):
        from django.utils.dateparse import parse_datetime

        data = request.data
        start_at = parse_datetime(str(data.get("startAt", ""))) if data.get("startAt") else None
        end_at = parse_datetime(str(data.get("endAt", ""))) if data.get("endAt") else None
        due_raw = data.get("dueDate")
        if not due_raw and start_at:
            due_raw = start_at.date().isoformat()
        grades_visible = str(data.get("gradesVisible", "false")).lower() in ("1", "true", "yes")
        review_allowed = str(data.get("reviewAllowed", "false")).lower() in ("1", "true", "yes")
        max_score_raw = data.get("maxScore", "0")
        try:
            max_score = Decimal(str(max_score_raw))
        except Exception:
            max_score = Decimal("0")
        if max_score < 0:
            max_score = Decimal("0")
        try:
            duration = int(data.get("durationMinutes", data.get("duration_minutes", 30)) or 30)
        except (TypeError, ValueError):
            duration = 30
        if duration <= 0:
            duration = 30
        try:
            max_attempts = int(data.get("maxAttempts", data.get("max_attempts", 1)) or 1)
        except (TypeError, ValueError):
            max_attempts = 1
        if max_attempts < 1:
            max_attempts = 1
        if max_attempts > 20:
            max_attempts = 20
        return {
            "subject": str(data.get("subject", "")).strip(),
            "title": str(data.get("title", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "due_date": due_raw,
            "start_at": start_at,
            "end_at": end_at,
            "duration_minutes": duration,
            "max_attempts": max_attempts,
            "grades_visible": grades_visible,
            "review_allowed": review_allowed,
            "max_score": max_score,
            "status": data.get("status", "active"),
        }

    def _parse_questions(self, request):
        import json

        raw = request.data.get("questions")
        if raw is None:
            return None
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    def _question_kwargs(self, q, order):
        correct_index = q.get("correctIndex", q.get("correct_index"))
        if correct_index in ("", None):
            correct_index = None
        else:
            correct_index = int(correct_index)
        try:
            points = Decimal(str(q.get("points", 1)))
        except Exception:
            points = Decimal("1")
        if points <= 0:
            points = Decimal("1")
        return {
            "prompt": str(q.get("prompt", "")).strip(),
            "question_type": q.get("questionType", q.get("question_type", "choice")),
            "options": q.get("options", []),
            "correct_index": correct_index,
            "correct_text": str(q.get("correctText", q.get("correct_text", ""))).strip(),
            "pairs": q.get("pairs", []),
            "points": points,
            "order": order,
        }

    def _save_questions(self, quiz, questions_data):
        quiz.questions.all().delete()
        for i, q in enumerate(questions_data):
            QuizQuestion.objects.create(quiz=quiz, **self._question_kwargs(q, i))
        from assignments.quiz_services import quiz_max_score

        quiz.max_score = quiz_max_score(quiz.questions.all())
        quiz.save(update_fields=["max_score"])

    def _copy_questions(self, source_quiz, target_quiz):
        for q in source_quiz.questions.all():
            QuizQuestion.objects.create(
                quiz=target_quiz,
                prompt=q.prompt,
                question_type=q.question_type,
                options=q.options,
                correct_index=q.correct_index,
                correct_text=q.correct_text,
                pairs=q.pairs,
                points=q.points,
                order=q.order,
            )

    def perform_create(self, serializer):
        teacher = _teacher_for_user(self.request.user)
        serializer.save(teacher=teacher)

    def create(self, request, *args, **kwargs):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "لم يتم ربط حسابك بملف معلم"}, status=status.HTTP_403_FORBIDDEN)

        class_ids = _parse_class_ids(request.data)

        fields = self._quiz_defaults(request)
        questions_data = self._parse_questions(request) or []
        if not fields["title"] or not fields["due_date"] or not fields["start_at"]:
            return Response(
                {"detail": "يرجى تعبئة العنوان وموعد البدء وموعد الانتهاء"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if class_ids:
            batch_group_id = uuid.uuid4()
            created = []
            for class_id in class_ids:
                quiz = Quiz.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    **fields,
                )
                self._save_questions(quiz, questions_data)
                created.append(quiz)
            return Response(
                QuizSerializer(created, many=True, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()
        apply_group = str(data.get("applyToGroup", "false")).lower() in ("1", "true", "yes")
        targets = (
            Quiz.objects.filter(group_id=instance.group_id)
            if apply_group and instance.group_id
            else Quiz.objects.filter(id=instance.id)
        )

        patch_fields = {}
        for key, attr in [
            ("subject", "subject"),
            ("title", "title"),
            ("description", "description"),
            ("dueDate", "due_date"),
            ("status", "status"),
        ]:
            if key in data:
                patch_fields[attr] = data[key]

        from django.utils.dateparse import parse_datetime

        if "startAt" in data:
            patch_fields["start_at"] = parse_datetime(str(data["startAt"])) if data["startAt"] else None
        if "endAt" in data:
            patch_fields["end_at"] = parse_datetime(str(data["endAt"])) if data["endAt"] else None
        if "gradesVisible" in data:
            patch_fields["grades_visible"] = str(data["gradesVisible"]).lower() in ("1", "true", "yes")
        if "reviewAllowed" in data:
            patch_fields["review_allowed"] = str(data["reviewAllowed"]).lower() in ("1", "true", "yes")
        if "durationMinutes" in data:
            try:
                duration = int(data.get("durationMinutes") or 30)
            except (TypeError, ValueError):
                duration = 30
            if duration > 0:
                patch_fields["duration_minutes"] = duration
        if "maxAttempts" in data:
            try:
                max_attempts = int(data.get("maxAttempts") or 1)
            except (TypeError, ValueError):
                max_attempts = 1
            if max_attempts < 1:
                max_attempts = 1
            if max_attempts > 20:
                max_attempts = 20
            patch_fields["max_attempts"] = max_attempts
        if "maxScore" in data:
            try:
                max_score = Decimal(str(data.get("maxScore", "0")))
            except Exception:
                max_score = Decimal("0")
            if max_score >= 0:
                patch_fields["max_score"] = max_score

        questions_data = self._parse_questions(request)
        class_ids = _parse_class_ids(request.data)
        sync_classes = str(data.get("syncClasses", "false")).lower() in ("1", "true", "yes")

        if sync_classes and class_ids and instance.group_id:
            try:
                self._sync_group_targets(instance, class_ids, patch_fields, questions_data)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            for quiz in targets:
                for attr, value in patch_fields.items():
                    setattr(quiz, attr, value)
                quiz.save()
                if questions_data is not None:
                    self._save_questions(quiz, questions_data)

        instance.refresh_from_db()
        return Response(QuizSerializer(instance, context={"request": request}).data)

    def _sync_group_targets(self, instance, class_ids, patch_fields, questions_data):
        group_id = instance.group_id
        teacher = instance.teacher
        existing_qs = Quiz.objects.filter(group_id=group_id).select_related("school_class").prefetch_related(
            "questions"
        )
        existing_map = {str(quiz.school_class_id): quiz for quiz in existing_qs}
        desired = {str(class_id) for class_id in class_ids}

        for class_id, quiz in list(existing_map.items()):
            if class_id not in desired:
                if quiz.submissions.exists():
                    raise ValueError(f"لا يمكن إزالة شعبة {quiz.school_class.name} لوجود تسليمات")
                quiz.delete()

        base_fields = {
            "subject": patch_fields.get("subject", instance.subject),
            "title": patch_fields.get("title", instance.title),
            "description": patch_fields.get("description", instance.description),
            "due_date": patch_fields.get("due_date", instance.due_date),
            "start_at": patch_fields.get("start_at", instance.start_at),
            "end_at": patch_fields.get("end_at", instance.end_at),
            "duration_minutes": patch_fields.get("duration_minutes", instance.duration_minutes),
            "grades_visible": patch_fields.get("grades_visible", instance.grades_visible),
            "review_allowed": patch_fields.get("review_allowed", instance.review_allowed),
            "max_score": patch_fields.get("max_score", instance.max_score),
            "status": patch_fields.get("status", instance.status),
        }

        for class_id in desired:
            if class_id in existing_map:
                quiz = existing_map[class_id]
                for attr, value in {**base_fields, **patch_fields}.items():
                    setattr(quiz, attr, value)
                quiz.save()
                if questions_data is not None:
                    self._save_questions(quiz, questions_data)
            else:
                quiz = Quiz.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=group_id,
                    **base_fields,
                )
                if questions_data is not None:
                    self._save_questions(quiz, questions_data)
                else:
                    self._copy_questions(instance, quiz)

    @action(detail=True, methods=["get"], url_path="grading-bundle")
    def grading_bundle(self, request, pk=None):
        instance = self.get_object()
        if instance.group_id:
            targets_qs = (
                Quiz.objects.filter(group_id=instance.group_id)
                .select_related("school_class", "teacher")
                .prefetch_related(
                    "questions",
                    "submissions__student",
                    "submissions__quiz__questions",
                    "submissions__answer_attachments",
                )
                .order_by("school_class__name")
            )
        else:
            targets_qs = (
                Quiz.objects.filter(id=instance.id)
                .select_related("school_class", "teacher")
                .prefetch_related(
                    "questions",
                    "submissions__student",
                    "submissions__quiz__questions",
                    "submissions__answer_attachments",
                )
            )

        targets = []
        submissions = []
        for quiz in targets_qs:
            targets.append(
                {
                    "id": str(quiz.id),
                    "classId": str(quiz.school_class_id),
                    "className": quiz.school_class.name,
                    "submissionCount": quiz.submissions.values("student_id").distinct().count(),
                }
            )
            submissions.extend(list(quiz.submissions.all()))

        from assignments.quiz_services import best_quiz_submission_ids

        best_ids = best_quiz_submission_ids(submissions)
        primary = targets_qs.first() or instance
        return Response(
            {
                "groupId": str(primary.group_id or primary.id),
                "overviewQuizId": str(primary.id),
                "quiz": QuizSerializer(instance, context={"request": request}).data,
                "targets": targets,
                "submissions": QuizSubmissionSerializer(
                    submissions,
                    many=True,
                    context={
                        "request": request,
                        "hide_grades_from_student": False,
                        "best_submission_ids": best_ids,
                    },
                ).data,
            }
        )

    @action(detail=True, methods=["patch"], url_path=r"submissions/(?P<submission_id>[^/.]+)/grade")
    def grade_submission(self, request, pk=None, submission_id=None):
        from assignments.models import QuestionType
        from assignments.quiz_services import (
            MANUAL_QUESTION_TYPES,
            quiz_max_score,
            quiz_submission_fully_graded,
            recalculate_quiz_submission_score,
        )

        quiz = self.get_object()
        submission = (
            QuizSubmission.objects.filter(id=submission_id, quiz=quiz)
            .select_related("student", "quiz")
            .prefetch_related("quiz__questions")
            .first()
        )
        if not submission:
            return Response({"detail": "التسليم غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        questions = list(quiz.questions.all())
        manual_questions = [
            q for q in questions if (q.question_type or QuestionType.CHOICE) in MANUAL_QUESTION_TYPES
        ]
        manual_scores = dict(submission.manual_scores or {})

        if "manualScores" in request.data:
            incoming = request.data.get("manualScores") or {}
            updated_manual: dict[str, float] = {}
            for question in manual_questions:
                qid = str(question.id)
                raw = incoming.get(qid)
                if raw is None:
                    raw = incoming.get(question.id)
                if raw in (None, ""):
                    continue
                try:
                    points = Decimal(str(raw))
                except Exception:
                    return Response({"detail": "درجة غير صالحة"}, status=status.HTTP_400_BAD_REQUEST)
                max_points = Decimal(str(question.points or 1))
                if points < 0 or points > max_points:
                    return Response(
                        {"detail": f"درجة السؤال يجب أن تكون بين 0 و {max_points}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                updated_manual[qid] = float(points)
            manual_scores = updated_manual

        submission.manual_scores = manual_scores
        if "teacherNote" in request.data:
            submission.teacher_note = str(request.data.get("teacherNote", "")).strip()

        submission.score = recalculate_quiz_submission_score(submission, questions)
        submission.max_score = quiz.max_score or quiz_max_score(questions)
        submission.graded_at = (
            timezone.now() if quiz_submission_fully_graded(submission, questions) else None
        )
        if submission.graded_at is not None:
            _publish_quiz_grades(quiz)
        submission.save()

        submission.refresh_from_db()
        quiz.refresh_from_db()

        return Response(
            QuizSubmissionSerializer(
                submission,
                context={"request": request, "hide_grades_from_student": False},
            ).data
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.query_params.get("group") == "true" and instance.group_id:
            Quiz.objects.filter(group_id=instance.group_id).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)


class TeacherAnnouncementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]
    serializer_class = SubjectAnnouncementSerializer

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return SubjectAnnouncement.objects.none()
        qs = SubjectAnnouncement.objects.filter(teacher=teacher).select_related(
            "school_class", "teacher"
        )
        class_id = self.request.query_params.get("classId")
        if class_id:
            qs = qs.filter(school_class_id=class_id)
        return qs.order_by("-created_at")

    def _announcement_defaults(self, request):
        data = request.data
        return {
            "subject": str(data.get("subject", "")).strip(),
            "title": str(data.get("title", "")).strip(),
            "body": str(data.get("body", "")).strip(),
        }

    def create(self, request, *args, **kwargs):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "لم يتم ربط حسابك بملف معلم"}, status=status.HTTP_403_FORBIDDEN)

        class_ids = _parse_class_ids(request.data)
        fields = self._announcement_defaults(request)
        if not fields["title"] or not fields["body"]:
            return Response(
                {"detail": "يرجى تعبئة عنوان الإعلان والنص"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if class_ids:
            batch_group_id = uuid.uuid4()
            created = []
            for class_id in class_ids:
                item = SubjectAnnouncement.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    **fields,
                )
                created.append(item)
            return Response(
                SubjectAnnouncementSerializer(created, many=True, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(teacher=teacher)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()
        apply_group = str(data.get("applyToGroup", "false")).lower() in ("1", "true", "yes")
        targets = (
            SubjectAnnouncement.objects.filter(group_id=instance.group_id)
            if apply_group and instance.group_id
            else SubjectAnnouncement.objects.filter(id=instance.id)
        )

        patch_fields = {}
        for key, attr in [("subject", "subject"), ("title", "title"), ("body", "body")]:
            if key in data:
                patch_fields[attr] = str(data[key]).strip()

        class_ids = _parse_class_ids(request.data)
        sync_classes = str(data.get("syncClasses", "false")).lower() in ("1", "true", "yes")

        if sync_classes and class_ids and instance.group_id:
            try:
                self._sync_group_targets(instance, class_ids, patch_fields)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            for item in targets:
                for attr, value in patch_fields.items():
                    setattr(item, attr, value)
                item.save()

        instance.refresh_from_db()
        return Response(SubjectAnnouncementSerializer(instance, context={"request": request}).data)

    def _sync_group_targets(self, instance, class_ids, patch_fields):
        group_id = instance.group_id
        teacher = instance.teacher
        existing_qs = SubjectAnnouncement.objects.filter(group_id=group_id).select_related("school_class")
        existing_map = {str(row.school_class_id): row for row in existing_qs}
        desired = {str(class_id) for class_id in class_ids}

        for class_id, row in list(existing_map.items()):
            if class_id not in desired:
                row.delete()

        base_fields = {
            "subject": patch_fields.get("subject", instance.subject),
            "title": patch_fields.get("title", instance.title),
            "body": patch_fields.get("body", instance.body),
        }

        for class_id in desired:
            if class_id in existing_map:
                row = existing_map[class_id]
                for attr, value in {**base_fields, **patch_fields}.items():
                    setattr(row, attr, value)
                row.save()
            else:
                SubjectAnnouncement.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=group_id,
                    **base_fields,
                )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.query_params.get("group") == "true" and instance.group_id:
            SubjectAnnouncement.objects.filter(group_id=instance.group_id).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)


class TeacherMaterialViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]
    serializer_class = SubjectMaterialSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return SubjectMaterial.objects.none()
        qs = SubjectMaterial.objects.filter(teacher=teacher).select_related(
            "school_class", "teacher"
        ).prefetch_related("files")
        class_id = self.request.query_params.get("classId")
        if class_id:
            qs = qs.filter(school_class_id=class_id)
        return qs.order_by("-created_at")

    def _material_defaults(self, request):
        data = request.data
        category = str(data.get("category", "resources")).strip() or "resources"
        valid = {"book", "slides", "resources", "other"}
        if category not in valid:
            category = "resources"
        return {
            "subject": str(data.get("subject", "")).strip(),
            "title": str(data.get("title", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "category": category,
        }

    def create(self, request, *args, **kwargs):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response({"detail": "لم يتم ربط حسابك بملف معلم"}, status=status.HTTP_403_FORBIDDEN)

        class_ids = _parse_class_ids(request.data)
        fields = self._material_defaults(request)
        if not fields["title"]:
            return Response({"detail": "يرجى تعبئة عنوان المرفق"}, status=status.HTTP_400_BAD_REQUEST)

        uploaded = collect_uploaded_files(request)
        file_items = _file_bytes_list(uploaded)
        if not file_items:
            return Response({"detail": "يرجى إرفاق ملف واحد على الأقل"}, status=status.HTTP_400_BAD_REQUEST)

        if class_ids:
            batch_group_id = uuid.uuid4()
            created = []
            for class_id in class_ids:
                item = SubjectMaterial.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    **fields,
                )
                add_attachments_to_material(item, file_items)
                created.append(item)
            return Response(
                SubjectMaterialSerializer(created, many=True, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        material = serializer.save(teacher=teacher)
        add_attachments_to_material(material, file_items)
        return Response(
            SubjectMaterialSerializer(material, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()
        apply_group = str(data.get("applyToGroup", "false")).lower() in ("1", "true", "yes")
        targets = (
            SubjectMaterial.objects.filter(group_id=instance.group_id)
            if apply_group and instance.group_id
            else SubjectMaterial.objects.filter(id=instance.id)
        )

        patch_fields = {}
        for key, attr in [
            ("subject", "subject"),
            ("title", "title"),
            ("description", "description"),
            ("category", "category"),
        ]:
            if key in data:
                if key == "category":
                    category = str(data[key]).strip() or "resources"
                    if category not in {"book", "slides", "resources", "other"}:
                        category = "resources"
                    patch_fields[attr] = category
                else:
                    patch_fields[attr] = str(data[key]).strip()

        uploaded = collect_uploaded_files(request)
        file_items = _file_bytes_list(uploaded)
        remove_ids = request.data.getlist("removeAttachmentIds") if hasattr(request.data, "getlist") else []
        class_ids = _parse_class_ids(request.data)
        sync_classes = str(data.get("syncClasses", "false")).lower() in ("1", "true", "yes")

        if remove_ids:
            remove_material_attachments(instance, remove_ids, apply_to_group=apply_group)

        if sync_classes and class_ids and instance.group_id:
            try:
                self._sync_group_targets(instance, class_ids, patch_fields, file_items)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            for item in targets:
                for attr, value in patch_fields.items():
                    setattr(item, attr, value)
                item.save()
                if file_items:
                    start = item.files.count()
                    add_attachments_to_material(item, file_items, start_order=start)

        instance.refresh_from_db()
        return Response(SubjectMaterialSerializer(instance, context={"request": request}).data)

    def _sync_group_targets(self, instance, class_ids, patch_fields, file_items):
        group_id = instance.group_id
        teacher = instance.teacher
        existing_qs = SubjectMaterial.objects.filter(group_id=group_id).select_related(
            "school_class"
        ).prefetch_related("files")
        existing_map = {str(row.school_class_id): row for row in existing_qs}
        desired = {str(class_id) for class_id in class_ids}

        for class_id, row in list(existing_map.items()):
            if class_id not in desired:
                row.delete()

        base_fields = {
            "subject": patch_fields.get("subject", instance.subject),
            "title": patch_fields.get("title", instance.title),
            "description": patch_fields.get("description", instance.description),
            "category": patch_fields.get("category", instance.category),
        }

        for class_id in desired:
            if class_id in existing_map:
                row = existing_map[class_id]
                for attr, value in {**base_fields, **patch_fields}.items():
                    setattr(row, attr, value)
                row.save()
                if file_items:
                    start = row.files.count()
                    add_attachments_to_material(row, file_items, start_order=start)
            else:
                created = SubjectMaterial.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=group_id,
                    **base_fields,
                )
                copy_attachments_from_material(instance, created)
                if file_items:
                    start = created.files.count()
                    add_attachments_to_material(created, file_items, start_order=start)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if request.query_params.get("group") == "true" and instance.group_id:
            SubjectMaterial.objects.filter(group_id=instance.group_id).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)


class ParentAlertsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response([])

        dismissed_ids = set(
            ParentDismissedAlert.objects.filter(parent=request.user).values_list("alert_id", flat=True)
        )

        alerts = []
        fee_status = build_fee_status(child)
        for notice in fee_status.get("notifications", []):
            alerts.append({
                "id": notice["id"],
                "text": notice["text"],
                "type": "installment",
                "order": notice.get("order"),
                "amount": notice.get("amount"),
                "remaining": notice.get("remaining"),
                "startDate": notice.get("startDate"),
                "endDate": notice.get("endDate"),
                "status": notice.get("status"),
            })

        latest_payment = PaymentNotice.objects.filter(student=child, status="approved").order_by("-date").first()
        if latest_payment and not fee_status.get("notifications"):
            alerts.append({
                "id": "a1",
                "text": f"آخر دفعة معتمدة: {int(latest_payment.amount)} ₪ — {latest_payment.date}",
                "type": "payment",
            })

        math_grade = SubjectGrade.objects.filter(student=child, subject="الرياضيات").first()
        if math_grade and math_grade.note:
            alerts.append({
                "id": "a2",
                "text": f"ملاحظة من معلم الرياضيات: {math_grade.note}",
                "type": "note",
            })

        physics_grade = SubjectGrade.objects.filter(student=child, subject="الفيزياء").first()
        if physics_grade:
            alerts.append({
                "id": "a3",
                "text": f"تمت إضافة علامة الفيزياء: {int(physics_grade.score)}/{int(physics_grade.max_score)}",
                "type": "grade",
            })

        pending_hw = (
            Homework.objects.filter(school_class=child.school_class)
            .exclude(id__in=HomeworkSubmission.objects.filter(student=child).values_list("homework_id", flat=True))
            .select_related("teacher", "school_class")
            .order_by("-created_at")
        )
        for hw in pending_hw:
            if not homework_is_open(hw):
                continue
            subject = _subject_label(hw.subject)
            alerts.append({
                "id": f"hw-{hw.id}",
                "text": f"واجب جديد — {hw.title} ({subject})",
                "type": "homework",
                "homeworkId": str(hw.id),
                "subject": subject,
            })

        from assignments.quiz_services import quiz_is_open

        open_quizzes = Quiz.objects.filter(school_class=child.school_class).order_by("-created_at")
        for quiz in open_quizzes:
            if not quiz_is_open(quiz):
                continue
            from assignments.quiz_services import can_take_quiz_attempt

            if not can_take_quiz_attempt(quiz, child):
                continue
            subject = _subject_label(quiz.subject)
            alerts.append({
                "id": f"quiz-{quiz.id}",
                "text": f"اختبار متاح — {quiz.title} ({subject})",
                "type": "quiz",
                "quizId": str(quiz.id),
                "subject": subject,
            })

        recent_cutoff = timezone.now() - timedelta(days=30)
        announcements = (
            SubjectAnnouncement.objects.filter(
                school_class=child.school_class,
                created_at__gte=recent_cutoff,
            )
            .select_related("teacher")
            .order_by("-created_at")[:20]
        )
        for ann in announcements:
            subject = _subject_label(ann.subject)
            alerts.append({
                "id": f"ann-{ann.id}",
                "text": f"إعلان — {ann.title} ({subject})",
                "type": "announcement",
                "announcementId": str(ann.id),
                "subject": subject,
            })

        materials = (
            SubjectMaterial.objects.filter(
                school_class=child.school_class,
                created_at__gte=recent_cutoff,
            )
            .select_related("teacher")
            .order_by("-created_at")[:20]
        )
        for mat in materials:
            subject = _subject_label(mat.subject)
            alerts.append({
                "id": f"mat-{mat.id}",
                "text": f"مرفق جديد — {mat.title} ({subject})",
                "type": "material",
                "materialId": str(mat.id),
                "subject": subject,
            })

        alerts = [
            row
            for row in alerts
            if row["type"] not in ("announcement", "material") or row["id"] not in dismissed_ids
        ]
        return Response(alerts)


class ParentAlertDismissView(APIView):
    permission_classes = [IsParent]

    def post(self, request):
        alert_id = str(request.data.get("alertId", "")).strip()
        if not alert_id:
            return Response({"detail": "معرّف الإشعار مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        if not (alert_id.startswith("ann-") or alert_id.startswith("mat-")):
            return Response(
                {"detail": "يمكن إخفاء الإعلانات والمرفقات فقط"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ParentDismissedAlert.objects.get_or_create(parent=request.user, alert_id=alert_id)
        return Response({"ok": True})


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

        fee_status = restore_student_access_after_fees(linked)
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
        from academics.academic_services import ensure_default_academic_calendar

        child = _child_for_parent(request.user)
        if not child:
            return Response([])
        ensure_default_academic_calendar()
        mark_parent_grades_seen(request.user, child)
        return Response(serialize_parent_subject_grades(child))


class ParentGradesNotificationView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.grade_scheme_services import get_parent_grades_notification
        from academics.academic_services import ensure_default_academic_calendar

        child = _child_for_parent(request.user)
        if not child:
            return Response({"hasNew": False, "count": 0})
        ensure_default_academic_calendar()
        return Response(get_parent_grades_notification(child, request.user))


class ParentCertificatesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        from academics.academic_services import ensure_default_academic_calendar
        from academics.certificate_services import active_certificate_config, serialize_parent_certificates

        child = _child_for_parent(request.user)
        if not child:
            return Response({"published": False, "message": "لا يوجد طالب مرتبط", "certificate": None})
        ensure_default_academic_calendar()
        config = active_certificate_config()
        return Response(serialize_parent_certificates(child, config))


class ParentAssessmentsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response([])

        items = []

        hw_subs = (
            HomeworkSubmission.objects.filter(
                student=child,
                homework__grades_visible=True,
                score__isnull=False,
            )
            .select_related("homework")
            .order_by("-graded_at", "-submitted_at")
        )
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

        quiz_subs = (
            QuizSubmission.objects.filter(student=child, quiz__grades_visible=True)
            .select_related("quiz")
            .prefetch_related("quiz__questions")
            .order_by("-score", "-attempt_number")
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
            "feeStatus": restore_student_access_after_fees(child),
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
        notice = PaymentNotice.objects.create(
            student=child,
            declared_amount=amount,
            amount=amount,
            date=date.today(),
            note=str(request.data.get("note", "")).strip(),
            receipt=request.FILES.get("receipt"),
        )
        return Response(
            PaymentNoticeSerializer(notice, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ParentHomeworkView(APIView):
    permission_classes = [IsParent]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])
        homework = (
            Homework.objects.filter(school_class_id=child.school_class_id)
            .select_related("teacher", "school_class")
            .prefetch_related("attachment_files")
            .order_by("-created_at")
        )
        return Response(HomeworkSerializer(homework, many=True, context={"request": request}).data)

    def post(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)

        homework_id = request.data.get("homeworkId")
        homework = Homework.objects.filter(id=homework_id).first()
        if not homework or homework.school_class_id != child.school_class_id:
            return Response({"detail": "الواجب غير متاح"}, status=status.HTTP_400_BAD_REQUEST)
        if not homework_is_open(homework):
            return Response({"detail": "انتهت مهلة تسليم هذا الواجب"}, status=status.HTTP_400_BAD_REQUEST)

        content = str(request.data.get("content", "")).strip()
        attachment = request.FILES.get("attachment")
        existing = HomeworkSubmission.objects.filter(homework=homework, student=child).first()

        has_text = bool(content)
        has_file = bool(attachment) or bool(existing and existing.attachment)
        if not has_text and not has_file:
            return Response({"detail": "أضف نصاً أو مرفقاً للتسليم"}, status=status.HTTP_400_BAD_REQUEST)

        submission, created = HomeworkSubmission.objects.update_or_create(
            homework=homework,
            student=child,
            defaults={"content": content, "max_score": homework.max_score},
        )
        if attachment:
            submission.attachment = attachment
        if not created:
            submission.submitted_at = timezone.now()
        submission.save()

        return Response(
            HomeworkSubmissionSerializer(
                submission,
                context={"request": request, "hide_grades_from_student": True},
            ).data,
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED,
        )


class ParentHomeworkBySubjectView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])

        homework = (
            Homework.objects.filter(school_class_id=child.school_class_id)
            .select_related("teacher", "school_class")
            .order_by("subject", "-created_at")
        )
        grouped: dict[str, dict] = {}
        for hw in homework:
            subject = hw.subject.strip() or "عام"
            if subject not in grouped:
                grouped[subject] = {
                    "subject": subject,
                    "teacherName": hw.teacher.name,
                    "homework": [],
                }
            grouped[subject]["homework"].append(
                HomeworkSerializer(hw, context={"request": request}).data
            )

        return Response(list(grouped.values()))


class ParentSubjectsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response([])

        class_id = school_class_id_for_student(child)
        if not class_id:
            return Response([])

        grouped: dict[str, dict] = {}
        for row in class_subject_assignments(class_id):
            grouped[row["subject"]] = {
                "subject": row["subject"],
                "teacherName": row["teacherName"],
                "homeworkCount": 0,
                "quizCount": 0,
                "announcementCount": 0,
                "materialCount": 0,
                "latestAt": None,
            }

        homework = Homework.objects.filter(school_class_id=class_id).only(
            "subject", "created_at"
        )
        quizzes = Quiz.objects.filter(school_class_id=class_id).only(
            "subject", "created_at"
        )
        announcements = SubjectAnnouncement.objects.filter(
            school_class_id=class_id
        ).only("subject", "created_at")
        materials = SubjectMaterial.objects.filter(
            school_class_id=class_id
        ).only("subject", "created_at")

        def touch_row(subject: str, created_at):
            if subject in grouped:
                row = grouped[subject]
            else:
                row = grouped.setdefault(
                    subject,
                    {
                        "subject": subject,
                        "teacherName": "",
                        "homeworkCount": 0,
                        "quizCount": 0,
                        "announcementCount": 0,
                        "materialCount": 0,
                        "latestAt": created_at,
                    },
                )
            if row["latestAt"] is None or created_at > row["latestAt"]:
                row["latestAt"] = created_at
            return row

        for hw in homework:
            subject = _subject_label(hw.subject)
            row = touch_row(subject, hw.created_at)
            row["homeworkCount"] += 1

        for quiz in quizzes:
            subject = _subject_label(quiz.subject)
            row = touch_row(subject, quiz.created_at)
            row["quizCount"] += 1

        for ann in announcements:
            subject = _subject_label(ann.subject)
            row = touch_row(subject, ann.created_at)
            row["announcementCount"] += 1

        for mat in materials:
            subject = _subject_label(mat.subject)
            row = touch_row(subject, mat.created_at)
            row["materialCount"] += 1

        result = []
        for row in grouped.values():
            row["totalCount"] = (
                row["homeworkCount"]
                + row["quizCount"]
                + row["announcementCount"]
                + row["materialCount"]
            )
            row["latestAt"] = row["latestAt"].isoformat() if row["latestAt"] else None
            result.append(row)
        result.sort(key=lambda r: (r["subject"]))
        return Response(result)


class ParentSubjectDetailView(APIView):
    permission_classes = [IsParent]

    def get(self, request, subject):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response({"subject": subject, "items": []})

        subject_label = _subject_label(subject)
        homework = (
            Homework.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_homework_q(subject_label))
            .select_related("teacher", "school_class")
            .order_by("-created_at")
        )
        quizzes = (
            Quiz.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_quiz_q(subject_label))
            .select_related("teacher")
            .prefetch_related("questions")
            .order_by("-created_at")
        )
        announcements = (
            SubjectAnnouncement.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_announcement_q(subject_label))
            .select_related("teacher", "school_class")
            .order_by("-created_at")
        )
        materials = (
            SubjectMaterial.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_material_q(subject_label))
            .select_related("teacher", "school_class")
            .prefetch_related("files")
            .order_by("-created_at")
        )

        items = []
        for hw in homework:
            items.append({
                "kind": "homework",
                "createdAt": hw.created_at.isoformat(),
                "homework": HomeworkSerializer(hw, context={"request": request}).data,
            })
        for quiz in quizzes:
            items.append({
                "kind": "quiz",
                "createdAt": quiz.created_at.isoformat(),
                "quiz": QuizSerializer(
                    quiz,
                    context={"request": request, "hide_quiz_answers": True, "student": child},
                ).data,
            })
        for ann in announcements:
            items.append({
                "kind": "announcement",
                "createdAt": ann.created_at.isoformat(),
                "announcement": SubjectAnnouncementSerializer(ann, context={"request": request}).data,
            })
        for mat in materials:
            items.append({
                "kind": "material",
                "createdAt": mat.created_at.isoformat(),
                "material": SubjectMaterialSerializer(mat, context={"request": request}).data,
            })
        items.sort(key=lambda row: row["createdAt"], reverse=True)

        teacher_name = ""
        if homework.exists():
            teacher_name = homework.first().teacher.name
        elif quizzes.exists():
            teacher_name = quizzes.first().teacher.name
        elif announcements.exists():
            teacher_name = announcements.first().teacher.name
        elif materials.exists():
            teacher_name = materials.first().teacher.name

        return Response({
            "subject": subject_label,
            "teacherName": teacher_name,
            "items": items,
        })


class ParentHomeworkDetailView(APIView):
    permission_classes = [IsParent]

    def get(self, request, homework_id):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)

        homework = (
            Homework.objects.filter(id=homework_id, school_class_id=child.school_class_id)
            .select_related("teacher", "school_class")
            .prefetch_related("attachment_files")
            .first()
        )
        if not homework:
            return Response({"detail": "الواجب غير متاح"}, status=status.HTTP_404_NOT_FOUND)

        return Response(HomeworkSerializer(homework, context={"request": request}).data)


class ParentQuizzesView(APIView):
    permission_classes = [IsParent]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])
        quizzes = (
            Quiz.objects.filter(school_class_id=child.school_class_id)
            .select_related("school_class", "teacher")
            .prefetch_related("questions")
        )
        return Response(
            QuizSerializer(quizzes, many=True, context={"request": request, "hide_quiz_answers": True, "student": child}).data
        )

    def post(self, request):
        import json

        from assignments.quiz_services import (
            can_take_quiz_attempt,
            quiz_attempt_count,
            quiz_attempts_remaining,
            quiz_has_manual_questions,
            quiz_is_open,
            quiz_max_score,
            score_quiz_answers,
        )

        child = _child_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)

        quiz_id = request.data.get("quizId")
        answers_raw = request.data.get("answers", [])
        if isinstance(answers_raw, str):
            try:
                answers = json.loads(answers_raw)
            except json.JSONDecodeError:
                return Response({"detail": "صيغة الإجابات غير صالحة"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            answers = answers_raw if isinstance(answers_raw, list) else []

        time_spent = request.data.get("timeSpentSeconds", 0)
        essay_files = collect_quiz_essay_files(request)

        try:
            quiz = Quiz.objects.prefetch_related("questions").get(id=quiz_id)
        except Quiz.DoesNotExist:
            return Response({"detail": "الاختبار غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        if quiz.school_class_id != child.school_class_id:
            return Response({"detail": "الاختبار غير متاح"}, status=status.HTTP_400_BAD_REQUEST)

        if not quiz_is_open(quiz):
            return Response({"detail": "الاختبار غير متاح حالياً"}, status=status.HTTP_400_BAD_REQUEST)

        if not can_take_quiz_attempt(quiz, child):
            return Response({"detail": "استنفدت جميع المحاولات المتاحة"}, status=status.HTTP_400_BAD_REQUEST)

        attempt_number = quiz_attempt_count(quiz, child) + 1

        questions = list(quiz.questions.all())
        for index, question in enumerate(questions):
            if question.question_type != QuestionType.ESSAY:
                continue
            text = str(answers[index] if index < len(answers) else "").strip()
            if not text and str(question.id) not in essay_files:
                return Response(
                    {"detail": "يرجى كتابة إجابة أو إرفاق ملف لكل سؤال مقالي"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        auto_score = score_quiz_answers(questions, answers)
        max_score = quiz_max_score(questions)
        fully_graded = not quiz_has_manual_questions(questions)

        submission = QuizSubmission.objects.create(
            quiz=quiz,
            student=child,
            attempt_number=attempt_number,
            answers=answers,
            auto_score=auto_score,
            manual_scores={},
            score=auto_score,
            max_score=max_score,
            time_spent_seconds=time_spent,
            teacher_note="",
            graded_at=timezone.now() if fully_graded else None,
        )
        if essay_files:
            save_quiz_answer_attachments(submission, essay_files)

        payload = QuizSubmissionSerializer(
            submission,
            context={"request": request, "hide_grades_from_student": True},
        ).data
        payload["attemptsUsed"] = attempt_number
        payload["attemptsRemaining"] = quiz_attempts_remaining(quiz, child)
        return Response(payload, status=status.HTTP_201_CREATED)


class ParentQuizReviewView(APIView):
    permission_classes = [IsParent]

    def get(self, request, quiz_id):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)

        quiz = (
            Quiz.objects.filter(id=quiz_id, school_class_id=child.school_class_id)
            .select_related("school_class", "teacher")
            .prefetch_related("questions")
            .first()
        )
        if not quiz:
            return Response({"detail": "الاختبار غير متاح"}, status=status.HTTP_404_NOT_FOUND)
        if not quiz.review_allowed:
            return Response(
                {"detail": "لم يفعّل المعلم مراجعة هذا الاختبار"},
                status=status.HTTP_403_FORBIDDEN,
            )

        submission = (
            QuizSubmission.objects.filter(quiz=quiz, student=child)
            .select_related("quiz")
            .prefetch_related("quiz__questions", "answer_attachments")
            .order_by("-score", "-attempt_number")
            .first()
        )
        if not submission:
            return Response({"detail": "لم يتم تسليم هذا الاختبار"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "quiz": QuizSerializer(
                    quiz,
                    context={"request": request, "hide_quiz_answers": False},
                ).data,
                "submission": QuizSubmissionSerializer(
                    submission,
                    context={"request": request, "hide_grades_from_student": False},
                ).data,
            }
        )


class ParentSubmissionsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"homework": [], "quizzes": []})
        hw = HomeworkSubmission.objects.filter(student=child).select_related("homework", "homework__school_class")
        qz = list(
            QuizSubmission.objects.filter(student=child)
            .select_related("quiz", "quiz__school_class")
            .prefetch_related("quiz__questions", "answer_attachments")
        )
        from assignments.quiz_services import best_quiz_submission_ids

        best_ids = best_quiz_submission_ids(qz)
        quiz_context = {
            "request": request,
            "hide_grades_from_student": True,
            "best_submission_ids": best_ids,
        }
        return Response({
            "homework": HomeworkSubmissionSerializer(
                hw,
                many=True,
                context={"request": request, "hide_grades_from_student": True},
            ).data,
            "quizzes": QuizSubmissionSerializer(qz, many=True, context=quiz_context).data,
        })


class PublicSiteSettingsView(CachedAPIViewMixin, APIView):
    permission_classes = [AllowAny]
    cache_prefix = "public:site"

    def get(self, request):
        return self.get_cached(request, lambda: self._serialize(SiteSettings.get()))

    def _programs(self, s):
        mapping = s.programs_by_grade or {}
        return [
            {"grade": g.name, "description": str(mapping.get(g.name, "") or "")}
            for g in Grade.objects.all().order_by("sort_order", "name")
        ]

    def _registration_grade_choices(self):
        return [
            {"value": g.name, "label": g.name}
            for g in Grade.objects.all().order_by("sort_order", "name")
        ]

    def _serialize(self, s):
        return {
            "hero": {
                "welcome": s.hero_welcome,
                "schoolName": s.hero_school_name,
                "tagline": s.hero_tagline,
                "description": s.hero_description,
                "ctaPrimary": s.hero_cta_primary,
                "ctaSecondary": s.hero_cta_secondary,
            },
            "about": {
                "description": s.about_description,
                "vision": s.about_vision,
                "mission": s.about_mission,
            },
            "contact": {
                "address": s.contact_address,
                "phone": s.contact_phone,
                "email": s.contact_email,
                "footerTagline": s.footer_tagline,
            },
            "registration": {
                "showNotes": s.reg_show_notes,
                "showBirthDate": s.reg_show_birth_date,
                "gradeChoices": self._registration_grade_choices(),
            },
            "programs": self._programs(s),
        }


class AdminSiteSettingsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        s = SiteSettings.get()
        return Response(PublicSiteSettingsView()._serialize(s))

    def patch(self, request):
        s = SiteSettings.get()
        data = request.data

        hero = data.get("hero", {})
        if "welcome" in hero:
            s.hero_welcome = hero["welcome"]
        if "schoolName" in hero:
            s.hero_school_name = hero["schoolName"]
        if "tagline" in hero:
            s.hero_tagline = hero["tagline"]
        if "description" in hero:
            s.hero_description = hero["description"]
        if "ctaPrimary" in hero:
            s.hero_cta_primary = hero["ctaPrimary"]
        if "ctaSecondary" in hero:
            s.hero_cta_secondary = hero["ctaSecondary"]

        about = data.get("about", {})
        if "description" in about:
            s.about_description = about["description"]
        if "vision" in about:
            s.about_vision = about["vision"]
        if "mission" in about:
            s.about_mission = about["mission"]

        contact = data.get("contact", {})
        if "address" in contact:
            s.contact_address = contact["address"]
        if "phone" in contact:
            s.contact_phone = contact["phone"]
        if "email" in contact:
            s.contact_email = contact["email"]
        if "footerTagline" in contact:
            s.footer_tagline = contact["footerTagline"]

        reg = data.get("registration", {})
        if "showNotes" in reg:
            s.reg_show_notes = bool(reg["showNotes"])
        if "showBirthDate" in reg:
            s.reg_show_birth_date = bool(reg["showBirthDate"])

        programs = data.get("programs")
        if isinstance(programs, list):
            # programs: [{grade, description}]
            next_map = {}
            for row in programs:
                if not isinstance(row, dict):
                    continue
                grade = str(row.get("grade", "")).strip()
                desc = str(row.get("description", "")).strip()
                if grade:
                    next_map[grade] = desc
            s.programs_by_grade = next_map

        s.save()
        return Response(PublicSiteSettingsView()._serialize(s))


class PublicAdmissionApplicationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        student_name = str(data.get("studentName", "")).strip()
        parent_name = str(data.get("parentName", "")).strip()
        grade = str(data.get("grade", "")).strip()
        phone = str(data.get("phone", "")).strip()
        email = str(data.get("email", "")).strip()
        notes = str(data.get("notes", "")).strip()
        birth_date_raw = str(data.get("birthDate", "")).strip()
        national_id = str(data.get("nationalId", "")).strip()
        if not national_id:
            return Response({"detail": "رقم الهوية مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r"\d{9}", national_id):
            return Response(
                {"detail": "رقم الهوية يجب أن يتكون من 9 أرقام"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if Student.objects.filter(national_id=national_id).exists():
            return Response(
                {"detail": "رقم الهوية مستخدم مسبقاً لطالب مسجّل في المدرسة"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if AdmissionApplication.objects.filter(
            national_id=national_id, status=AdmissionStatus.PENDING
        ).exists():
            return Response(
                {"detail": "يوجد طلب قبول قيد المراجعة بنفس رقم الهوية"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not student_name or not parent_name or not grade or not phone:
            return Response({"detail": "يرجى تعبئة الحقول المطلوبة"}, status=status.HTTP_400_BAD_REQUEST)

        birth_date = None
        if birth_date_raw:
            try:
                birth_date = date.fromisoformat(birth_date_raw)
            except ValueError:
                return Response({"detail": "تاريخ الميلاد غير صالح"}, status=status.HTTP_400_BAD_REQUEST)

        app = AdmissionApplication.objects.create(
            student_name=student_name,
            national_id=national_id,
            parent_name=parent_name,
            grade=grade,
            phone=phone,
            email=email,
            notes=notes,
            birth_date=birth_date,
        )
        return Response({"id": str(app.id), "status": app.status}, status=status.HTTP_201_CREATED)


class AdminAdmissionApplicationsView(APIView):
    permission_classes = [AdminScopePermission("students")]

    def get(self, request):
        status_filter = (request.query_params.get("status") or "").strip()
        qs = AdmissionApplication.objects.select_related("approved_student", "approved_by")
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = [
            {
                "id": str(a.id),
                "studentName": a.student_name,
                "nationalId": a.national_id or "",
                "birthDate": str(a.birth_date) if a.birth_date else None,
                "grade": a.grade,
                "parentName": a.parent_name,
                "phone": a.phone,
                "email": a.email,
                "notes": a.notes,
                "status": a.status,
                "createdAt": a.created_at.isoformat(),
                "approvedStudentId": str(a.approved_student_id) if a.approved_student_id else None,
                "approvedByName": a.approved_by.display_name if a.approved_by else None,
                "approvedAt": a.approved_at.isoformat() if a.approved_at else None,
            }
            for a in qs.order_by("-created_at", "-id")[:500]
        ]
        return Response(data)


class AdminApproveAdmissionView(APIView):
    permission_classes = [AdminScopePermission("students")]

    def post(self, request, app_id: str):
        app = AdmissionApplication.objects.filter(id=app_id).select_related("approved_student").first()
        if not app:
            return Response({"detail": "الطلب غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        if app.status == "approved" and app.approved_student_id:
            return Response({"studentId": str(app.approved_student_id), "status": app.status})

        class_id = request.data.get("classId")
        if not class_id:
            return Response({"detail": "يجب اختيار فصل وشعبة"}, status=status.HTTP_400_BAD_REQUEST)

        if not SchoolClass.objects.filter(id=class_id).exists():
            return Response({"detail": "الفصل المحدد غير موجود"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = StudentSerializer(
            data={
                "name": app.student_name,
                "nationalId": app.national_id or "",
                "classId": class_id,
                "is_active": True,
            },
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        student = serializer.save()
        generated_password = getattr(student, "_generated_password", None)
        StudentFeeBalance.objects.get_or_create(student=student, defaults={"total": 0, "paid": 0})
        apply_plan_to_student(student)

        app.status = "approved"
        app.approved_student = student
        app.approved_by = request.user
        app.approved_at = timezone.now()
        app.save(update_fields=["status", "approved_student", "approved_by", "approved_at"])

        return Response(
            {
                "studentId": str(student.id),
                "status": app.status,
                "studentNumber": student.student_number,
                "username": student.parent.username if student.parent_id else None,
                "password": generated_password,
                "approvedByName": request.user.display_name,
                "approvedAt": app.approved_at.isoformat(),
            }
        )


class AdminUnapproveAdmissionView(APIView):
    permission_classes = [AdminScopePermission("students")]

    def post(self, request, app_id: str):
        app = (
            AdmissionApplication.objects.filter(id=app_id)
            .select_related("approved_student", "approved_student__parent")
            .first()
        )
        if not app:
            return Response({"detail": "الطلب غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        if app.status != "approved":
            return Response({"detail": "الطلب غير معتمد"}, status=status.HTTP_400_BAD_REQUEST)

        student = app.approved_student
        if student:
            parent = student.parent
            student.delete()
            if parent:
                parent.delete()

        app.status = "pending"
        app.approved_student = None
        app.approved_by = None
        app.approved_at = None
        app.save(update_fields=["status", "approved_student", "approved_by", "approved_at"])

        return Response({"id": str(app.id), "status": app.status})


class AdminDeleteAdmissionView(APIView):
    permission_classes = [AdminScopePermission("students")]

    def delete(self, request, app_id: str):
        app = AdmissionApplication.objects.filter(id=app_id).first()
        if not app:
            return Response({"detail": "الطلب غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        if app.status == "approved" and app.approved_student_id:
            return Response(
                {"detail": "لا يمكن حذف طلب معتمد مرتبط بطالب"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        app.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicContactMessageView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        email = str(request.data.get("email", "")).strip()
        phone = str(request.data.get("phone", "")).strip()
        message = str(request.data.get("message", "")).strip()
        if not name or not message:
            return Response({"detail": "يرجى تعبئة الحقول المطلوبة"}, status=status.HTTP_400_BAD_REQUEST)
        if not email and not phone:
            return Response(
                {"detail": "يرجى إدخال البريد الإلكتروني أو رقم الهاتف"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        msg = ContactMessage.objects.create(name=name, email=email, phone=phone, message=message)
        return Response({"id": str(msg.id), "status": msg.status}, status=status.HTTP_201_CREATED)


class AdminContactMessagesView(APIView):
    permission_classes = [AdminScopePermission("content")]

    def get(self, request):
        status_filter = (request.query_params.get("status") or "").strip()
        qs = ContactMessage.objects.all()
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = [
            {
                "id": str(m.id),
                "name": m.name,
                "email": m.email,
                "phone": m.phone,
                "message": m.message,
                "status": m.status,
                "createdAt": m.created_at.isoformat(),
            }
            for m in qs.order_by("-created_at", "-id")[:500]
        ]
        return Response(data)


class AdminArchiveContactMessageView(APIView):
    permission_classes = [AdminScopePermission("content")]

    def post(self, request, message_id: str):
        msg = ContactMessage.objects.filter(id=message_id).first()
        if not msg:
            return Response({"detail": "الرسالة غير موجودة"}, status=status.HTTP_404_NOT_FOUND)
        msg.status = "archived"
        msg.save(update_fields=["status"])
        return Response({"id": str(msg.id), "status": msg.status})


class AdminBlockedStudentsView(APIView):
    permission_classes = [AdminScopePermission("finance")]

    def get(self, request):
        rows = []
        for student in Student.objects.select_related("fee_balance").filter(is_active=True).order_by("name"):
            status = build_fee_status(student)
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
        return Response(rows)


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
        return qs


class ParentSchedulesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])

        schedule_type = (request.query_params.get("type") or "").strip()
        qs = Schedule.objects.filter(is_published=True).prefetch_related("school_classes")
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


def _normalize_teacher_name(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _school_class_label(school_class):
    section = school_class.section or ""
    label = f"{school_class.grade_level} - {section}".strip(" -")
    return label or school_class.name


class TeacherSchedulesView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response([])

        teacher_name = _normalize_teacher_name(teacher.name)
        qs = (
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
                subject = (entry.get("subject") or "").strip()
                if not subject:
                    continue
                day = (entry.get("day") or "").strip()
                time = (entry.get("time") or "").strip()
                duration = (entry.get("duration") or "").strip() or "60"
                rows.append(
                    {
                        "id": f"{schedule.id}-{index}-{day}-{time}-{subject}",
                        "scheduleId": str(schedule.id),
                        "scheduleName": schedule.name,
                        "day": day,
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


class AcademicContextView(CachedAPIViewMixin, APIView):
    permission_classes = [IsAuthenticated]
    cache_prefix = "academic:context"
    cache_ttl = 120

    def get(self, request):
        return self.get_cached(
            request,
            lambda: (
                ensure_default_academic_calendar(),
                serialize_academic_context(),
            )[1],
        )


class AdminAcademicYearViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics")]
    serializer_class = AcademicYearWriteSerializer
    queryset = AcademicYear.objects.prefetch_related("terms").all()

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
                new_year_name=request.data.get("newYearName"),
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
