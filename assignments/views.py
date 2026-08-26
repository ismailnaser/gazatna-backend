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

class TeacherHomeworkViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]
    serializer_class = HomeworkSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return Homework.objects.none()
        qs = _scope_operational_term(
            Homework.objects.filter(teacher=teacher)
            .select_related("school_class", "teacher")
            .prefetch_related("attachment_files")
            .annotate(_submission_count=Count("submissions"))
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
            access_err = _validate_teacher_class_ids_response(teacher, class_ids)
            if access_err:
                return access_err
            batch_group_id = uuid.uuid4()
            uploaded = collect_uploaded_files(request)
            file_items = _file_bytes_list(uploaded)
            created = []
            for class_id in class_ids:
                hw = Homework.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    academic_term=_operational_term(),
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
                    academic_term=_operational_term(),
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
            .annotate(submission_count=Count("submissions"))
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
                        "submissionCount": int(getattr(hw, "submission_count", 0) or 0),
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
        qs = _scope_operational_term(
            Quiz.objects.filter(teacher=teacher)
            .select_related("school_class", "teacher")
            .prefetch_related("questions")
            .annotate(_submission_count=Count("submissions__student_id", distinct=True))
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
            access_err = _validate_teacher_class_ids_response(teacher, class_ids)
            if access_err:
                return access_err
            batch_group_id = uuid.uuid4()
            created = []
            for class_id in class_ids:
                quiz = Quiz.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    academic_term=_operational_term(),
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
                    academic_term=_operational_term(),
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
            quiz_subs = list(quiz.submissions.all())
            distinct_students = {sub.student_id for sub in quiz_subs}
            targets.append(
                {
                    "id": str(quiz.id),
                    "classId": str(quiz.school_class_id),
                    "className": quiz.school_class.name,
                    "submissionCount": len(distinct_students),
                }
            )
            submissions.extend(quiz_subs)

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
        qs = _scope_operational_term(
            SubjectAnnouncement.objects.filter(teacher=teacher).select_related(
                "school_class", "teacher"
            )
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
            access_err = _validate_teacher_class_ids_response(teacher, class_ids)
            if access_err:
                return access_err
            batch_group_id = uuid.uuid4()
            created = []
            for class_id in class_ids:
                item = SubjectAnnouncement.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    academic_term=_operational_term(),
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
                    academic_term=_operational_term(),
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
        qs = _scope_operational_term(
            SubjectMaterial.objects.filter(teacher=teacher).select_related(
                "school_class", "teacher"
            ).prefetch_related("files")
        )
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
            access_err = _validate_teacher_class_ids_response(teacher, class_ids)
            if access_err:
                return access_err
            batch_group_id = uuid.uuid4()
            created = []
            for class_id in class_ids:
                item = SubjectMaterial.objects.create(
                    school_class_id=class_id,
                    teacher=teacher,
                    group_id=batch_group_id,
                    academic_term=_operational_term(),
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
                    academic_term=_operational_term(),
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
        fee_status = build_fee_status(child, link_plan=False)
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

        pending_hw = _scope_operational_term(
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

        open_quizzes = _scope_operational_term(
            Quiz.objects.filter(school_class=child.school_class).order_by("-created_at")
        )
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
        announcements = _scope_operational_term(
            SubjectAnnouncement.objects.filter(
                school_class=child.school_class,
                created_at__gte=recent_cutoff,
            )
            .select_related("teacher")
            .order_by("-created_at")
        )[:20]
        for ann in announcements:
            subject = _subject_label(ann.subject)
            alerts.append({
                "id": f"ann-{ann.id}",
                "text": f"إعلان — {ann.title} ({subject})",
                "type": "announcement",
                "announcementId": str(ann.id),
                "subject": subject,
            })

        materials = _scope_operational_term(
            SubjectMaterial.objects.filter(
                school_class=child.school_class,
                created_at__gte=recent_cutoff,
            )
            .select_related("teacher")
            .order_by("-created_at")
        )[:20]
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



class ParentHomeworkView(APIView):
    permission_classes = [IsParent]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])
        homework = _scope_operational_term(
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

        homework = _scope_operational_term(
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

        homework = _scope_operational_term(
            Homework.objects.filter(school_class_id=class_id).only("subject", "created_at")
        )
        quizzes = _scope_operational_term(
            Quiz.objects.filter(school_class_id=class_id).only("subject", "created_at")
        )
        announcements = _scope_operational_term(
            SubjectAnnouncement.objects.filter(school_class_id=class_id).only("subject", "created_at")
        )
        materials = _scope_operational_term(
            SubjectMaterial.objects.filter(school_class_id=class_id).only("subject", "created_at")
        )

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
        homework = _scope_operational_term(
            Homework.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_homework_q(subject_label))
            .select_related("teacher", "school_class")
            .order_by("-created_at")
        )
        quizzes = _scope_operational_term(
            Quiz.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_quiz_q(subject_label))
            .select_related("teacher")
            .prefetch_related("questions")
            .order_by("-created_at")
        )
        announcements = _scope_operational_term(
            SubjectAnnouncement.objects.filter(school_class_id=child.school_class_id)
            .filter(_subject_announcement_q(subject_label))
            .select_related("teacher", "school_class")
            .order_by("-created_at")
        )
        materials = _scope_operational_term(
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


