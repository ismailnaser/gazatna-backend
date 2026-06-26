from itertools import product

from rest_framework import serializers

from academics.models import SchoolClass, Subject, ClassSubjectAssignment
from staff.models import TeacherClassAssignment, TeacherProfile


def teacher_class_ids(teacher):
    assigned = set(
        TeacherClassAssignment.objects.filter(teacher=teacher).values_list("school_class_id", flat=True)
    )
    homeroom = set(teacher.homeroom_classes.values_list("id", flat=True))
    return assigned | homeroom


def teacher_school_classes(teacher):
    class_ids = teacher_class_ids(teacher)
    if not class_ids:
        return SchoolClass.objects.none()
    return SchoolClass.objects.filter(id__in=class_ids).order_by("grade_level", "section", "id")


def subjects_for_school_class(school_class_id):
    """المواد المسندة لفصل معيّن (مباشرة أو عبر المعلمين)."""
    if not school_class_id:
        return Subject.objects.none()

    subject_ids: set[int] = set(
        ClassSubjectAssignment.objects.filter(school_class_id=school_class_id).values_list(
            "subject_id", flat=True
        )
    )

    teachers = TeacherProfile.objects.prefetch_related(
        "teaching_subjects", "class_assignments", "homeroom_classes"
    )
    for teacher in teachers:
        if school_class_id not in teacher_class_ids(teacher):
            continue
        subject_ids.update(s.id for s in teacher.teaching_subjects.all())

    if not subject_ids:
        return Subject.objects.none()

    return Subject.objects.filter(id__in=subject_ids).order_by("name")


def school_class_id_for_student(student):
    """يحدد معرف صف الطالب من الربط المباشر أو من المرحلة والشعبة."""
    if getattr(student, "school_class_id", None):
        return student.school_class_id
    if not student.grade_level:
        return None

    qs = SchoolClass.objects.filter(grade_level=student.grade_level)
    if student.section:
        match = qs.filter(section=student.section).values_list("id", flat=True).first()
        if match:
            return match
    return qs.values_list("id", flat=True).first()


def class_subject_assignments(school_class_id):
    """قائمة المواد مع أسماء المعلمين المسندين لكل مادة في الفصل."""
    if not school_class_id:
        return []

    grouped: dict[str, dict] = {}

    direct = ClassSubjectAssignment.objects.filter(
        school_class_id=school_class_id
    ).select_related("subject")
    for row in direct:
        grouped.setdefault(
            row.subject.name,
            {"subject": row.subject.name, "teacherNames": set()},
        )

    teacher_ids = set(
        TeacherClassAssignment.objects.filter(school_class_id=school_class_id).values_list(
            "teacher_id", flat=True
        )
    )
    teacher_ids.update(
        TeacherProfile.objects.filter(homeroom_classes__id=school_class_id).values_list("id", flat=True)
    )

    if teacher_ids:
        teachers = TeacherProfile.objects.filter(id__in=teacher_ids).prefetch_related("teaching_subjects")
        for teacher in teachers:
            for subject in teacher.teaching_subjects.all():
                row = grouped.setdefault(
                    subject.name,
                    {"subject": subject.name, "teacherNames": set()},
                )
                row["teacherNames"].add(teacher.name)

    return [
        {
            "subject": name,
            "teacherName": "، ".join(sorted(grouped[name]["teacherNames"])),
        }
        for name in sorted(grouped.keys())
    ]


def class_subject_assignments_for_student(student):
    class_id = school_class_id_for_student(student)
    if not class_id:
        return []
    return class_subject_assignments(class_id)


def validate_teacher_subject_class_assignments(teacher, subject_ids, class_ids):
    subject_ids = [int(s) for s in subject_ids if s is not None]
    class_ids = [int(c) for c in class_ids if c is not None]
    if not subject_ids or not class_ids:
        return

    exclude_pk = teacher.pk if teacher and teacher.pk else None
    others = TeacherProfile.objects.prefetch_related("teaching_subjects").exclude(pk=exclude_pk)

    subject_names = dict(Subject.objects.filter(id__in=subject_ids).values_list("id", "name"))
    class_names = dict(SchoolClass.objects.filter(id__in=class_ids).values_list("id", "name"))

    messages = []
    for sid, cid in product(subject_ids, class_ids):
        for other in others:
            other_subject_ids = {s.id for s in other.teaching_subjects.all()}
            if sid not in other_subject_ids:
                continue
            if cid not in teacher_class_ids(other):
                continue
            subject_name = subject_names.get(sid, str(sid))
            class_name = class_names.get(cid, str(cid))
            messages.append(
                f"مادة {subject_name} في فصل {class_name} مسندة بالفعل للمعلم {other.name}"
            )
            break

    if messages:
        raise serializers.ValidationError({"detail": messages[0] if len(messages) == 1 else "؛ ".join(messages)})
