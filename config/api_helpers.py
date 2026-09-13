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



# --- shared helpers extracted from api_views ---

def _teacher_for_user(user):
    return TeacherProfile.objects.filter(user=user).first()



def _operational_term():
    from academics.term_operational_services import require_operational_term

    return require_operational_term()



def _scope_operational_term(qs):
    from academics.term_operational_services import scope_to_current_term

    return scope_to_current_term(qs)



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



def _validate_teacher_class_ids_response(teacher, class_ids):
    """Return a 4xx Response if the teacher may not use any class_id, else None."""
    from academics.grade_scheme_services import teacher_teachable_class_ids

    allowed = set(teacher_teachable_class_ids(teacher))
    parsed_ids = []
    for class_id in class_ids:
        try:
            parsed_ids.append(int(class_id))
        except (TypeError, ValueError):
            return Response({"detail": "معرّف فصل غير صالح"}, status=status.HTTP_400_BAD_REQUEST)

    if not parsed_ids:
        return None

    classes = {row.id: row for row in SchoolClass.objects.filter(id__in=parsed_ids)}
    for cid in parsed_ids:
        school_class = classes.get(cid)
        if not school_class:
            return Response({"detail": "الصف غير موجود"}, status=status.HTTP_404_NOT_FOUND)
        if cid not in allowed:
            return Response(
                {"detail": f"لا تدرّس في فصل {school_class.name}"},
                status=status.HTTP_403_FORBIDDEN,
            )
    return None



def _teacher_school_class_or_response(teacher, class_id):
    """Return (school_class, None) or (None, error Response)."""
    err = _validate_teacher_class_ids_response(teacher, [class_id])
    if err:
        return None, err
    return SchoolClass.objects.filter(id=int(class_id)).first(), None



def _linked_student_for_parent(user):
    return (
        Student.objects.filter(parent=user)
        .select_related("school_class", "fee_balance", "parent")
        .prefetch_related(
            "uploaded_documents",
            Prefetch(
                "payment_notices",
                queryset=PaymentNotice.objects.order_by("-date", "-id"),
            ),
        )
        .order_by("-is_active", "id")
        .first()
    )



def _child_for_parent(user):
    student = _linked_student_for_parent(user)
    if not student:
        return None
    if build_fee_status(student, link_plan=False).get("blocked"):
        return None
    return student



def _parse_gradebook_score(raw):
    if raw is None or raw == "":
        return None, None
    try:
        score = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None, Response({"detail": "درجة غير صالحة"}, status=status.HTTP_400_BAD_REQUEST)
    if score < 0 or score > 100:
        return None, Response(
            {"detail": "الدرجة يجب أن تكون بين 0 و 100"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return score, None



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



def _subject_label(value):
    label = str(value or "").strip()
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



def _sync_grade_sections(grade: Grade):
    from academics.services import sync_grade_sections

    sync_grade_sections(grade)



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



def _normalize_teacher_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()



def _schedule_entry_text(value, default=""):
    text = str(value).strip() if value is not None else ""
    return text if text else default



def _school_class_label(school_class):
    section = school_class.section or ""
    label = f"{school_class.grade_level} - {section}".strip(" -")
    return label or school_class.name



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

# Star-imports skip leading-underscore names unless listed in __all__.
__all__ = [
    "AR_MONTHS",
    "_teacher_for_user",
    "_operational_term",
    "_scope_operational_term",
    "_parse_class_ids",
    "_validate_teacher_class_ids_response",
    "_teacher_school_class_or_response",
    "_linked_student_for_parent",
    "_child_for_parent",
    "_parse_gradebook_score",
    "_shift_month",
    "_build_fees_chart",
    "_build_grade_chart",
    "_publish_homework_grades",
    "_publish_quiz_grades",
    "_subject_label",
    "_subject_homework_q",
    "_subject_quiz_q",
    "_subject_announcement_q",
    "_subject_material_q",
    "_sync_grade_sections",
    "_sync_grade_sections_count",
    "_normalize_teacher_name",
    "_schedule_entry_text",
    "_school_class_label",
]



