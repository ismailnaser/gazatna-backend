from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import ClassGradebook, Grade, SchoolClass, Student, StudentDocument, Subject, SubjectGrade
from accounts.models import User
from accounts.roles import ADMIN_ROLES
from accounts.serializers import UserCreateSerializer, UserSerializer
from accounts.utils import generate_five_digit_password
from assignments.models import Homework, HomeworkSubmission, Quiz, QuizSubmission
from config.permissions import AdminScopePermission, IsAdmin, IsParent, IsSuperAdmin, IsTeacher
from config.serializers import (
    AccreditationSerializer,
    ActivitySerializer,
    AlumniSerializer,
    ClassGradebookSerializer,
    ClassStudentSerializer,
    FeePlanSerializer,
    FinanceNoticeSerializer,
    HomeworkSerializer,
    HomeworkSubmissionSerializer,
    NewsItemSerializer,
    ParentChildSerializer,
    PaymentNoticeSerializer,
    PolicySerializer,
    ProgramSerializer,
    QuizSerializer,
    QuizSubmissionSerializer,
    SchoolClassSerializer,
    SchoolClassWriteSerializer,
    GradeSerializer,
    SchoolStatSerializer,
    SchoolValueSerializer,
    StudentSerializer,
    SubjectGradeSerializer,
    SubjectSerializer,
    TeacherProfileSerializer,
    TeacherWriteSerializer,
    ParentAlertSerializer,
)
from content.models import (
    Accreditation,
    Activity,
    Alumni,
    AdmissionApplication,
    ContactMessage,
    NewsImage,
    NewsItem,
    Policy,
    Program,
    SchoolStat,
    SchoolValue,
    SiteSettings,
)
from finance.models import FeePlan, PaymentNotice, StudentFeeBalance
from finance.services import apply_plan_to_student, apply_plan_to_students, build_fee_status
from staff.models import TeacherClassAssignment, TeacherProfile


def _teacher_for_user(user):
    return TeacherProfile.objects.filter(user=user).first()


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
    grade_chart = []
    for level in ["التاسع", "العاشر", "الحادي عشر", "الثاني عشر"]:
        avg = SubjectGrade.objects.filter(
            student__grade_level__contains=level
        ).aggregate(a=Avg("score"))["a"]
        if avg is None:
            continue
        value = round(float(avg))
        if value <= 0:
            continue
        grade_chart.append({"label": level, "value": value})
    return grade_chart


def _child_for_parent(user):
    return Student.objects.filter(parent=user, is_active=True).select_related("school_class", "fee_balance").first()


class PublicNewsViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = NewsItemSerializer
    queryset = NewsItem.objects.filter(is_published=True).prefetch_related("images")


class PublicProgramViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = ProgramSerializer
    queryset = Program.objects.all()


class PublicActivityViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = ActivitySerializer
    queryset = Activity.objects.all()


class PublicAlumniViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = AlumniSerializer
    queryset = Alumni.objects.all()


class PublicPolicyViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = PolicySerializer
    queryset = Policy.objects.all()


class PublicAccreditationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = AccreditationSerializer
    queryset = Accreditation.objects.all()


class PublicStatsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(SchoolStatSerializer(SchoolStat.objects.all(), many=True).data)


class PublicSchoolValuesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(SchoolValueSerializer(SchoolValue.objects.all(), many=True).data)


class PublicTeachersViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = TeacherProfileSerializer
    queryset = TeacherProfile.objects.filter(is_public=True).prefetch_related("teaching_subjects")


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
    permission_classes = [AdminScopePermission("academics")]
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
                school_class.homeroom_teacher = teacher
                school_class.save(update_fields=["homeroom_teacher"])

        students = Student.objects.filter(school_class=school_class, is_active=True).order_by("name")
        return Response(
            {
                "class": SchoolClassSerializer(school_class, context={"request": request}).data,
                "students": StudentSerializer(students, many=True, context={"request": request}).data,
            }
        )


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

    # Remove extra sections if safe
    for cls in existing:
        if cls.section and cls.section not in desired_sections:
            if cls.students.filter(is_active=True).exists():
                raise ValueError(f"لا يمكن تقليل الشعب لأن شعبة {cls.section} تحتوي طلاباً")
            cls.delete()


class AdminGradeViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics")]
    serializer_class = GradeSerializer
    queryset = Grade.objects.all()

    def perform_create(self, serializer):
        grade = serializer.save()
        _sync_grade_sections(grade)

    def perform_update(self, serializer):
        grade = serializer.save()
        _sync_grade_sections(grade)

    def destroy(self, request, *args, **kwargs):
        grade = self.get_object()
        classes = SchoolClass.objects.filter(grade_level=grade.name)
        if Student.objects.filter(school_class__in=classes, is_active=True).exists():
            return Response(
                {"detail": "لا يمكن حذف فصل مرتبط بطلاب"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        classes.delete()
        return super().destroy(request, *args, **kwargs)


class AdminSubjectViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics")]
    serializer_class = SubjectSerializer
    queryset = Subject.objects.all()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.teachers.exists():
            return Response(
                {"detail": "لا يمكن حذف مادة مسندة لمعلمين"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class AdminTeacherViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("staff")]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return TeacherProfile.objects.prefetch_related(
            "class_assignments", "teaching_subjects"
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
        notices = PaymentNotice.objects.select_related("student").order_by("-date", "-id")
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
            if new_status == "approved" and old_status != "approved":
                approve_amount = Decimal(str(request.data.get("amount", notice.amount)))
                notice.amount = approve_amount
                balance, _ = StudentFeeBalance.objects.get_or_create(student=notice.student)
                balance.paid += approve_amount
                balance.save(update_fields=["paid"])
            notice.status = new_status
            notice.reviewed_by = request.user
            notice.save()
        elif "amount" in request.data and notice.status == "pending":
            notice.amount = Decimal(str(request.data["amount"]))
            notice.save(update_fields=["amount"])
        return Response(PaymentNoticeSerializer(notice, context={"request": request}).data)


class AdminAnalyticsView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        avg_grade = SubjectGrade.objects.aggregate(avg=Avg("score"))["avg"] or 0
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

        return Response({
            "avgGrade": round(float(avg_grade), 1),
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
        })


class AdminAnalyticsDetailsView(APIView):
    permission_classes = [IsAdmin]

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
        grade_rows = (
            grades_qs.values("student__grade_level")
            .annotate(avg=Avg("score"))
            .order_by("student__grade_level")
        )
        grade_chart = [
            {"label": (row["student__grade_level"] or ""), "value": round(float(row["avg"] or 0), 1)}
            for row in grade_rows
            if row["student__grade_level"]
        ]

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
        avg_grade = grades_qs.aggregate(avg=Avg("score"))["avg"] or 0
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
                "avgGrade": round(float(avg_grade), 1),
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
        class_ids = TeacherClassAssignment.objects.filter(teacher=teacher).values_list("school_class_id", flat=True)
        classes = SchoolClass.objects.filter(id__in=class_ids)
        return Response(SchoolClassSerializer(classes, many=True).data)


class TeacherProfileView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        teacher = _teacher_for_user(request.user)
        if not teacher:
            return Response(
                {"detail": "لم يتم ربط حسابك بملف معلم"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(TeacherProfileSerializer(teacher).data)


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

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return Homework.objects.none()
        qs = Homework.objects.filter(teacher=teacher).select_related("school_class")
        class_id = self.request.query_params.get("classId")
        if class_id:
            qs = qs.filter(school_class_id=class_id)
        return qs

    def perform_create(self, serializer):
        teacher = _teacher_for_user(self.request.user)
        serializer.save(teacher=teacher)


class TeacherQuizViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]
    serializer_class = QuizSerializer

    def get_queryset(self):
        teacher = _teacher_for_user(self.request.user)
        if not teacher:
            return Quiz.objects.none()
        qs = Quiz.objects.filter(teacher=teacher).prefetch_related("questions")
        class_id = self.request.query_params.get("classId")
        if class_id:
            qs = qs.filter(school_class_id=class_id)
        return qs

    def perform_create(self, serializer):
        teacher = _teacher_for_user(self.request.user)
        serializer.save(teacher=teacher)


class ParentAlertsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response([])

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

        pending_hw = Homework.objects.filter(
            school_class=child.school_class, status="active"
        ).exclude(
            id__in=HomeworkSubmission.objects.filter(student=child).values_list("homework_id", flat=True)
        ).count()
        if pending_hw:
            alerts.append({
                "id": "a4",
                "text": f"لديك {pending_hw} واجب بانتظار التسليم",
                "type": "homework",
            })

        return Response(alerts)


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
        child = _child_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)
        return Response(StudentSerializer(child).data)


class ParentGradesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response([])
        grades = SubjectGrade.objects.filter(student=child)
        return Response(SubjectGradeSerializer(grades, many=True).data)


class ParentFeesView(APIView):
    permission_classes = [IsParent]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"student": None, "notices": [], "feeStatus": None})
        notices = PaymentNotice.objects.filter(student=child).order_by("-date", "-id")
        return Response({
            "student": StudentSerializer(child, context={"request": request}).data,
            "notices": PaymentNoticeSerializer(notices, many=True, context={"request": request}).data,
            "feeStatus": build_fee_status(child),
        })

    def post(self, request):
        child = _child_for_parent(request.user)
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

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])
        homework = Homework.objects.filter(school_class_id=child.school_class_id).order_by("-created_at")
        return Response(HomeworkSerializer(homework, many=True).data)

    def post(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)
        homework_id = request.data.get("homeworkId")
        content = request.data.get("content", "")
        submission, _ = HomeworkSubmission.objects.update_or_create(
            homework_id=homework_id,
            student=child,
            defaults={"content": content},
        )
        return Response(HomeworkSubmissionSerializer(submission).data, status=status.HTTP_201_CREATED)


class ParentQuizzesView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child or not child.school_class_id:
            return Response([])
        quizzes = Quiz.objects.filter(school_class_id=child.school_class_id).prefetch_related("questions")
        return Response(QuizSerializer(quizzes, many=True).data)

    def post(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"detail": "لا يوجد طالب مرتبط"}, status=status.HTTP_404_NOT_FOUND)

        quiz_id = request.data.get("quizId")
        answers = request.data.get("answers", [])
        time_spent = request.data.get("timeSpentSeconds", 0)

        quiz = Quiz.objects.prefetch_related("questions").get(id=quiz_id)
        questions = list(quiz.questions.all())
        score = sum(
            1 for i, q in enumerate(questions)
            if i < len(answers) and answers[i] == q.correct_index
        )
        max_score = len(questions)

        submission, _ = QuizSubmission.objects.update_or_create(
            quiz=quiz,
            student=child,
            defaults={
                "answers": answers,
                "score": Decimal(score),
                "max_score": Decimal(max_score),
                "time_spent_seconds": time_spent,
            },
        )
        return Response(QuizSubmissionSerializer(submission).data, status=status.HTTP_201_CREATED)


class ParentSubmissionsView(APIView):
    permission_classes = [IsParent]

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"homework": [], "quizzes": []})
        hw = HomeworkSubmission.objects.filter(student=child)
        qz = QuizSubmission.objects.filter(student=child)
        return Response({
            "homework": HomeworkSubmissionSerializer(hw, many=True).data,
            "quizzes": QuizSubmissionSerializer(qz, many=True).data,
        })


class PublicSiteSettingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        s = SiteSettings.get()
        return Response(self._serialize(s))

    def _programs(self, s):
        mapping = s.programs_by_grade or {}
        return [
            {"grade": g.name, "description": str(mapping.get(g.name, "") or "")}
            for g in Grade.objects.all().order_by("name")
        ]

    def _registration_grade_choices(self):
        return [
            {"value": g.name, "label": g.name}
            for g in Grade.objects.all().order_by("name")
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
    permission_classes = [IsAdmin]

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
        qs = AdmissionApplication.objects.select_related("approved_student")
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = [
            {
                "id": str(a.id),
                "studentName": a.student_name,
                "birthDate": str(a.birth_date) if a.birth_date else None,
                "grade": a.grade,
                "parentName": a.parent_name,
                "phone": a.phone,
                "email": a.email,
                "notes": a.notes,
                "status": a.status,
                "createdAt": a.created_at.isoformat(),
                "approvedStudentId": str(a.approved_student_id) if a.approved_student_id else None,
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

        # Required extra info for creating Student
        student_number = str(request.data.get("studentNumber", "")).strip()
        section = str(request.data.get("section", "")).strip()
        grade_level = str(request.data.get("gradeLevel", "")).strip() or app.grade

        if not student_number:
            # generate a simple unique student number
            base = str(int(timezone.now().timestamp()))
            student_number = f"S{base[-8:]}"

        # Create parent user? (optional) - not required now
        student = Student.objects.create(
            name=app.student_name,
            student_number=student_number,
            grade_level=grade_level,
            section=section or "",
            is_active=True,
        )
        StudentFeeBalance.objects.get_or_create(student=student, defaults={"total": 0, "paid": 0})
        apply_plan_to_student(student)

        app.status = "approved"
        app.approved_student = student
        app.save(update_fields=["status", "approved_student"])

        return Response({"studentId": str(student.id), "status": app.status})


class PublicContactMessageView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        email = str(request.data.get("email", "")).strip()
        message = str(request.data.get("message", "")).strip()
        if not name or not email or not message:
            return Response({"detail": "يرجى تعبئة الحقول المطلوبة"}, status=status.HTTP_400_BAD_REQUEST)
        msg = ContactMessage.objects.create(name=name, email=email, message=message)
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
                "grade": s.grade_level,
                "section": s.section or "",
                "createdAt": s.created_at.isoformat(),
            }
            for s in Student.objects.filter(is_active=False).order_by("-created_at", "name")
        ]
        return Response(rows)
