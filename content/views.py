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
            lambda: SchoolStatSerializer(SchoolStat.public_queryset(), many=True).data,
        )



class PublicSchoolValuesView(CachedAPIViewMixin, APIView):
    permission_classes = [AllowAny]
    cache_prefix = "public:values"

    def get(self, request):
        return self.get_cached(
            request,
            lambda: SchoolValueSerializer(SchoolValue.objects.all(), many=True).data,
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



class PublicSiteSettingsView(CachedAPIViewMixin, APIView):
    permission_classes = [AllowAny]
    cache_prefix = "public:site"

    def get(self, request):
        return self.get_cached(request, lambda: self._serialize(SiteSettings.get(), request))

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

    def _serialize(self, s, request=None):
        from config.media_access import build_media_url

        hero_image_url = build_media_url(request, s.hero_image) if s.hero_image else None
        return {
            "hero": {
                "welcome": s.hero_welcome,
                "schoolName": s.hero_school_name,
                "tagline": s.hero_tagline,
                "description": s.hero_description,
                "ctaPrimary": s.hero_cta_primary,
                "ctaSecondary": s.hero_cta_secondary,
                "imageUrl": hero_image_url,
                "imageHeight": s.hero_image_height or "100dvh",
                "imageObjectFit": s.hero_image_object_fit or "cover",
                "imageObjectPosition": s.hero_image_object_position or "center top",
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
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        s = SiteSettings.get()
        return Response(PublicSiteSettingsView()._serialize(s, request))

    def _parse_nested(self, raw):
        if raw in (None, ""):
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            import json

            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def patch(self, request):
        s = SiteSettings.get()
        is_multipart = request.content_type and "multipart" in request.content_type
        data = request.data

        hero_image = request.FILES.get("heroImage")
        if hero_image:
            from assignments.attachment_utils import validate_uploaded_file

            validate_uploaded_file(hero_image)
            if s.hero_image:
                s.hero_image.delete(save=False)
            s.hero_image = hero_image

        remove_flag = str(data.get("removeHeroImage", "")).lower()
        if remove_flag in ("1", "true", "yes"):
            if s.hero_image:
                s.hero_image.delete(save=False)
                s.hero_image = None

        hero = self._parse_nested(data.get("hero")) if is_multipart else data.get("hero", {})
        if not isinstance(hero, dict):
            hero = {}
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
        if "imageHeight" in hero:
            s.hero_image_height = str(hero["imageHeight"]).strip() or "100dvh"
        if "imageObjectFit" in hero:
            fit = str(hero["imageObjectFit"]).strip() or "cover"
            if fit in ("cover", "contain"):
                s.hero_image_object_fit = fit
        if "imageObjectPosition" in hero:
            s.hero_image_object_position = str(hero["imageObjectPosition"]).strip() or "center top"

        about = self._parse_nested(data.get("about")) if is_multipart else data.get("about", {})
        if not isinstance(about, dict):
            about = {}
        if "description" in about:
            s.about_description = about["description"]
        if "vision" in about:
            s.about_vision = about["vision"]
        if "mission" in about:
            s.about_mission = about["mission"]

        contact = self._parse_nested(data.get("contact")) if is_multipart else data.get("contact", {})
        if not isinstance(contact, dict):
            contact = {}

        if "address" in contact:
            s.contact_address = contact["address"]
        if "phone" in contact:
            s.contact_phone = contact["phone"]
        if "email" in contact:
            s.contact_email = contact["email"]
        if "footerTagline" in contact:
            s.footer_tagline = contact["footerTagline"]

        reg = self._parse_nested(data.get("registration")) if is_multipart else data.get("registration", {})
        if not isinstance(reg, dict):
            reg = {}

        if "showNotes" in reg:
            s.reg_show_notes = bool(reg["showNotes"])
        if "showBirthDate" in reg:
            s.reg_show_birth_date = bool(reg["showBirthDate"])

        programs_raw = data.get("programs")
        if is_multipart and isinstance(programs_raw, str):
            import json

            try:
                programs_raw = json.loads(programs_raw)
            except json.JSONDecodeError:
                programs_raw = None
        programs = programs_raw
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
        return Response(PublicSiteSettingsView()._serialize(s, request))



class PublicAdmissionApplicationView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PublicPostRateThrottle]

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
        address = str(data.get("address", "")).strip()
        if not national_id:
            return Response({"detail": "رقم الهوية مطلوب"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r"\d{9}", national_id):
            return Response(
                {"detail": "رقم الهوية يجب أن يتكون من 9 أرقام"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Anti-enumeration: same status + message whether duplicate or created.
        if Student.objects.filter(national_id=national_id).exists() or AdmissionApplication.objects.filter(
            national_id=national_id, status=AdmissionStatus.PENDING
        ).exists():
            return Response(
                {"detail": "تم استلام طلبك. سنتواصل معك قريباً."},
                status=status.HTTP_201_CREATED,
            )

        if not student_name or not parent_name or not grade or not phone:
            return Response({"detail": "يرجى تعبئة الحقول المطلوبة"}, status=status.HTTP_400_BAD_REQUEST)

        birth_date = None
        if birth_date_raw:
            try:
                birth_date = date.fromisoformat(birth_date_raw)
            except ValueError:
                return Response({"detail": "تاريخ الميلاد غير صالح"}, status=status.HTTP_400_BAD_REQUEST)

        AdmissionApplication.objects.create(
            student_name=student_name,
            national_id=national_id,
            parent_name=parent_name,
            grade=grade,
            phone=phone,
            address=address,
            email=email,
            notes=notes,
            birth_date=birth_date,
        )
        return Response(
            {"detail": "تم استلام طلبك. سنتواصل معك قريباً."},
            status=status.HTTP_201_CREATED,
        )



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
                "address": a.address or "",
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

        student_payload = {
            "name": app.student_name,
            "parentPhone": app.phone or "",
            "address": app.address or "",
            "classId": class_id,
            "isActive": True,
        }
        if app.national_id:
            student_payload["nationalId"] = app.national_id
        serializer = StudentSerializer(
            data=student_payload,
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
    throttle_classes = [PublicPostRateThrottle]

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


