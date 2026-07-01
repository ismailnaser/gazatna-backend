from itertools import product

from django.db import transaction

from rest_framework import serializers

from academics.models import SchoolClass, Subject, ClassSubjectAssignment
from staff.models import TeacherClassAssignment, TeacherProfile


def teacher_teaching_class_ids(teacher):
    """فصول تدريس المواد — لا تشمل مربي الصف."""
    return set(
        TeacherClassAssignment.objects.filter(teacher=teacher).values_list(
            "school_class_id", flat=True
        )
    )


def teacher_homeroom_class_ids(teacher):
    """فصول مربي الصف فقط."""
    return set(teacher.homeroom_classes.values_list("id", flat=True))


def teacher_class_ids(teacher):
    """فصول تدريس المواد (مستقل عن مربي الصف)."""
    return teacher_teaching_class_ids(teacher)


def teacher_school_classes(teacher):
    class_ids = teacher_teaching_class_ids(teacher)
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

    teachers = TeacherProfile.objects.prefetch_related("teaching_subjects", "class_assignments")
    for teacher in teachers:
        if school_class_id not in teacher_teaching_class_ids(teacher):
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
    from academics.academic_services import get_current_academic_term

    if not school_class_id:
        return []

    term = get_current_academic_term()
    grouped: dict[str, dict] = {}

    direct_qs = ClassSubjectAssignment.objects.filter(school_class_id=school_class_id)
    if term:
        direct_qs = direct_qs.filter(academic_term=term)
    direct = direct_qs.select_related("subject")
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


def validate_homeroom_teacher(teacher, school_class):
    """مربي صف واحد لكل فصل، ولا يمكن للمعلم أن يكون مربي أكثر من فصل."""
    if teacher is None or school_class is None:
        return

    other_class = teacher.homeroom_classes.exclude(pk=school_class.pk).first()
    if other_class:
        raise serializers.ValidationError(
            {
                "detail": (
                    f"المعلم {teacher.name} مربي صف لـ {other_class.name} بالفعل — "
                    "لا يمكن إسناده كمربي صف لفصل آخر"
                )
            }
        )


def collect_subject_class_conflicts(teacher, subject_id, class_ids):
    """يفصل الفصول القابلة للإسناد عن الفصول التي فيها معلم آخر."""
    subject_id = int(subject_id)
    class_ids = [int(class_id) for class_id in class_ids if class_id is not None]
    if not class_ids:
        return [], []

    subject_name = Subject.objects.filter(id=subject_id).values_list("name", flat=True).first() or str(subject_id)
    class_names = dict(SchoolClass.objects.filter(id__in=class_ids).values_list("id", "name"))

    assignable: list[int] = []
    conflicts: list[str] = []
    exclude_pk = teacher.pk if teacher and teacher.pk else None
    others = TeacherProfile.objects.prefetch_related(
        "teaching_subjects", "class_assignments"
    ).exclude(pk=exclude_pk)

    for class_id in class_ids:
        conflict_teacher = None
        for other in others:
            other_subject_ids = {subject.id for subject in other.teaching_subjects.all()}
            if subject_id not in other_subject_ids:
                continue
            if class_id not in teacher_teaching_class_ids(other):
                continue
            conflict_teacher = other.name
            break

        class_name = class_names.get(class_id, str(class_id))
        if conflict_teacher:
            conflicts.append(
                f"مادة {subject_name} في فصل {class_name} مسندة بالفعل للمعلم {conflict_teacher}"
            )
        else:
            assignable.append(class_id)

    return assignable, conflicts


def validate_teacher_subject_class_assignments(teacher, subject_ids, class_ids):
    """
    لكل (مادة، فصل): معلم واحد فقط.
    يمكن لعدة معلمين تدريس نفس المادة في فصول مختلفة.
    """
    subject_ids = [int(s) for s in subject_ids if s is not None]
    class_ids = [int(c) for c in class_ids if c is not None]
    if not subject_ids or not class_ids:
        return

    exclude_pk = teacher.pk if teacher and teacher.pk else None
    others = TeacherProfile.objects.prefetch_related(
        "teaching_subjects", "class_assignments"
    ).exclude(pk=exclude_pk)

    subject_names = dict(Subject.objects.filter(id__in=subject_ids).values_list("id", "name"))
    class_names = dict(SchoolClass.objects.filter(id__in=class_ids).values_list("id", "name"))

    messages = []
    for sid, cid in product(subject_ids, class_ids):
        for other in others:
            other_subject_ids = {s.id for s in other.teaching_subjects.all()}
            if sid not in other_subject_ids:
                continue
            if cid not in teacher_teaching_class_ids(other):
                continue
            subject_name = subject_names.get(sid, str(sid))
            class_name = class_names.get(cid, str(cid))
            messages.append(
                f"مادة {subject_name} في فصل {class_name} مسندة بالفعل للمعلم {other.name}"
            )
            break

    if messages:
        raise serializers.ValidationError({"detail": messages[0] if len(messages) == 1 else "؛ ".join(messages)})


def sync_teacher_teaching_classes(teacher, class_ids):
    """يربط المعلم بفصول التدريس (لا يمس مربي الصف)."""
    class_ids = [int(class_id) for class_id in class_ids if class_id is not None]
    TeacherClassAssignment.objects.filter(teacher=teacher).delete()
    for class_id in class_ids:
        TeacherClassAssignment.objects.create(teacher=teacher, school_class_id=class_id)


def _teacher_still_needs_class(teacher, class_id, *, exclude_subject_id=None):
    """هل المعلم ما زال يحتاج الفصل لمواد أخرى مسندة لهذا الفصل؟"""
    subject_ids = set(teacher.teaching_subjects.values_list("id", flat=True))
    if exclude_subject_id is not None:
        subject_ids.discard(int(exclude_subject_id))

    if not subject_ids:
        return False

    return ClassSubjectAssignment.objects.filter(
        school_class_id=class_id,
        subject_id__in=subject_ids,
    ).exists()


def _maybe_remove_class_from_teacher(teacher, class_id, *, exclude_subject_id=None):
    if _teacher_still_needs_class(teacher, class_id, exclude_subject_id=exclude_subject_id):
        return
    TeacherClassAssignment.objects.filter(teacher=teacher, school_class_id=class_id).delete()


@transaction.atomic
def sync_subject_section_teachers(subject, sections):
    """
    sections: [{"classId": int, "teacherId": int | None}, ...]
    يربط المادة بالشعب ويحدّد معلم كل شعبة.
    """
    normalized = []
    for row in sections or []:
        class_id = row.get("classId")
        if class_id is None:
            continue
        normalized.append(
            {
                "class_id": int(class_id),
                "teacher_id": int(row["teacherId"]) if row.get("teacherId") else None,
            }
        )

    class_ids = [row["class_id"] for row in normalized]

    from academics.term_operational_services import require_operational_term

    term = require_operational_term()
    ClassSubjectAssignment.objects.filter(subject=subject, academic_term=term).delete()
    for class_id in class_ids:
        ClassSubjectAssignment.objects.get_or_create(
            subject=subject,
            school_class_id=class_id,
            academic_term=term,
        )

    affected_teacher_ids: set[int] = set()

    for row in normalized:
        class_id = row["class_id"]
        teacher_id = row["teacher_id"]

        others = TeacherProfile.objects.prefetch_related("teaching_subjects").all()
        for other in others:
            other_subject_ids = {item.id for item in other.teaching_subjects.all()}
            if subject.id not in other_subject_ids:
                continue
            if class_id not in teacher_teaching_class_ids(other):
                continue
            if teacher_id and other.pk == teacher_id:
                continue
            _maybe_remove_class_from_teacher(other, class_id, exclude_subject_id=subject.id)
            affected_teacher_ids.add(other.pk)

        if not teacher_id:
            continue

        teacher = TeacherProfile.objects.prefetch_related("teaching_subjects").get(pk=teacher_id)
        teacher.teaching_subjects.add(subject)
        TeacherClassAssignment.objects.get_or_create(teacher=teacher, school_class_id=class_id)
        affected_teacher_ids.add(teacher.pk)

    for teacher in TeacherProfile.objects.filter(teaching_subjects=subject).prefetch_related(
        "class_assignments"
    ):
        assigned_class_ids = teacher_teaching_class_ids(teacher)
        has_section = ClassSubjectAssignment.objects.filter(
            subject=subject,
            school_class_id__in=assigned_class_ids,
        ).exists()
        if not has_section:
            teacher.teaching_subjects.remove(subject)
            affected_teacher_ids.add(teacher.pk)

    return sorted(affected_teacher_ids)
