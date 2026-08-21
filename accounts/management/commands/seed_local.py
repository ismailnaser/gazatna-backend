"""
بيانات تجريبية كاملة لكل جداول المشروع — للتجربة على اللوكل.

الاستخدام:
    python manage.py seed_local
    python manage.py seed_local --reset
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
    ClassGradebook,
    ClassSubjectAssignment,
    Enrollment,
    Grade,
    GradeSchemeTemplate,
    ParentDismissedAlert,
    ParentGradesSeenState,
    PromotionPolicy,
    SchoolClass,
    Student,
    Subject,
    SubjectGrade,
    SubjectGradeScheme,
    SubjectGradeSchemeEntry,
    YearEndPromotionRun,
)
from accounts.models import User
from accounts.utils import create_auto_user
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
from finance.services import apply_plan_to_students
from staff.models import StaffType, TeacherClassAssignment, TeacherProfile, TeacherReadAlert

from accounts.management.commands.wipe_data import MODELS_IN_DELETE_ORDER, KEEP_USERNAME

DEMO_PASSWORD = "123456"

SUBJECT_NAMES = [
    "رياضيات",
    "لغة عربية",
    "علوم",
    "لغة إنجليزية",
    "تربية إسلامية",
    "دراسات اجتماعية",
]

GRADE_COMPONENTS = [
    {"id": "cmp-hw", "name": "أعمال فصلية", "maxScore": 30},
    {"id": "cmp-mid", "name": "امتحان منتصف الفصل", "maxScore": 30},
    {"id": "cmp-final", "name": "امتحان نهاية الفصل", "maxScore": 40},
]

STUDENT_SPECS = [
    ("أحمد محمود الشوا", "الصف الأول", "أ", "غزة — الرمال"),
    ("سارة خالد الحبشي", "الصف الأول", "أ", "غزة — التل الهوا"),
    ("يوسف عمر الريس", "الصف الأول", "أ", "غزة — النصر"),
    ("مريم حسام الجعبري", "الصف الأول", "ب", "غزة — الشجاعية"),
    ("عبدالله سعيد عوض", "الصف الأول", "ب", "غزة — الزيتون"),
    ("ليان محمد بردويل", "الصف الأول", "ب", "غزة — الصبرة"),
    ("كريم نادر أبو شنب", "الصف الثاني", "أ", "غزة — الرمال"),
    ("نور إبراهيم حمد", "الصف الثاني", "أ", "غزة — النصر"),
    ("تالا رامي السراج", "الصف الثاني", "أ", "غزة — الشيخ رضوان"),
    ("زين ياسر المغني", "الصف الثاني", "ب", "غزة — التفاح"),
    ("هدى سامي المصري", "الصف الثاني", "ب", "غزة — الدرج"),
    ("مالك فادي الغول", "الصف الثاني", "ب", "غزة — الشاطئ"),
    ("جنى وائل أبو العوف", "الصف الثالث", "أ", "غزة — تل الهوا"),
    ("رامي نبيل المصري", "الصف الثالث", "أ", "غزة — الزيتون"),
    ("سلام علاء جودة", "الصف الثالث", "أ", "غزة — الرمال"),
    ("بيان كمال عاشور", "الصف الثالث", "ب", "غزة — النصر"),
    ("إياد حسن النجار", "الصف الثالث", "ب", "غزة — الشجاعية"),
    ("لينا وليد برهوم", "الصف الثالث", "ب", "غزة — الصبرة"),
]

TEACHER_SPECS = [
    ("guide_teacher", "أ. محمد الدليل", "Mohammed Al-Daleel", ["رياضيات"], "male", "married"),
    ("teacher_arabic", "أ. فاطمة النجار", "Fatima Al-Najjar", ["لغة عربية"], "female", "married"),
    ("teacher_science", "أ. سامي قاسم", "Sami Qasem", ["علوم"], "male", "married"),
    ("teacher_english", "أ. هالة بركات", "Hala Barakat", ["لغة إنجليزية"], "female", "single"),
    ("teacher_islamic", "أ. محمود أبو خاطر", "Mahmoud Abu Khater", ["تربية إسلامية"], "male", "married"),
    ("teacher_social", "أ. رنا المصري", "Rana Al-Masri", ["دراسات اجتماعية"], "female", "married"),
]


class Command(BaseCommand):
    help = "ملء كل جداول المشروع ببيانات تجريبية للتجربة على اللوكل"

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
            self._role_admins()
            year, term1, term2, archived_year = self._academic_calendar()
            grades, classes = self._grades_and_classes()
            subjects = self._subjects()
            teachers, _staff_members = self._staff(subjects, classes)
            self._class_subjects(classes, subjects, term1)
            students, guide_student = self._students(classes, year, archived_year)
            self._grade_schemes(teachers, classes, subjects, term1, students)
            self._subject_grades(students, term1, term2)
            self._gradebooks(students, classes, teachers)
            self._assignments(teachers, classes, term1, students, guide_student)
            self._schedules(classes, term1, teachers)
            self._public_content(grades)
            self._admissions(admin)
            self._finance(students, guide_student, year, grades)
            self._certificates(admin, year, term1, archived_year)
            self._promotions(admin, grades, year, archived_year, students)
            self._alerts(teachers, guide_student)

        self._print_logins(guide_student)

    def _wipe(self):
        self.stdout.write("جاري مسح البيانات القديمة...")
        for model in MODELS_IN_DELETE_ORDER:
            model.objects.all().delete()
        User.objects.exclude(username=KEEP_USERNAME).delete()
        self.stdout.write(self.style.SUCCESS("تم المسح."))

    def _set_password(self, user):
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
        return user

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
        if created or not admin.check_password(DEMO_PASSWORD):
            self._set_password(admin)
        return admin

    def _role_admins(self):
        specs = [
            ("admin_students", "نادية أبو العوف", User.Role.ADMIN_STUDENTS),
            ("admin_academics", "خليل المصري", User.Role.ADMIN_ACADEMICS),
            ("admin_finance", "سمر الغول", User.Role.ADMIN_FINANCE),
            ("admin_content", "باسم جودة", User.Role.ADMIN_CONTENT),
            ("admin_staff", "ليلى برهوم", User.Role.ADMIN_STAFF),
        ]
        for username, name, role in specs:
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": name,
                    "email": f"{username}@ghazatna.edu.ps",
                    "role": role,
                    "status": User.Status.ACTIVE,
                    "is_staff": True,
                },
            )
            self._set_password(user)

    def _academic_calendar(self):
        # أغسطس 2026: نجعل السنة 2026/2027 بدأت لتكون التجربة كاملة (واجبات، رسوم، فصل حالي).
        year, _ = AcademicYear.objects.update_or_create(
            name="2026/2027",
            defaults={
                "start_date": date(2026, 8, 1),
                "end_date": date(2027, 6, 30),
                "status": AcademicYear.STATUS_ACTIVE,
                "is_active": True,
            },
        )
        AcademicYear.objects.exclude(id=year.id).update(
            is_active=False, status=AcademicYear.STATUS_ARCHIVED
        )

        term1, _ = AcademicTerm.objects.update_or_create(
            academic_year=year,
            sort_order=1,
            defaults={
                "name": "الفصل الأول",
                "start_date": date(2026, 8, 1),
                "end_date": date(2027, 1, 31),
                "is_current": True,
                "is_closed": False,
                "closed_at": None,
            },
        )
        term2, _ = AcademicTerm.objects.update_or_create(
            academic_year=year,
            sort_order=2,
            defaults={
                "name": "الفصل الثاني",
                "start_date": date(2027, 2, 1),
                "end_date": date(2027, 6, 30),
                "is_current": False,
                "is_closed": False,
                "closed_at": None,
            },
        )
        set_current_academic_term(term1)

        archived_year, _ = AcademicYear.objects.update_or_create(
            name="2025/2026",
            defaults={
                "start_date": date(2025, 9, 1),
                "end_date": date(2026, 6, 30),
                "status": AcademicYear.STATUS_ARCHIVED,
                "is_active": False,
            },
        )
        AcademicTerm.objects.update_or_create(
            academic_year=archived_year,
            sort_order=1,
            defaults={
                "name": "الفصل الأول",
                "start_date": date(2025, 9, 1),
                "end_date": date(2026, 1, 31),
                "is_current": False,
                "is_closed": True,
                "closed_at": timezone.now() - timedelta(days=200),
            },
        )
        AcademicTerm.objects.update_or_create(
            academic_year=archived_year,
            sort_order=2,
            defaults={
                "name": "الفصل الثاني",
                "start_date": date(2026, 2, 1),
                "end_date": date(2026, 6, 30),
                "is_current": False,
                "is_closed": True,
                "closed_at": timezone.now() - timedelta(days=50),
            },
        )
        return year, term1, term2, archived_year

    def _grades_and_classes(self):
        grade_defs = [
            ("الصف الأول", 1, 2),
            ("الصف الثاني", 2, 2),
            ("الصف الثالث", 3, 2),
        ]
        grades = []
        classes = []
        for name, order, sections in grade_defs:
            grade, _ = Grade.objects.update_or_create(
                name=name,
                defaults={"sort_order": order, "sections_count": sections},
            )
            grades.append(grade)
            for section in ["أ", "ب"][:sections]:
                school_class, _ = SchoolClass.objects.update_or_create(
                    name=f"{name} - {section}",
                    defaults={"grade_level": name, "section": section},
                )
                classes.append(school_class)
        return grades, classes

    def _subjects(self):
        subjects = []
        for name in SUBJECT_NAMES:
            subj, _ = Subject.objects.get_or_create(name=name)
            subjects.append(subj)
        return subjects

    def _staff(self, subjects, classes):
        teacher_type, _ = StaffType.objects.get_or_create(
            name="معلم", defaults={"is_teacher": True, "sort_order": 1}
        )
        for name, is_teacher, sort_order in [
            ("مدير", False, 2),
            ("نائب مدير", False, 3),
            ("سكرتير", False, 4),
            ("محاسب", False, 5),
            ("مراقب", False, 6),
        ]:
            StaffType.objects.get_or_create(
                name=name, defaults={"is_teacher": is_teacher, "sort_order": sort_order}
            )

        teachers = []
        by_subject = {s.name: s for s in subjects}
        for i, (username, display_name, name_en, subject_names, gender, marital) in enumerate(TEACHER_SPECS):
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": display_name,
                    "email": f"{username}@ghazatna.edu.ps",
                    "role": User.Role.TEACHER,
                    "status": User.Status.ACTIVE,
                },
            )
            self._set_password(user)
            profile, _ = TeacherProfile.objects.update_or_create(
                user=user,
                defaults={
                    "staff_type": teacher_type,
                    "name": display_name,
                    "name_en": name_en,
                    "national_id": f"{900000001 + i:09d}",
                    "date_of_birth": date(1985 + i, 3, 10 + i),
                    "gender": gender,
                    "marital_status": marital,
                    "mobile": f"0599{100100 + i:06d}"[:10],
                    "alt_mobile": f"0569{200200 + i:06d}"[:10],
                    "address": "غزة — الرمال",
                    "join_date": date(2018 + (i % 5), 9, 1),
                    "bio": f"{display_name} — معلم/ة {subject_names[0]} في مدرسة غَزتنا.",
                    "experience": f"خبرة {8 + i} سنوات في التعليم الأساسي.",
                    "is_public": True,
                },
            )
            profile.teaching_subjects.set([by_subject[n] for n in subject_names if n in by_subject])
            teachers.append(profile)

        for cls, teacher in zip(classes, teachers):
            cls.homeroom_teacher = teacher
            cls.save(update_fields=["homeroom_teacher"])

        for teacher in teachers:
            for school_class in classes:
                TeacherClassAssignment.objects.get_or_create(teacher=teacher, school_class=school_class)

        secretary_type = StaffType.objects.get(name="سكرتير")
        accountant_type = StaffType.objects.get(name="محاسب")
        supervisor_type = StaffType.objects.get(name="مراقب")
        non_teachers = [
            ("أ. هناء شعث", "Hanaa Shaath", secretary_type, "900000101"),
            ("أ. وليد العجلة", "Walid Al-Ajla", accountant_type, "900000102"),
            ("أ. فؤاد حجازي", "Fouad Hijazi", supervisor_type, "900000103"),
        ]
        staff_members = []
        for name, name_en, staff_type, nid in non_teachers:
            member, _ = TeacherProfile.objects.update_or_create(
                national_id=nid,
                defaults={
                    "user": None,
                    "staff_type": staff_type,
                    "name": name,
                    "name_en": name_en,
                    "date_of_birth": date(1988, 5, 12),
                    "gender": "male" if "وليد" in name or "فؤاد" in name else "female",
                    "marital_status": "married",
                    "mobile": "0599111222",
                    "address": "غزة",
                    "join_date": date(2020, 9, 1),
                    "is_public": False,
                    "bio": "",
                    "experience": "",
                },
            )
            staff_members.append(member)
        return teachers, staff_members

    def _class_subjects(self, classes, subjects, term):
        for school_class in classes:
            for subject in subjects:
                ClassSubjectAssignment.objects.get_or_create(
                    subject=subject,
                    school_class=school_class,
                    academic_term=term,
                )

    def _students(self, classes, year, archived_year):
        class_by_key = {(c.grade_level, c.section): c for c in classes}
        students = []
        guide_student = None

        for i, (name, grade_level, section, address) in enumerate(STUDENT_SPECS):
            school_class = class_by_key[(grade_level, section)]
            student_number = f"2026{i + 1:03d}"
            national_id = f"{400000001 + i:09d}"
            phone = f"0598{200001 + i:06d}"[:10]

            existing = Student.objects.filter(student_number=student_number).select_related("parent").first()
            if existing and existing.parent_id:
                login_user = existing.parent
            else:
                login_user, _ = create_auto_user(
                    name=name,
                    role=User.Role.PARENT,
                    username=student_number,
                )
                self._set_password(login_user)

            student, _ = Student.objects.update_or_create(
                student_number=student_number,
                defaults={
                    "name": name,
                    "national_id": national_id,
                    "parent_phone": phone,
                    "address": address,
                    "evaluation": "طالب مجتهد ومتعاون." if i % 3 == 0 else "يحتاج متابعة في بعض المواد." if i % 3 == 1 else "",
                    "grade_level": grade_level,
                    "section": section,
                    "school_class": school_class,
                    "parent": login_user,
                    "is_active": i != 17,
                    "documents": [],
                },
            )
            Enrollment.objects.update_or_create(
                student=student,
                school_class=school_class,
                academic_year=year.name,
            )
            first_class = class_by_key[("الصف الأول", "أ")]
            Enrollment.objects.update_or_create(
                student=student,
                school_class=first_class if grade_level != "الصف الأول" else school_class,
                academic_year=archived_year.name,
            )
            students.append(student)
            if name == "أحمد محمود الشوا":
                guide_student = student

        return students, guide_student

    def _grade_schemes(self, teachers, classes, subjects, term, students):
        GradeSchemeTemplate.objects.update_or_create(
            academic_term=term,
            defaults={"max_score": Decimal("100"), "components": GRADE_COMPONENTS},
        )
        teacher_by_subject = {}
        for teacher in teachers:
            for subject in teacher.teaching_subjects.all():
                teacher_by_subject[subject.name] = teacher

        for school_class in classes:
            class_students = [s for s in students if s.school_class_id == school_class.id]
            for subject in subjects:
                teacher = teacher_by_subject.get(subject.name)
                if not teacher:
                    continue
                scheme, _ = SubjectGradeScheme.objects.update_or_create(
                    teacher=teacher,
                    school_class=school_class,
                    subject=subject.name,
                    academic_term=term,
                    defaults={"max_score": Decimal("100"), "components": GRADE_COMPONENTS},
                )
                for student in class_students:
                    seed = (student.id + subject.id) % 8
                    SubjectGradeSchemeEntry.objects.update_or_create(
                        scheme=scheme,
                        student=student,
                        defaults={
                            "scores": {
                                "cmp-hw": float(20 + seed),
                                "cmp-mid": float(22 + (seed % 7)),
                                "cmp-final": float(28 + (seed % 10)),
                            }
                        },
                    )

    def _subject_grades(self, students, term1, term2):
        for student in students:
            for j, subject_name in enumerate(SUBJECT_NAMES):
                base = 68 + ((student.id + j) % 28)
                SubjectGrade.objects.update_or_create(
                    student=student,
                    subject=subject_name,
                    academic_term=term1,
                    defaults={
                        "score": Decimal(str(base)),
                        "max_score": Decimal("100"),
                        "term": term1.name,
                        "note": "أداء جيد" if base >= 80 else "",
                    },
                )

    def _gradebooks(self, students, classes, teachers):
        math_teacher = teachers[0]
        for student in students:
            if not student.school_class_id:
                continue
            ClassGradebook.objects.update_or_create(
                student=student,
                school_class=student.school_class,
                defaults={
                    "score": Decimal(str(70 + (student.id % 25))),
                    "note": "متابعة مستمرة",
                    "teacher": math_teacher,
                },
            )

    def _assignments(self, teachers, classes, term, students, guide_student):
        now = timezone.now()
        math_teacher, arabic_teacher, science_teacher = teachers[0], teachers[1], teachers[2]
        c1a = next(c for c in classes if c.grade_level == "الصف الأول" and c.section == "أ")
        c2a = next(c for c in classes if c.grade_level == "الصف الثاني" and c.section == "أ")
        class_students = [s for s in students if s.school_class_id == c1a.id]

        hw1, _ = Homework.objects.update_or_create(
            title="واجب الجمع والطرح — الوحدة الثالثة",
            school_class=c1a,
            teacher=math_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "حل تمارين صفحة 45 و46 من الكتاب المدرسي. اكتب خطوات الحل بوضوح.",
                "due_date": (now + timedelta(days=5)).date(),
                "start_at": now - timedelta(days=2),
                "end_at": now + timedelta(days=5),
                "max_score": Decimal("20"),
                "grades_visible": True,
                "academic_term": term,
            },
        )
        hw2, _ = Homework.objects.update_or_create(
            title="قراءة قصة «النخلة الطيبة»",
            school_class=c1a,
            teacher=arabic_teacher,
            defaults={
                "subject": "لغة عربية",
                "description": "اقرأ القصة ثم أجب عن الأسئلة الثلاثة في نهايتها.",
                "due_date": (now + timedelta(days=3)).date(),
                "max_score": Decimal("15"),
                "grades_visible": False,
                "academic_term": term,
            },
        )
        Homework.objects.update_or_create(
            title="تقرير دورة الماء في الطبيعة",
            school_class=c1a,
            teacher=science_teacher,
            defaults={
                "subject": "علوم",
                "description": "اكتب تقريراً من 10 أسطر مع رسم توضيحي.",
                "due_date": (now + timedelta(days=7)).date(),
                "academic_term": term,
            },
        )
        Homework.objects.update_or_create(
            title="مسائل الضرب للصف الثاني",
            school_class=c2a,
            teacher=math_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "حل تمارين الضرب من 2 إلى 9.",
                "due_date": (now + timedelta(days=4)).date(),
                "academic_term": term,
            },
        )

        notes = ["عمل ممتاز.", "جيد، راجع الترتيب.", "يحتاج إعادة بعض الأسئلة."]
        for idx, student in enumerate(class_students[:4]):
            HomeworkSubmission.objects.update_or_create(
                homework=hw1,
                student=student,
                defaults={
                    "content": f"تسليم واجب الرياضيات — {student.name}",
                    "score": Decimal(str(16 + (idx % 5))),
                    "max_score": Decimal("20"),
                    "teacher_note": notes[idx % len(notes)],
                    "graded_at": now,
                },
            )
        if len(class_students) > 4:
            HomeworkSubmission.objects.update_or_create(
                homework=hw2,
                student=class_students[4],
                defaults={"content": "أنهيت القراءة وأنتظر التصحيح.", "max_score": Decimal("15")},
            )

        quiz, _ = Quiz.objects.update_or_create(
            title="اختبار قصير — جدول الضرب",
            school_class=c1a,
            teacher=math_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "اختبار قصير لمدة 20 دقيقة يغطي جدول الضرب من 1 إلى 10.",
                "due_date": (now + timedelta(days=2)).date(),
                "start_at": now - timedelta(hours=2),
                "end_at": now + timedelta(days=2),
                "duration_minutes": 20,
                "max_attempts": 2,
                "grades_visible": True,
                "review_allowed": True,
                "max_score": Decimal("15"),
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
            QuizQuestion.objects.create(
                quiz=quiz,
                prompt="عرّف عملية الضرب بكلماتك.",
                question_type="essay",
                points=Decimal("5"),
                order=3,
            )

        quiz_ar, _ = Quiz.objects.update_or_create(
            title="مفردات اللغة العربية",
            school_class=c1a,
            teacher=arabic_teacher,
            defaults={
                "subject": "لغة عربية",
                "description": "طابق المصطلح مع معناه.",
                "due_date": (now + timedelta(days=6)).date(),
                "start_at": now,
                "end_at": now + timedelta(days=6),
                "duration_minutes": 15,
                "grades_visible": False,
                "max_score": Decimal("10"),
                "academic_term": term,
            },
        )
        if not quiz_ar.questions.exists():
            QuizQuestion.objects.create(
                quiz=quiz_ar,
                prompt="معنى كلمة «نخيل»",
                question_type="term",
                correct_text="شجر مثمر",
                points=Decimal("5"),
                order=1,
            )
            QuizQuestion.objects.create(
                quiz=quiz_ar,
                prompt="طابق الكلمة بمعناها",
                question_type="matching",
                pairs=[{"left": "كتاب", "right": "مقروء"}, {"left": "قلم", "right": "للكتابة"}],
                points=Decimal("5"),
                order=2,
            )

        questions = list(quiz.questions.order_by("order"))
        if guide_student and questions:
            QuizSubmission.objects.update_or_create(
                quiz=quiz,
                student=guide_student,
                attempt_number=1,
                defaults={
                    "answers": [
                        {"questionId": questions[0].id, "selectedIndex": 2},
                        {"questionId": questions[1].id, "selectedIndex": 0},
                        {"questionId": questions[2].id, "text": "الضرب جمع متكرر."},
                    ],
                    "auto_score": Decimal("10"),
                    "manual_scores": {str(questions[2].id): "4"},
                    "score": Decimal("14"),
                    "max_score": Decimal("15"),
                    "teacher_note": "إجابة المقال جيدة.",
                    "graded_at": now,
                    "time_spent_seconds": 480,
                },
            )

        SubjectAnnouncement.objects.update_or_create(
            title="تذكير: اختبار الرياضيات يوم الأربعاء",
            school_class=c1a,
            teacher=math_teacher,
            defaults={
                "subject": "رياضيات",
                "body": "يرجى مراجعة جدول الضرب والقسمة استعداداً للاختبار القصير.",
                "academic_term": term,
            },
        )
        SubjectAnnouncement.objects.update_or_create(
            title="رحلة علمية إلى حديقة المدرسة",
            school_class=c1a,
            teacher=science_teacher,
            defaults={
                "subject": "علوم",
                "body": "نشاط علمي يوم الخميس لمشاهدة النباتات وتصنيفها.",
                "academic_term": term,
            },
        )
        SubjectMaterial.objects.update_or_create(
            title="ملخص الرياضيات — الوحدة الثالثة",
            school_class=c1a,
            teacher=math_teacher,
            defaults={
                "subject": "رياضيات",
                "description": "ملخص الجمع والطرح والضرب.",
                "category": "slides",
                "academic_term": term,
            },
        )
        SubjectMaterial.objects.update_or_create(
            title="قواعد النحو — المبتدأ والخبر",
            school_class=c1a,
            teacher=arabic_teacher,
            defaults={
                "subject": "لغة عربية",
                "description": "عرض تقديمي مع أمثلة.",
                "category": "book",
                "academic_term": term,
            },
        )

    def _schedules(self, classes, term, teachers):
        teacher_name = {t.teaching_subjects.first().name: t.name for t in teachers if t.teaching_subjects.exists()}
        class_entries = [
            {"day": "السبت", "time": "08:00", "duration": "45", "subject": "رياضيات", "teacher": teacher_name.get("رياضيات", ""), "period": "1"},
            {"day": "السبت", "time": "08:50", "duration": "45", "subject": "لغة عربية", "teacher": teacher_name.get("لغة عربية", ""), "period": "2"},
            {"day": "السبت", "time": "09:40", "duration": "45", "subject": "علوم", "teacher": teacher_name.get("علوم", ""), "period": "3"},
            {"day": "الأحد", "time": "08:00", "duration": "45", "subject": "لغة إنجليزية", "teacher": teacher_name.get("لغة إنجليزية", ""), "period": "1"},
            {"day": "الأحد", "time": "08:50", "duration": "45", "subject": "تربية إسلامية", "teacher": teacher_name.get("تربية إسلامية", ""), "period": "2"},
            {"day": "الأحد", "time": "09:40", "duration": "45", "subject": "دراسات اجتماعية", "teacher": teacher_name.get("دراسات اجتماعية", ""), "period": "3"},
            {"day": "الاثنين", "time": "08:00", "duration": "45", "subject": "رياضيات", "teacher": teacher_name.get("رياضيات", ""), "period": "1"},
            {"day": "الاثنين", "time": "08:50", "duration": "45", "subject": "لغة عربية", "teacher": teacher_name.get("لغة عربية", ""), "period": "2"},
            {"day": "الثلاثاء", "time": "08:00", "duration": "45", "subject": "علوم", "teacher": teacher_name.get("علوم", ""), "period": "1"},
            {"day": "الأربعاء", "time": "08:00", "duration": "45", "subject": "لغة إنجليزية", "teacher": teacher_name.get("لغة إنجليزية", ""), "period": "1"},
            {"day": "الخميس", "time": "08:00", "duration": "45", "subject": "تربية إسلامية", "teacher": teacher_name.get("تربية إسلامية", ""), "period": "1"},
        ]
        exam_entries = [
            {"day": "الأحد", "time": "09:00", "duration": "60", "subject": "رياضيات", "teacher": teacher_name.get("رياضيات", ""), "period": "1"},
            {"day": "الاثنين", "time": "09:00", "duration": "60", "subject": "لغة عربية", "teacher": teacher_name.get("لغة عربية", ""), "period": "2"},
            {"day": "الثلاثاء", "time": "09:00", "duration": "60", "subject": "علوم", "teacher": teacher_name.get("علوم", ""), "period": "1"},
        ]
        for school_class in classes:
            schedule, _ = Schedule.objects.update_or_create(
                name=f"جدول حصص {school_class.name}",
                schedule_type="class",
                academic_term=term,
                defaults={"entries": class_entries, "is_published": True},
            )
            schedule.school_classes.set([school_class])
        exam, _ = Schedule.objects.update_or_create(
            name="جدول اختبارات منتصف الفصل الأول",
            schedule_type="exam",
            academic_term=term,
            defaults={"entries": exam_entries, "is_published": True},
        )
        exam.school_classes.set(classes[:2])

    def _public_content(self, grades):
        news_items = [
            ("افتتاح معمل الحاسوب الجديد", "أخبار", "تم افتتاح معمل حاسوب مجهّز بأحدث الأجهزة لطلاب المرحلة الابتدائية."),
            ("يوم التطوع المدرسي", "فعاليات", "شارك الطلاب في حملة تجميل ساحة المدرسة وتشجير الحديقة."),
            ("فوز فريق الروبوتيك", "إنجازات", "حقق فريق غَزتنا للروبوتيك المركز الأول في المسابقة المحلية."),
            ("ورشة القراءة الإبداعية", "فعاليات", "ورشة أسبوعية لتعزيز مهارات القراءة والكتابة."),
        ]
        for i, (title, category, desc) in enumerate(news_items):
            NewsItem.objects.update_or_create(
                title=title,
                defaults={
                    "description": desc,
                    "body": f"{desc}\n\nتفاصيل إضافية ضمن برنامج غَزتنا التعليمي.",
                    "date": timezone.localdate() - timedelta(days=i * 5),
                    "category": category,
                    "featured": i == 0,
                    "is_published": True,
                },
            )

        programs = [
            ("المرحلة الابتدائية", "الصفوف 1-3", "تعليم أساسي متكامل يجمع بين المهارات الأكاديمية والقيم."),
            ("التميز في الرياضيات", "جميع المراحل", "برنامج تعزيزي لطلاب الرياضيات المتميزين."),
            ("اللغة والإبداع", "ابتدائي", "تنمية مهارات القراءة والكتابة والتعبير."),
        ]
        for i, (title, grade_label, desc) in enumerate(programs):
            Program.objects.update_or_create(
                title=title,
                defaults={
                    "grades": grade_label,
                    "description": desc,
                    "features": ["معلمون متخصصون", "أنشطة تفاعلية", "متابعة أولياء الأمور"],
                    "order": i,
                },
            )

        stats = [
            ("students", "طلاب مسجّلون", "18", "Users"),
            ("teachers", "معلمون", "6", "GraduationCap"),
            ("programs", "برامج تعليمية", "3", "BookOpen"),
        ]
        for i, (key, label, value, icon) in enumerate(stats):
            SchoolStat.objects.update_or_create(
                key=key,
                defaults={"label": label, "value": value, "icon_name": icon, "order": i},
            )
        SchoolStat.objects.filter(key="years").delete()

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

        site = SiteSettings.get()
        site.hero_school_name = "مدرسة غَزتنا"
        site.hero_tagline = "التعليم الرقمي بمعايير عالمية"
        site.contact_address = "غزة، فلسطين"
        site.contact_phone = "+970 599 000 000"
        site.contact_email = "info@ghazatna.edu.ps"
        site.reg_grade_choices = [{"value": g.name, "label": g.name} for g in grades]
        site.programs_by_grade = {
            g.name: f"برنامج تعليمي متكامل لـ{g.name} يشمل المواد الأساسية والأنشطة."
            for g in grades
        }
        site.save()

    def _admissions(self, admin):
        apps = [
            ("لينا أحمد برهوم", "الصف الأول", "أحمد برهوم", "0599123456", "pending", None),
            ("عمر سمير دغمش", "الصف الثاني", "سمير دغمش", "0598765432", "pending", None),
            ("رغد محمد عياش", "الصف الأول", "محمد عياش", "0598111222", "rejected", None),
        ]
        for i, (student_name, grade, parent_name, phone, status, student) in enumerate(apps):
            AdmissionApplication.objects.update_or_create(
                student_name=student_name,
                parent_name=parent_name,
                defaults={
                    "national_id": f"{410000001 + i:09d}",
                    "birth_date": date(2018, 4, 12),
                    "grade": grade,
                    "phone": phone,
                    "address": "غزة",
                    "email": f"{parent_name.replace(' ', '.')}@example.com",
                    "notes": "طلب تسجيل جديد من الموقع العام.",
                    "status": status,
                    "approved_student": student,
                    "approved_by": admin if status == "approved" else None,
                    "approved_at": timezone.now() if status == "approved" else None,
                },
            )

        messages = [
            ("سعاد محمود", "أود معرفة جدول الأقساط للصف الأول.", "new"),
            ("إياد خليل", "هل يمكن تحديد موعد لمقابلة إدارية؟", "new"),
            ("أم كريم", "شكرًا على متابعة ابني هذا الأسبوع.", "archived"),
        ]
        for name, body, status in messages:
            ContactMessage.objects.update_or_create(
                name=name,
                message=body,
                defaults={
                    "phone": "0599000000",
                    "email": "visitor@example.com",
                    "status": status,
                },
            )

    def _finance(self, students, guide_student, year, grades):
        today = timezone.localdate()
        year_start, year_end = year.start_date, year.end_date

        def clamp(d):
            return max(year_start, min(year_end, d))

        plan1, _ = FeePlan.objects.update_or_create(
            name="رسوم الصف الأول 2026/2027",
            defaults={
                "total_amount": Decimal("2400"),
                "installments_count": 3,
                "billing_period": FeePlan.BILLING_FULL_YEAR,
                "academic_year": year,
                "is_active": True,
            },
        )
        plan1.grades.set([grades[0]])
        for order, amount, start, end, inst_name in [
            (1, Decimal("800"), clamp(today - timedelta(days=20)), clamp(today + timedelta(days=20)), "القسط الأول"),
            (2, Decimal("800"), clamp(today + timedelta(days=21)), clamp(today + timedelta(days=80)), "القسط الثاني"),
            (3, Decimal("800"), clamp(today + timedelta(days=81)), clamp(today + timedelta(days=140)), "القسط الثالث"),
        ]:
            FeeInstallment.objects.update_or_create(
                fee_plan=plan1,
                order=order,
                defaults={"name": inst_name, "amount": amount, "start_date": start, "end_date": end},
            )

        plan2, _ = FeePlan.objects.update_or_create(
            name="رسوم الصف الثاني والثالث 2026/2027",
            defaults={
                "total_amount": Decimal("2600"),
                "installments_count": 2,
                "billing_period": FeePlan.BILLING_FULL_YEAR,
                "academic_year": year,
                "is_active": True,
            },
        )
        plan2.grades.set(grades[1:])
        for order, amount, start, end, inst_name in [
            (1, Decimal("1300"), clamp(today - timedelta(days=10)), clamp(today + timedelta(days=40)), "الدفعة الأولى"),
            (2, Decimal("1300"), clamp(today + timedelta(days=41)), clamp(today + timedelta(days=120)), "الدفعة الثانية"),
        ]:
            FeeInstallment.objects.update_or_create(
                fee_plan=plan2,
                order=order,
                defaults={"name": inst_name, "amount": amount, "start_date": start, "end_date": end},
            )

        apply_plan_to_students(plan1)
        apply_plan_to_students(plan2)

        admin_finance = User.objects.filter(username="admin_finance").first()
        for i, student in enumerate(students):
            balance = StudentFeeBalance.objects.filter(student=student).first()
            if not balance:
                continue
            if i % 4 == 0:
                paid = balance.total
            elif i % 4 == 1:
                paid = (balance.total / 2).quantize(Decimal("0.01"))
            elif i % 4 == 2:
                paid = Decimal("0")
            else:
                paid = Decimal("400")
            balance.paid = paid
            balance.save(update_fields=["paid"])

        if guide_student:
            PaymentNotice.objects.update_or_create(
                student=guide_student,
                amount=Decimal("800"),
                date=today - timedelta(days=8),
                defaults={
                    "declared_amount": Decimal("800"),
                    "status": "approved",
                    "source": "parent",
                    "note": "دفعة القسط الأول — تم الاعتماد.",
                    "reviewed_by": admin_finance,
                },
            )
            PaymentNotice.objects.update_or_create(
                student=guide_student,
                amount=Decimal("200"),
                date=today - timedelta(days=1),
                defaults={
                    "declared_amount": Decimal("200"),
                    "status": "pending",
                    "source": "parent",
                    "note": "إشعار بانتظار المراجعة.",
                },
            )

        unpaid = next((s for s in students if s.id != getattr(guide_student, "id", None)), None)
        if unpaid:
            PaymentNotice.objects.update_or_create(
                student=unpaid,
                amount=Decimal("300"),
                date=today - timedelta(days=12),
                defaults={
                    "declared_amount": Decimal("500"),
                    "status": "rejected",
                    "source": "manual",
                    "note": "المبلغ المعلن لا يطابق الإيصال.",
                    "reviewed_by": admin_finance,
                },
            )

    def _certificates(self, admin, year, term1, archived_year):
        publish_term_certificates(year, admin, term_id=str(term1.id))
        config = get_or_create_certificate_config(year)
        config.honors_enabled = True
        config.honors_min_average = Decimal("90")
        config.save()

        arch_config, _ = CertificateConfig.objects.update_or_create(
            academic_year=archived_year,
            defaults={
                "is_term_published": True,
                "is_published": True,
                "is_year_published": True,
                "term_published_at": timezone.now() - timedelta(days=80),
                "year_published_at": timezone.now() - timedelta(days=50),
                "published_at": timezone.now() - timedelta(days=50),
                "published_by": admin,
            },
        )
        arch_term = archived_year.terms.order_by("-sort_order").first()
        if arch_term:
            arch_config.published_term = arch_term
            arch_config.save()

    def _promotions(self, admin, grades, year, archived_year, students):
        for grade in grades:
            PromotionPolicy.objects.update_or_create(
                grade=grade,
                defaults={
                    "evaluation_scope": PromotionPolicy.EVAL_FULL_YEAR,
                    "year_calculation_method": PromotionPolicy.CALC_TERM_AVERAGE,
                    "pass_rule": PromotionPolicy.PASS_MINIMUM_COUNT,
                    "pass_minimum_count": 4,
                    "required_subjects": SUBJECT_NAMES[:4],
                    "pass_score_ratio": Decimal("0.500"),
                    "pass_promotion_mode": PromotionPolicy.MODE_AUTOMATIC,
                    "fail_handling_mode": PromotionPolicy.FAIL_MANUAL_REVIEW,
                    "is_configured": True,
                },
            )

        YearEndPromotionRun.objects.update_or_create(
            academic_year=archived_year,
            defaults={
                "new_academic_year": year,
                "executed_by": admin,
                "status": YearEndPromotionRun.STATUS_EXECUTED,
                "summary": {
                    "promoted": 14,
                    "repeated": 2,
                    "manual": 2,
                },
                "student_results": [
                    {"studentId": students[0].id, "name": students[0].name, "decision": "promoted"}
                ],
            },
        )

    def _alerts(self, teachers, guide_student):
        math_user = teachers[0].user
        if math_user:
            TeacherReadAlert.objects.get_or_create(
                teacher=math_user,
                alert_key="homework-due-soon",
            )
        if guide_student and guide_student.parent_id:
            ParentGradesSeenState.objects.update_or_create(
                parent=guide_student.parent,
                student=guide_student,
                defaults={"last_seen_at": timezone.now() - timedelta(days=2)},
            )
            ParentDismissedAlert.objects.get_or_create(
                parent=guide_student.parent,
                alert_id="fees-reminder",
            )

    def _print_logins(self, guide_student):
        self.stdout.write(self.style.SUCCESS("تم ملء البيانات التجريبية بنجاح."))
        self.stdout.write("")
        self.stdout.write("حسابات الدخول (كلمة المرور للجميع: 123456)")
        self.stdout.write("  مدير كامل:          ismail")
        self.stdout.write("  إدارة الطلاب:       admin_students")
        self.stdout.write("  إدارة الأكاديمي:    admin_academics")
        self.stdout.write("  إدارة المالية:      admin_finance")
        self.stdout.write("  إدارة المحتوى:      admin_content")
        self.stdout.write("  إدارة الكادر:       admin_staff")
        self.stdout.write("  معلم رياضيات:       guide_teacher")
        self.stdout.write("  معلمة عربي:         teacher_arabic")
        self.stdout.write("  معلم علوم:          teacher_science")
        self.stdout.write("  معلمة إنجليزي:      teacher_english")
        if guide_student:
            self.stdout.write(f"  ولي أمر / طالب:     {guide_student.student_number}  ({guide_student.name})")
        self.stdout.write("")
        self.stdout.write("لإعادة التوليد من الصفر:  python manage.py seed_local --reset")
