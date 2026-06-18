from academics.models import Grade, SchoolClass, Student


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
        SchoolClass.objects.filter(grade_level=next_grade.name).order_by("section", "id").first()
    )
    if not target_class:
        return None

    student.grade_level = next_grade.name
    student.section = target_class.section
    student.school_class = target_class
    student.save(update_fields=["grade_level", "section", "school_class"])
    return next_grade
