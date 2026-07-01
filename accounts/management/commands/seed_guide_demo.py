"""
بيانات وهمية غنية لتوليد دليل الواجهات — يملأ الموقع قبل التقاط لقطات الشاشة.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academics.academic_services import set_current_academic_term
from academics.certificate_services import get_or_create_certificate_config, publish_term_certificates
from academics.models import (
    AcademicTerm,
    AcademicYear,
    CertificateConfig,
    ClassSubjectAssignment,
    Enrollment,
    Grade,
    GradeSchemeTemplate,
    SchoolClass,
    Student,
    Subject,
    SubjectGrade,
    SubjectGradeScheme,
    SubjectGradeSchemeEntry,
)
from accounts.models import User
from assignments.models import (
    Homework,
    HomeworkSubmission,
    Quiz,
    QuizQuestion,
    QuizSubmission,
    SubjectAnnouncement,
    SubjectMaterial,
)
from content.models import (
    AdmissionApplication,
    ContactMessage,
    NewsItem,
    Program,
    Schedule,
    SchoolStat,
    SchoolValue,
    SiteSettings,
)
from finance.models import FeeInstallment, FeePlan, PaymentNotice, StudentFeeBalance
from staff.models import TeacherClassAssignment, TeacherProfile

from accounts.management.commands.wipe_data import MODELS_IN_DELETE_ORDER, KEEP_USERNAME

SUBJECT_NAMES = ["رياضيات", "لغة عربية", "علوم", "لغة إنجليزية", "تربية إسلامية"]
GRADE_COMPONENTS = [
    {"id": "cmp-hw", "name": "أعمال فصلية", "maxScore": 30},
    {"id": "cmp-mid", "name": "امتحان منتصف الفصل", "maxScore": 30},
    {"id": "cmp-final", "name": "امتحان نهاية الفصل", "maxScore": 40},
]

ARABIC_STUDENT_NAMES = [
    "أحمد محمود الشوا",
    "سارة خالد الحبشي",
    "يوسف عمر الريس",
    "مريم حسام الجعبري",
    "عبدالله سعيد عوض",
    "ليان محمد بردويل",
    "كريم نادر أبو شنب",
    "نور إبراهيم حمد",
    "تالا رامي السراج",
    "زين ياسر المغني",
]


class Command(BaseCommand):
    help = "ملء الموقع ببيانات وهمية واقعية لتوليد دليل الواجهات (PDF)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="مسح البيانات الحالية (مع الإبقاء على ismail) ثم إعادة البذر",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._wipe()

        with transaction.atomic():
            admin = self._ensure_admin()
            year, term1, term2, archived_year = self._academic_calendar()
            grades, classes = self._grades_and_classes()
            subjects = self._subjects()
            teachers = self._teachers(subjects)
            self._class_subjects(classes, subjects, term2)
            students, _guide_login, guide_student = self._students_and_parents(classes, year)
            self._enrollments(students, classes, year, archived_year)
            self._grade_schemes(teachers, classes, subjects, term2, students)
            self._subject_grades(students, term1, term2)
            self._assignments(teachers, classes, subjects, term2, students, guide_student)
            self._schedules(classes, term2, teachers)
            self._public_content()
            self._admissions_and_messages()
            self._finance(students, guide_student, year, term2, grades)
            self._certificates(admin, year, term1, term2, archived_year, students)
            site = SiteSettings.get()
            site.hero_school_name = "مدرسة غَزتنا"
            site.save()

        self.stdout.write(self.style.SUCCESS("تم ملء البيانات الوهمية بنجاح."))
        self.stdout.write("  مدير: ismail / 123456")
        self.stdout.write("  معلم: guide_teacher / 123456")
        if guide_student:
            self.stdout.write(f"  طالب تجريبي: {guide_student.student_number} / 123456")

    def _wipe(self):
        admin = User.objects.filter(username=KEEP_USERNAME).first()
        if not admin:
            self.stdout.write(self.style.ERROR(f'حساب "{KEEP_USERNAME}" غير موجود.'))
            return
        self.stdout.write("جاري مسح البيانات القديمة...")
        for model in MODELS_IN_DELETE_ORDER:
            model.objects.all().delete()
        User.objects.exclude(username=KEEP_USERNAME).delete()
        self.stdout.write(self.style.SUCCESS("تم المسح."))

    def _ensure_admin(self):
        admin, created = User.objects.get_or_create(
            username="ismail",
            defaults={
                "email": "ismail@ghazatna.edu.ps",
                "first_name": "إسماعيل",
                "role": User.Role.ADMIN,
                "status": User.Status.ACTIVE,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created or not admin.check_password("123456"):
            admin.set_password("123456")
            admin.save()
        return admin

    def _academic_calendar(self):
        today = timezone.localdate()
        year_start = date(today.year - 1, 9, 1)
        year_end = date(today.year + 1, 6, 30)
        year_name = f"{today.year - 1}/{today.year}" if today.month >= 9 else f"{today.year - 1}/{today.year}"

        year, _ = AcademicYear.objects.update_or_create(
            name="2025/2026",
            defaults={
                "start_date": year_start,
                "end_date": year_end,
                "status": AcademicYear.STATUS_ACTIVE,
                "is_active": True,
            },
        )
        AcademicYear.objects.exclude(id=year.id).update(is_active=False, status=AcademicYear.STATUS_ARCHIVED)

        term1_start = year_start
        term1_end = date(today.year, 1, 31) if today.month >= 2 else date(today.year - 1, 1, 31)
        term2_start = term1_end + timedelta(days=1)
        term2_end = min(year_end, today + timedelta(days=90))

        term1, _ = AcademicTerm.objects.update_or_create(
            academic_year=year,
            sort_order=1,
            defaults={
                "name": "الفصل الأول",
                "start_date": term1_start,
                "end_date": term1_end,
                "is_current": False,
                "is_closed": True,
                "closed_at": timezone.now() - timedelta(days=5),
            },
        )
        term2, _ = AcademicTerm.objects.update_or_create(
            academic_year=year,
            sort_order=2,
            defaults={
                "name": "الفصل الثاني",
                "start_date": term2_start,
                "end_date": term2_end,
                "is_current": True,
                "is_closed": False,
                "closed_at": None,
            },
        )
        AcademicTerm.objects.filter(academic_year=year).exclude(id__in=[term1.id, term2.id]).delete()
        set_current_academic_term(term2)

        arch_start = date(today.year - 2, 9, 1)
        arch_end = date(today.year - 1, 6, 30)
        archived_year, _ = AcademicYear.objects.update_or_create(
            name="2024/2025",
            defaults={
                "start_date": arch_start,
                "end_date": arch_end,
                "status": AcademicYear.STATUS_ARCHIVED,
                "is_active": False,
            },
        )
        AcademicTerm.objects.update_or_create(
            academic_year=archived_year,
            sort_order=1,
            defaults={
                "name": "الفصل الأول",
                "start_date": arch_start,
                "end_date": date(arch_start.year + 1, 1, 31),
                "is_current": False,
                "is_closed": True,
                "closed_at": timezone.now() - timedelta(days=120),
            },
        )
        AcademicTerm.objects.update_or_create(
            academic_year=archived_year,
            sort_order=2,
            defaults={
                "name": "الفصل الثاني",
                "start_date": date(arch_start.year + 1, 2, 1),
                "end_date": arch_end,
                "is_current": False,
                "is_closed": True,
                "closed_at": timezone.now() - timedelta(days=90),
            },
        )

        return year, term1, term2, archived_year

    def _grades_and_classes(self):
        g1, _ = Grade.objects.get_or_create(name="الصف الأول", defaults={"sort_order": 1, "sections_count": 2})
        g2, _ = Grade.objects.get_or_create(name="الصف الثاني", defaults={"sort_order": 2, "sections_count": 1})
        c1a, _ = SchoolClass.objects.get_or_create(
            name="الصف الأول - أ",
            defaults={"grade_level": "الصف الأول", "section": "أ"},
        )
        c1b, _ = SchoolClass.objects.get_or_create(
            name="الصف الأول - ب",
            defaults={"grade_level": "الصف الأول", "section": "ب"},
        )
        c2a, _ = SchoolClass.objects.get_or_create(
            name="الصف الثاني - أ",
            defaults={"grade_level": "الصف الثاني", "section": "أ"},
        )
        return [g1, g2], [c1a, c1b, c2a]

    def _subjects(self):
        subjects = []
        for name in SUBJECT_NAMES:
            subj, _ = Subject.objects.get_or_create(name=name)
            subjects.append(subj)
        return subjects

    def _teachers(self, subjects):
        specs = [
            ("guide_teacher", "أ. محمد الدليل", "معلم رياضيات — خبرة 12 سنة في التعليم الابتدائي.", ["رياضيات"]),
            ("teacher_arabic", "أ. فاطمة النجار", "متخصصة في اللغة العربية وآدابها.", ["لغة عربية"]),
            ("teacher_science", "أ. سامي قاسم", "معلم علوم ومسؤول النشاط العلمي.", ["علوم", "لغة إنجليزية"]),
        ]
        teachers = []
        math_subj = next(s for s in subjects if s.name == "رياضيات")
        for username, display_name, bio, subject_names in specs:
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": display_name,
                    "email": f"{username}@ghazatna.edu.ps",
                    "role": User.Role.TEACHER,
                    "status": User.Status.ACTIVE,
                },
            )
            user.set_password("123456")
            user.save()
            profile, _ = TeacherProfile.objects.update_or_create(
                user=user,
                defaults={"name": display_name, "bio": bio, "experience": bio, "is_public": True},
            )
            profile.teaching_subjects.set([s for s in subjects if s.name in subject_names])
            teachers.append(profile)
        return teachers

    def _class_subjects(self, classes, subjects, term):
        for school_class in classes:
            for subject in subjects:
                ClassSubjectAssignment.objects.get_or_create(
                    subject=subject,
                    school_class=school_class,
                    academic_term=term,
                )

    def _students_and_parents(self, classes, year):
        from accounts.utils import create_auto_user

        c1a, c1b, c2a = classes
        class_map = [c1a, c1a, c1a, c1b, c1b, c2a, c2a, c1a, c1b, c2a]

        students = []
        guide_student = None
        guide_login_user = None

        for i, name in enumerate(ARABIC_STUDENT_NAMES):
            school_class = class_map[i]
            student_number = f"2026{i + 1:03d}"
            national_id = f"4{100000000 + i:08d}"[-9:]

            existing = Student.objects.filter(student_number=student_number).first()
            if existing and existing.parent_id:
                login_user = existing.parent
            else:
                login_user, _password = create_auto_user(
                    name=name,
                    role=User.Role.PARENT,
                    username=student_number,
                )
                if name == "أحمد محمود الشوا":
                    login_user.set_password("123456")
                    login_user.save(update_fields=["password"])
                    guide_login_user = login_user

            student, _ = Student.objects.update_or_create(
                student_number=student_number,
                defaults={
                    "name": name,
                    "national_id": national_id,
                    "grade_level": school_class.grade_level,
                    "section": school_class.section,
                    "school_class": school_class,
                    "parent": login_user,
                    "is_active": True,
                },
            )
            students.append(student)
            if name == "أحمد محمود الشوا":
                guide_student = student

        guide_teacher = TeacherProfile.objects.get(user__username="guide_teacher")
        for cls in classes[:2]:
            TeacherClassAssignment.objects.get_or_create(teacher=guide_teacher, school_class=cls)
        arabic_teacher = TeacherProfile.objects.get(user__username="teacher_arabic")
        TeacherClassAssignment.objects.get_or_create(teacher=arabic_teacher, school_class=c1a)

        return students, guide_login_user, guide_student

    def _enrollments(self, students, classes, year, archived_year):
        c1a, c1b, c2a = classes
        for student in students:
            Enrollment.objects.update_or_create(
                student=student,
                academic_year=year.name,
                defaults={"school_class": student.school_class},
            )
            Enrollment.objects.update_or_create(
                student=student,
                academic_year=archived_year.name,
                defaults={"school_class": c1a},
            )

    def _grade_schemes(self, teachers, classes, subjects, term, students):
        GradeSchemeTemplate.objects.update_or_create(
            academic_term=term,
            defaults={"max_score": Decimal("100"), "components": GRADE_COMPONENTS},
        )
        guide_teacher = teachers[0]
        c1a = classes[0]
        for subject_name in ["رياضيات", "لغة عربية"]:
            scheme, _ = SubjectGradeScheme.objects.update_or_create(
                teacher=guide_teacher,
                school_class=c1a,
                subject=subject_name,
                academic_term=term,
                defaults={"max_score": Decimal("100"), "components": GRADE_COMPONENTS},
            )
            for student in [s for s in students if s.school_class_id == c1a.id]:
                scores = {
                    "cmp-hw": float(22 + (student.id % 8)),
                    "cmp-mid": float(24 + (student.id % 6)),
                    "cmp-final": float(30 + (student.id % 10)),
                }
                SubjectGradeSchemeEntry.objects.update_or_create(
                    scheme=scheme,
                    student=student,
                    defaults={"scores": scores},
                )

    def _subject_grades(self, students, term1, term2):
        for student in students:
            for term in [term1, term2]:
                for j, subject_name in enumerate(SUBJECT_NAMES):
                    base = 70 + ((student.id + j) % 25)
                    SubjectGrade.objects.update_or_create(
                        student=student,
                        subject=subject_name,
                        academic_term=term,
                        defaults={
                            "score": Decimal(str(base)),
                            "max_score": Decimal("100"),
                            "term": term.name,
                        },
                    )

    def _assignments(self, teachers, classes, subjects, term, students, guide_student):
        guide_teacher = teachers[0]
        c1a = classes[0]
        now = timezone.now()
        class_students = [s for s in students if s.school_class_id == c1a.id]

        hw1, _ = Homework.objects.update_or_create(
            title="واجب الجمع والطرح — الفصل الثالث",
            school_class=c1a,
            teacher=guide_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "حل تمارين صفحة 45 و46 من الكتاب المدرسي. اكتب خطوات الحل بوضوح.",
                "due_date": (now + timedelta(days=5)).date(),
                "max_score": Decimal("20"),
                "grades_visible": True,
                "academic_term": term,
            },
        )
        hw2, _ = Homework.objects.update_or_create(
            title="قراءة قصة «النخلة الطيبة»",
            school_class=c1a,
            teacher=teachers[1],
            defaults={
                "subject": "لغة عربية",
                "description": "اقرأ القصة في الكتاب صفحة 28-32 ثم أجب عن الأسئلة الثلاثة في نهاية القصة.",
                "due_date": (now + timedelta(days=3)).date(),
                "academic_term": term,
            },
        )
        Homework.objects.update_or_create(
            title="تقرير عن دورة الماء في الطبيعة",
            school_class=c1a,
            teacher=teachers[2],
            defaults={
                "subject": "علوم",
                "description": "اكتب تقريراً من 10 أسطر يشرح دورة الماء مع رسم توضيحي.",
                "due_date": (now + timedelta(days=7)).date(),
                "academic_term": term,
            },
        )

        if guide_student:
            HomeworkSubmission.objects.update_or_create(
                homework=hw1,
                student=guide_student,
                defaults={
                    "content": "تم حل جميع التمارين — مرفق صورة الحل.",
                    "score": Decimal("18"),
                    "max_score": Decimal("20"),
                    "teacher_note": "عمل ممتاز، انتبه لترتيب الخطوات في السؤال الرابع.",
                    "graded_at": now,
                },
            )

        quiz, _ = Quiz.objects.update_or_create(
            title="اختبار قصير — جدول الضرب",
            school_class=c1a,
            teacher=guide_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "اختبار قصير لمدة 20 دقيقة يغطي جدول الضرب من 1 إلى 10.",
                "due_date": (now + timedelta(days=2)).date(),
                "start_at": now - timedelta(hours=2),
                "end_at": now + timedelta(days=2),
                "duration_minutes": 20,
                "grades_visible": True,
                "review_allowed": True,
                "max_score": Decimal("10"),
                "academic_term": term,
            },
        )
        if not quiz.questions.exists():
            QuizQuestion.objects.create(
                quiz=quiz,
                prompt="كم يساوي 7 × 8؟",
                question_type="choice",
                options=["48", "54", "56", "63"],
                correct_index=2,
                points=Decimal("5"),
                order=1,
            )
            QuizQuestion.objects.create(
                quiz=quiz,
                prompt="الضرب عملية إبدالية (تبديلية).",
                question_type="true_false",
                options=["صح", "خطأ"],
                correct_index=0,
                points=Decimal("5"),
                order=2,
            )
        quiz.max_score = Decimal("10")
        quiz.save(update_fields=["max_score"])

        if guide_student:
            QuizSubmission.objects.update_or_create(
                quiz=quiz,
                student=guide_student,
                attempt_number=1,
                defaults={
                    "answers": [{"questionId": quiz.questions.first().id, "selectedIndex": 2}],
                    "auto_score": Decimal("10"),
                    "score": Decimal("10"),
                    "max_score": Decimal("10"),
                    "graded_at": now,
                },
            )

        SubjectAnnouncement.objects.update_or_create(
            title="تذكير: اختبار الرياضيات يوم الأربعاء",
            school_class=c1a,
            teacher=guide_teacher,
            defaults={
                "subject": "رياضيات",
                "body": "يرجى من الطلاب مراجعة جدول الضرب والقسمة استعداداً للاختبار القصير يوم الأربعاء.",
                "academic_term": term,
            },
        )
        SubjectAnnouncement.objects.update_or_create(
            title="رحلة علمية إلى حديقة المدرسة",
            school_class=c1a,
            teacher=teachers[2],
            defaults={
                "subject": "علوم",
                "body": "سيتم تنظيم نشاط علمي يوم الخميس لمشاهدة النباتات وتصنيفها.",
                "academic_term": term,
            },
        )

        mat, _ = SubjectMaterial.objects.update_or_create(
            title="كتاب الرياضيات — الفصل الثالث",
            school_class=c1a,
            teacher=guide_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "ملخص الفصل الثالث: الجمع والطرح والضرب.",
                "category": "slides",
                "academic_term": term,
            },
        )
        SubjectMaterial.objects.update_or_create(
            title="قواعد النحو — المبتدأ والخبر",
            school_class=c1a,
            teacher=teachers[1],
            defaults={
                "subject": "لغة عربية",
                "description": "عرض تقديمي يشرح المبتدأ والخبر مع أمثلة.",
                "category": "slides",
                "academic_term": term,
            },
        )

    def _schedules(self, classes, term, teachers):
        entries = [
            {"day": "السبت", "time": "08:00", "duration": 45, "subject": "رياضيات", "teacher": "أ. محمد الدليل", "period": "1"},
            {"day": "السبت", "time": "08:50", "duration": 45, "subject": "لغة عربية", "teacher": "أ. فاطمة النجار", "period": "2"},
            {"day": "السبت", "time": "09:40", "duration": 45, "subject": "علوم", "teacher": "أ. سامي قاسم", "period": "3"},
            {"day": "الأحد", "time": "08:00", "duration": 45, "subject": "لغة إنجليزية", "teacher": "أ. سامي قاسم", "period": "1"},
            {"day": "الأحد", "time": "08:50", "duration": 45, "subject": "تربية إسلامية", "teacher": "أ. فاطمة النجار", "period": "2"},
            {"day": "الأحد", "time": "09:40", "duration": 45, "subject": "رياضيات", "teacher": "أ. محمد الدليل", "period": "3"},
            {"day": "الاثنين", "time": "08:00", "duration": 45, "subject": "علوم", "teacher": "أ. سامي قاسم", "period": "1"},
            {"day": "الاثنين", "time": "08:50", "duration": 45, "subject": "لغة عربية", "teacher": "أ. فاطمة النجار", "period": "2"},
            {"day": "الثلاثاء", "time": "08:00", "duration": 45, "subject": "رياضيات", "teacher": "أ. محمد الدليل", "period": "1"},
            {"day": "الأربعاء", "time": "08:00", "duration": 45, "subject": "لغة عربية", "teacher": "أ. فاطمة النجار", "period": "1"},
            {"day": "الخميس", "time": "08:00", "duration": 45, "subject": "تربية إسلامية", "teacher": "أ. فاطمة النجار", "period": "1"},
        ]
        for school_class in classes:
            schedule, _ = Schedule.objects.update_or_create(
                name=f"جدول حصص {school_class.name}",
                schedule_type="class",
                academic_term=term,
                defaults={"entries": entries, "is_published": True},
            )
            schedule.school_classes.set([school_class])

    def _public_content(self):
        news_items = [
            ("افتتاح معمل الحاسوب الجديد", "أخبار", "تم افتتاح معمل حاسوب مجهّز بأحدث الأجهزة لطلاب المرحلة الابتدائية."),
            ("يوم التطوع المدرسي", "فعاليات", "شارك طلاب الصفوف العليا في حملة تجميل ساحة المدرسة وتشجير الحديقة."),
            ("فوز فريق الروبوتيك", "إنجازات", "حقق فريق غَزتنا للروبوتيك المركز الأول في المسابقة المحلية."),
            ("ورشة القراءة الإبداعية", "فعاليات", "ورشة أسبوعية لتعزيز مهارات القراءة والكتابة لدى طلاب الصف الثاني."),
        ]
        for i, (title, category, desc) in enumerate(news_items):
            NewsItem.objects.update_or_create(
                title=title,
                defaults={
                    "description": desc,
                    "body": f"{desc}\n\nتفاصيل إضافية: نشاط مدرسي ضمن برنامج غَزتنا التعليمي.",
                    "date": timezone.localdate() - timedelta(days=i * 4),
                    "category": category,
                    "featured": i == 0,
                    "is_published": True,
                },
            )

        programs = [
            ("المرحلة الابتدائية", "الصفوف 1-4", "تعليم أساسي متكامل يجمع بين المهارات الأكاديمية والقيم."),
            ("التميز في الرياضيات", "جميع المراحل", "برنامج تعزيزي لطلاب الرياضيات المتميزين."),
            ("اللغة والإبداع", "ابتدائي", "تنمية مهارات القراءة والكتابة والتعبير."),
        ]
        for i, (title, grades, desc) in enumerate(programs):
            Program.objects.update_or_create(
                title=title,
                defaults={
                    "grades": grades,
                    "description": desc,
                    "features": ["معلمون متخصصون", "أنشطة تفاعلية", "متابعة أولياء الأمور"],
                    "order": i,
                },
            )

        stats = [
            ("students", "طلاب مسجّلون", "320", "Users"),
            ("teachers", "معلمون", "28", "GraduationCap"),
            ("programs", "برامج تعليمية", "12", "BookOpen"),
            ("years", "سنوات خبرة", "15", "Award"),
        ]
        for key, label, value, icon in stats:
            SchoolStat.objects.update_or_create(
                key=key,
                defaults={"label": label, "value": value, "icon_name": icon, "order": len(stats)},
            )

        values = [
            ("الانتماء", "نغرس قيمة الانتماء للوطن والمجتمع في قلوب طلابنا."),
            ("الإبداع", "نشجّع التفكير الإبداعي وحل المشكلات."),
            ("التميز", "نسعى للتميز الأكاديمي مع مراعاة الفروق الفردية."),
        ]
        for i, (title, desc) in enumerate(values):
            SchoolValue.objects.update_or_create(
                title=title,
                defaults={"description": desc, "number": f"0{i + 1}", "order": i},
            )

    def _admissions_and_messages(self):
        apps = [
            ("لينا أحمد برهوم", "الصف الأول", "أحمد برهوم", "0599123456"),
            ("عمر سمير دغمش", "الصف الثاني", "سمير دغمش", "0598765432"),
            ("رغد محمد عياش", "الصف الأول", "محمد عياش", "0598111222"),
        ]
        for student_name, grade, parent_name, phone in apps:
            AdmissionApplication.objects.update_or_create(
                student_name=student_name,
                parent_name=parent_name,
                defaults={
                    "grade": grade,
                    "phone": phone,
                    "email": f"{parent_name.replace(' ', '.')}@example.com",
                    "notes": "طلب تسجيل جديد من الموقع العام.",
                    "status": "pending",
                },
            )

        messages = [
            ("سعاد محمود", "استفسار عن الرسوم", "أود معرفة جدول الأقساط للصف الأول."),
            ("إياد خليل", "موعد مقابلة", "هل يمكن تحديد موعد لمقابلة إدارية؟"),
        ]
        for name, subject, body in messages:
            ContactMessage.objects.update_or_create(
                name=name,
                message=body,
                defaults={"phone": "0599000000", "email": "visitor@example.com", "status": "new"},
            )

    def _finance(self, students, guide_student, year, term, grades):
        plan, _ = FeePlan.objects.update_or_create(
            name="رسوم الصف الابتدائي 2025/2026",
            defaults={
                "total_amount": Decimal("2400"),
                "installments_count": 3,
                "billing_period": FeePlan.BILLING_FULL_YEAR,
                "academic_year": year,
                "is_active": True,
            },
        )
        plan.grades.set(grades[:1])
        installments = [
            (1, Decimal("800"), timezone.localdate() - timedelta(days=60), timezone.localdate() - timedelta(days=30)),
            (2, Decimal("800"), timezone.localdate() - timedelta(days=29), timezone.localdate() + timedelta(days=30)),
            (3, Decimal("800"), timezone.localdate() + timedelta(days=31), timezone.localdate() + timedelta(days=90)),
        ]
        for order, amount, start, end in installments:
            FeeInstallment.objects.update_or_create(
                fee_plan=plan,
                order=order,
                defaults={"amount": amount, "start_date": start, "end_date": end},
            )

        if guide_student:
            StudentFeeBalance.objects.update_or_create(
                student=guide_student,
                defaults={"fee_plan": plan, "total": Decimal("2400"), "paid": Decimal("1600")},
            )
            PaymentNotice.objects.update_or_create(
                student=guide_student,
                amount=Decimal("800"),
                date=timezone.localdate() - timedelta(days=10),
                defaults={
                    "declared_amount": Decimal("800"),
                    "status": "approved",
                    "note": "دفعة القسط الثاني — تم الاستلام.",
                },
            )

    def _certificates(self, admin, year, term1, term2, archived_year, students):
        publish_term_certificates(year, admin, term_id=str(term2.id))
        config = get_or_create_certificate_config(year)
        config.is_term_published = True
        config.published_term = term2
        config.term_published_at = timezone.now()
        config.save()

        arch_config, _ = CertificateConfig.objects.update_or_create(
            academic_year=archived_year,
            defaults={
                "is_term_published": True,
                "is_published": True,
                "term_published_at": timezone.now() - timedelta(days=100),
                "published_at": timezone.now() - timedelta(days=100),
            },
        )
        arch_term = archived_year.terms.order_by("-sort_order").first()
        if arch_term:
            arch_config.published_term = arch_term

        arch_config.save()
