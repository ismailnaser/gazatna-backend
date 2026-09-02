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

class PublicTeachersViewSet(CachedReadOnlyViewSetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = TeacherProfileSerializer
    queryset = TeacherProfile.objects.filter(is_public=True, staff_type__is_teacher=True).select_related(
        "staff_type"
    ).prefetch_related(
        "teaching_subjects",
        "class_assignments",
        "homeroom_classes",
    )
    cache_prefix = "public:teachers"

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.action == "list":
            teachable = getattr(self, "_teachable_cache", None)
            subject_map = getattr(self, "_subject_class_cache", None)
            if teachable is not None:
                ctx["teachable_class_ids_cache"] = teachable
            if subject_map is not None:
                ctx["subject_class_ids_cache"] = subject_map
        return ctx

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        teachers = list(page if page is not None else queryset)
        from academics.grade_scheme_services import build_teacher_assignment_caches

        self._teachable_cache, self._subject_class_cache = build_teacher_assignment_caches(teachers)
        return super(CachedReadOnlyViewSetMixin, self).list(request, *args, **kwargs)



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
        return TeacherProfile.objects.select_related("staff_type").prefetch_related(
            "class_assignments", "teaching_subjects", "homeroom_classes"
        ).all()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TeacherWriteSerializer
        return TeacherProfileSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.action == "list":
            teachable = getattr(self, "_teachable_cache", None)
            subject_map = getattr(self, "_subject_class_cache", None)
            if teachable is not None:
                ctx["teachable_class_ids_cache"] = teachable
            if subject_map is not None:
                ctx["subject_class_ids_cache"] = subject_map
        return ctx

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        teachers = list(page if page is not None else queryset)
        from academics.grade_scheme_services import build_teacher_assignment_caches

        self._teachable_cache, self._subject_class_cache = build_teacher_assignment_caches(teachers)
        return super().list(request, *args, **kwargs)

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
        new_password = generate_secure_password()
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



class AdminStaffTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("staff")]
    serializer_class = StaffTypeSerializer
    queryset = StaffType.objects.all()

    def perform_destroy(self, instance):
        if instance.is_teacher:
            raise ValidationError({"detail": "لا يمكن حذف نوع «معلم» من النظام."})
        if instance.members.exists():
            raise ValidationError({"detail": "لا يمكن حذف نوع مرتبط بأعضاء كادر."})
        instance.delete()



class TeacherProfileView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = (
            TeacherProfile.objects.filter(user=request.user)
            .select_related("staff_type", "user")
            .prefetch_related("teaching_subjects", "class_assignments", "homeroom_classes")
            .first()
        )
        if not teacher:
            return Response(
                {"detail": "لم يتم ربط حسابك بملف معلم"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(TeacherProfileSerializer(teacher, context={"request": request}).data)


