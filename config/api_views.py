from datetime import date
from decimal import Decimal

from django.db.models import Avg, Count, Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import ClassGradebook, SchoolClass, Student, Subject, SubjectGrade
from accounts.models import User
from accounts.roles import ADMIN_ROLES
from accounts.serializers import UserCreateSerializer, UserSerializer
from assignments.models import Homework, HomeworkSubmission, Quiz, QuizSubmission
from config.permissions import AdminScopePermission, IsAdmin, IsParent, IsSuperAdmin, IsTeacher
from config.serializers import (
    AccreditationSerializer,
    ActivitySerializer,
    AlumniSerializer,
    ClassGradebookSerializer,
    ClassStudentSerializer,
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
    SchoolStatSerializer,
    SchoolValueSerializer,
    StudentSerializer,
    SubjectGradeSerializer,
    SubjectSerializer,
    TeacherProfileSerializer,
    TeacherWriteSerializer,
    ParentAlertSerializer,
)
from content.models import Accreditation, Activity, Alumni, NewsItem, Policy, Program, SchoolStat, SchoolValue
from finance.models import PaymentNotice, StudentFeeBalance
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
    queryset = NewsItem.objects.filter(is_published=True)


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


class AdminStudentViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("students")]
    serializer_class = StudentSerializer
    queryset = Student.objects.select_related("school_class", "fee_balance").all()

    def perform_create(self, serializer):
        student = serializer.save()
        StudentFeeBalance.objects.get_or_create(student=student, defaults={"total": 2500, "paid": 0})

    def perform_destroy(self, instance):
        parent = instance.parent
        instance.delete()
        if parent:
            parent.delete()


class AdminClassViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("academics")]
    queryset = SchoolClass.objects.all()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return SchoolClassWriteSerializer
        return SchoolClassSerializer


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


class AdminFinanceViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("finance")]
    serializer_class = PaymentNoticeSerializer
    queryset = PaymentNotice.objects.select_related("student").all()

    def get_serializer_class(self):
        return PaymentNoticeSerializer

    def list(self, request, *args, **kwargs):
        notices = PaymentNotice.objects.select_related("student").order_by("-date")
        data = FinanceNoticeSerializer(
            [
                {
                    "id": str(n.id),
                    "studentName": n.student.name,
                    "amount": float(n.amount),
                    "status": n.status,
                    "date": str(n.date),
                }
                for n in notices
            ],
            many=True,
        ).data
        return Response(data)

    def partial_update(self, request, *args, **kwargs):
        notice = self.get_object()
        new_status = request.data.get("status")
        if new_status:
            notice.status = new_status
            notice.reviewed_by = request.user
            notice.save()
            if new_status == "approved":
                balance, _ = StudentFeeBalance.objects.get_or_create(student=notice.student)
                balance.paid += notice.amount
                balance.save()
        return Response(PaymentNoticeSerializer(notice).data)


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

        urgent_tasks = []
        if pending_count:
            urgent_tasks.append({
                "id": "t1",
                "text": f"{pending_count} إشعارات دفع تنتظر الموافقة",
                "type": "finance",
            })
        if inactive_students:
            urgent_tasks.append({
                "id": "t2",
                "text": f"{inactive_students} طالب جديد ينتظر التفعيل",
                "type": "students",
            })

        grade_chart = _build_grade_chart()
        fees_chart = _build_fees_chart()

        return Response({
            "avgGrade": round(float(avg_grade), 1),
            "feesCollected": fees_collected,
            "urgentTasks": urgent_tasks,
            "gradeChart": grade_chart,
            "feesChart": fees_chart,
        })


class AdminNewsViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminScopePermission("content")]
    serializer_class = NewsItemSerializer
    queryset = NewsItem.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]


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
        latest_payment = PaymentNotice.objects.filter(student=child, status="approved").order_by("-date").first()
        if latest_payment:
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

    def get(self, request):
        child = _child_for_parent(request.user)
        if not child:
            return Response({"student": None, "notices": []})
        notices = PaymentNotice.objects.filter(student=child).order_by("-date")
        return Response({
            "student": StudentSerializer(child).data,
            "notices": PaymentNoticeSerializer(notices, many=True).data,
        })


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
