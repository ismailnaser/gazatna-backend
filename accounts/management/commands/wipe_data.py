from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import (
    AcademicTerm,
    AcademicYear,
    CertificateConfig,
    ClassGradebook,
    ClassSubjectAssignment,
    Enrollment,
    Grade,
    GradeSchemeTemplate,
    ParentDismissedAlert,
    PromotionPolicy,
    SchoolClass,
    Student,
    StudentDocument,
    Subject,
    SubjectGrade,
    SubjectGradeScheme,
    SubjectGradeSchemeEntry,
    YearEndPromotionRun,
)
from accounts.models import User
from assignments.models import (
    Homework,
    HomeworkAttachment,
    HomeworkSubmission,
    Quiz,
    QuizAnswerAttachment,
    QuizQuestion,
    QuizSubmission,
    SubjectAnnouncement,
    SubjectMaterial,
    SubjectMaterialFile,
)
from content.models import (
    AdmissionApplication,
    ContactMessage,
    NewsImage,
    NewsItem,
    Program,
    Schedule,
    SchoolStat,
    SchoolValue,
)
from finance.models import FeeInstallment, FeePlan, PaymentNotice, StudentFeeBalance
from staff.models import TeacherClassAssignment, TeacherProfile, TeacherReadAlert

KEEP_USERNAME = "ismail"

MODELS_IN_DELETE_ORDER = [
    QuizAnswerAttachment,
    QuizSubmission,
    QuizQuestion,
    Quiz,
    HomeworkSubmission,
    HomeworkAttachment,
    Homework,
    SubjectMaterialFile,
    SubjectMaterial,
    SubjectAnnouncement,
    PaymentNotice,
    StudentFeeBalance,
    FeeInstallment,
    FeePlan,
    SubjectGradeSchemeEntry,
    SubjectGradeScheme,
    GradeSchemeTemplate,
    SubjectGrade,
    ClassGradebook,
    ParentDismissedAlert,
    StudentDocument,
    Enrollment,
    YearEndPromotionRun,
    CertificateConfig,
    PromotionPolicy,
    AcademicTerm,
    AcademicYear,
    Student,
    ClassSubjectAssignment,
    Schedule,
    SchoolClass,
    Subject,
    Grade,
    TeacherReadAlert,
    TeacherClassAssignment,
    TeacherProfile,
    NewsImage,
    NewsItem,
    Program,
    SchoolStat,
    SchoolValue,
    AdmissionApplication,
    ContactMessage,
]


class Command(BaseCommand):
    help = "مسح كل بيانات الموقع مع الإبقاء على حساب المدير ismail"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="تأكيد التنفيذ بدون سؤال",
        )

    def handle(self, *args, **options):
        admin = User.objects.filter(username=KEEP_USERNAME).first()
        if not admin:
            self.stdout.write(
                self.style.ERROR(f'حساب "{KEEP_USERNAME}" غير موجود. أوقف العملية.')
            )
            return

        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    f'سيتم مسح كل البيانات مع الإبقاء على حساب "{KEEP_USERNAME}" فقط.'
                )
            )
            self.stdout.write('نفّذ مع --yes للتأكيد.')

        with transaction.atomic():
            total_deleted = 0
            for model in MODELS_IN_DELETE_ORDER:
                count, _ = model.objects.all().delete()
                if count:
                    self.stdout.write(f"  حذف {count:>4} سجل من {model._meta.label}")
                    total_deleted += count

            users_deleted, _ = User.objects.exclude(username=KEEP_USERNAME).delete()
            if users_deleted:
                self.stdout.write(f"  حذف {users_deleted:>4} مستخدم")
                total_deleted += users_deleted

        self.stdout.write(
            self.style.SUCCESS(
                f"تم المسح بنجاح ({total_deleted} سجل). "
                f'حساب المدير المحفوظ: {admin.username} ({admin.display_name})'
            )
        )
