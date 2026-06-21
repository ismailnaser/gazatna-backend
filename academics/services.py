from datetime import date

from academics.models import Grade, SchoolClass, Student

SECTION_LABELS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح", "ط", "ي", "ك", "ل", "م", "ن", "س", "ع", "ف", "ص", "ق", "ر"]


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


def sync_grade_sections(grade: Grade):
    desired = int(grade.sections_count or 0)
    desired = max(1, min(desired, len(SECTION_LABELS)))
    grade.sections_count = desired
    grade.save(update_fields=["sections_count"])

    existing = list(SchoolClass.objects.filter(grade_level=grade.name).order_by("id"))
    existing_by_section = {school_class.section: school_class for school_class in existing if school_class.section}
    desired_sections = SECTION_LABELS[:desired]

    for section in desired_sections:
        if section in existing_by_section:
            school_class = existing_by_section[section]
            expected_name = f"{grade.name} - {section}"
            if school_class.name != expected_name:
                school_class.name = expected_name
                school_class.save(update_fields=["name"])
        else:
            SchoolClass.objects.create(
                grade_level=grade.name,
                section=section,
                name=f"{grade.name} - {section}",
            )

    for school_class in existing:
        if school_class.section and school_class.section not in desired_sections:
            school_class.delete()


def ensure_all_grade_sections():
    for grade in Grade.objects.order_by("sort_order", "id"):
        sync_grade_sections(grade)
