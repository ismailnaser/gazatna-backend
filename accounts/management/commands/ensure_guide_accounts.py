"""Create demo accounts for UI documentation screenshots."""
from django.core.management.base import BaseCommand

from academics.models import AcademicYear, Enrollment, SchoolClass, Student
from accounts.models import User
from accounts.utils import create_auto_user
from staff.models import TeacherClassAssignment, TeacherProfile


class Command(BaseCommand):
    help = "إنشاء حسابات تجريبية لتوليد دليل الواجهات (طالب + معلم)"

    def handle(self, *args, **options):
        school_class, _ = SchoolClass.objects.get_or_create(
            name="الصف الأول - أ",
            defaults={"grade_level": "الصف الأول", "section": "أ"},
        )

        teacher_user, _ = User.objects.get_or_create(
            username="guide_teacher",
            defaults={
                "first_name": "معلم",
                "last_name": "الدليل",
                "email": "guide_teacher@ghazatna.edu.ps",
                "role": User.Role.TEACHER,
                "status": User.Status.ACTIVE,
            },
        )
        teacher_user.set_password("123456")
        teacher_user.save()

        teacher_profile, _ = TeacherProfile.objects.get_or_create(
            user=teacher_user,
            defaults={"name": "أ. محمد الدليل", "bio": "معلم تجريبي لدليل الواجهات"},
        )
        TeacherClassAssignment.objects.get_or_create(
            teacher=teacher_profile,
            school_class=school_class,
        )

        student_number = "2026001"
        student = Student.objects.filter(student_number=student_number).select_related("parent").first()
        if student and student.parent_id:
            login_user = student.parent
        else:
            login_user, _ = create_auto_user(
                name="أحمد محمود الشوا",
                role=User.Role.PARENT,
                username=student_number,
            )
            login_user.set_password("123456")
            login_user.save(update_fields=["password"])
            student, _ = Student.objects.update_or_create(
                student_number=student_number,
                defaults={
                    "name": "أحمد محمود الشوا",
                    "national_id": "400000001",
                    "grade_level": "الصف الأول",
                    "section": "أ",
                    "school_class": school_class,
                    "parent": login_user,
                    "is_active": True,
                },
            )

        active_year = AcademicYear.objects.filter(is_active=True).first()
        if active_year:
            Enrollment.objects.update_or_create(
                student=student,
                academic_year=active_year.name,
                defaults={"school_class": school_class},
            )

        self.stdout.write(self.style.SUCCESS("حسابات دليل الواجهات جاهزة:"))
        self.stdout.write("  مدير: ismail / 123456")
        self.stdout.write("  معلم: guide_teacher / 123456")
        self.stdout.write(f"  طالب تجريبي: {student.student_number} / 123456")
