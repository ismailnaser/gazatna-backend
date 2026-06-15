from django.core.management.base import BaseCommand

from academics.models import ClassGradebook, SchoolClass, Student, SubjectGrade
from accounts.models import User
from assignments.models import Homework, HomeworkSubmission, Quiz, QuizQuestion, QuizSubmission
from content.models import (
    Accreditation,
    Activity,
    Alumni,
    NewsItem,
    Policy,
    Program,
    SchoolStat,
    SchoolValue,
)
from finance.models import PaymentNotice, StudentFeeBalance
from staff.models import TeacherClassAssignment, TeacherProfile


class Command(BaseCommand):
    help = "مسح كل البيانات وإنشاء حساب المدير فقط"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="مسح البيانات القديمة قبل الإنشاء")

    def handle(self, *args, **options):
        if options["reset"]:
            self._wipe_all()

        if User.objects.filter(username="ismail").exists():
            self.stdout.write(self.style.WARNING("حساب المدير موجود مسبقاً."))
            return

        admin = User.objects.create(
            username="ismail",
            email="ismail@ghazatna.edu.ps",
            first_name="إسماعيل",
            role=User.Role.ADMIN,
            status=User.Status.ACTIVE,
            is_staff=True,
            is_superuser=True,
        )
        admin.set_password("123456")
        admin.save()

        self.stdout.write(self.style.SUCCESS("تم إنشاء حساب المدير بنجاح!"))
        self.stdout.write("  اسم المستخدم: ismail")
        self.stdout.write("  كلمة المرور: 123456")

    def _wipe_all(self):
        self.stdout.write("جاري مسح جميع البيانات...")
        for model in [
            QuizSubmission,
            QuizQuestion,
            Quiz,
            HomeworkSubmission,
            Homework,
            PaymentNotice,
            StudentFeeBalance,
            SubjectGrade,
            ClassGradebook,
            Student,
            TeacherClassAssignment,
            TeacherProfile,
            SchoolClass,
            NewsItem,
            Program,
            Activity,
            Alumni,
            Policy,
            Accreditation,
            SchoolStat,
            SchoolValue,
        ]:
            model.objects.all().delete()
        User.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("تم مسح جميع البيانات."))
