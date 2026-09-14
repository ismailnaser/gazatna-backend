from datetime import date

from academics.models import Grade, SchoolClass, Student

SECTION_LABELS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح", "ط", "ي", "ك", "ل", "م", "ن", "س", "ع", "ف", "ص", "ق", "ر"]
MAX_SECTIONS = 20
MAX_SECTION_NAME = 40


class SectionSyncError(ValueError):
    pass


def format_section_display(grade_name: str, section: str) -> str:
    section = (section or "").strip()
    grade_name = (grade_name or "").strip()
    if grade_name and section:
        return f"{grade_name} ({section})"
    return grade_name or section


def normalize_section_names(raw_names) -> list[str]:
    if not isinstance(raw_names, list):
        raise SectionSyncError("أسماء الشعب غير صالحة")
    names = []
    for item in raw_names:
        label = " ".join(str(item or "").split())
        if not label:
            raise SectionSyncError("اكتب اسماً لكل شعبة")
        if len(label) > MAX_SECTION_NAME:
            raise SectionSyncError("اسم الشعبة طويل جداً")
        names.append(label)
    if not names:
        raise SectionSyncError("أضف شعبة واحدة على الأقل")
    if len(names) > MAX_SECTIONS:
        raise SectionSyncError("عدد الشعب كبير جداً")
    if len(set(names)) != len(names):
        raise SectionSyncError("أسماء الشعب يجب أن تكون مختلفة")
    return names


def get_ordered_grades():
    return list(Grade.objects.order_by("sort_order", "id"))


def get_next_grade(current_grade_name: str):
    grades = get_ordered_grades()
    names = [g.name for g in grades]
    if current_grade_name not in names:
        return None
    index = names.index(current_grade_name)
    if index + 1 >= len(grades):
        return None
    return grades[index + 1]


def promote_student_to_next_grade(student: Student):
    next_grade = get_next_grade(student.grade_level)
    if not next_grade:
        return None

    target_class = (
        SchoolClass.objects.filter(grade_level=next_grade.name, section=student.section).first()
        or SchoolClass.objects.filter(grade_level=next_grade.name).order_by("section", "id").first()
    )
    if not target_class:
        return None

    student.grade_level = next_grade.name
    student.section = target_class.section
    student.school_class = target_class
    student.save(update_fields=["grade_level", "section", "school_class"])
    return next_grade


def _apply_section_label(grade: Grade, school_class: SchoolClass, label: str):
    old_section = school_class.section
    school_class.section = label
    school_class.name = format_section_display(grade.name, label)
    school_class.save(update_fields=["section", "name"])
    if old_section and old_section != label:
        Student.objects.filter(school_class=school_class).update(section=label)
        Student.objects.filter(grade_level=grade.name, section=old_section).exclude(
            school_class_id=school_class.id
        ).update(section=label)


def sync_grade_sections(grade: Grade, section_names=None):
    existing = list(SchoolClass.objects.filter(grade_level=grade.name).order_by("id"))

    if section_names is not None:
        names = normalize_section_names(section_names)
        grade.sections_count = len(names)
        grade.save(update_fields=["sections_count"])

        for index, label in enumerate(names):
            if index < len(existing):
                _apply_section_label(grade, existing[index], label)
            else:
                SchoolClass.objects.create(
                    grade_level=grade.name,
                    section=label,
                    name=format_section_display(grade.name, label),
                )
        for school_class in existing[len(names) :]:
            school_class.delete()
        return

    desired = int(grade.sections_count or 0)
    desired = max(1, min(desired, MAX_SECTIONS))
    grade.sections_count = desired
    grade.save(update_fields=["sections_count"])

    if len(existing) > desired:
        for school_class in existing[desired:]:
            school_class.delete()
        existing = existing[:desired]

    used = {school_class.section for school_class in existing if school_class.section}
    while len(existing) < desired:
        label = next((item for item in SECTION_LABELS if item not in used), None)
        if not label:
            label = str(len(existing) + 1)
        used.add(label)
        existing.append(
            SchoolClass.objects.create(
                grade_level=grade.name,
                section=label,
                name=format_section_display(grade.name, label),
            )
        )


def ensure_all_grade_sections():
    for grade in Grade.objects.order_by("sort_order", "id"):
        sync_grade_sections(grade)
