from django.db.models import Avg, Count, F, FloatField
from django.db.models.functions import Cast, Least

from academics.academic_services import get_active_academic_year
from academics.models import AcademicYear, Student, SubjectGrade


def subject_grades_percent_queryset(queryset=None):
    qs = queryset if queryset is not None else SubjectGrade.objects.all()
    return qs.filter(max_score__gt=0)


def average_grade_percent(queryset=None) -> float:
    """Average of (score / max_score * 100), capped at 100 per record."""
    qs = subject_grades_percent_queryset(queryset)
    avg = qs.aggregate(
        avg=Avg(
            Least(
                Cast(F("score"), FloatField()) / Cast(F("max_score"), FloatField()) * 100.0,
                100.0,
            )
        )
    )["avg"]
    if avg is None:
        return 0.0
    return round(min(100.0, float(avg)), 1)


def grade_chart_by_level(queryset=None) -> list[dict]:
    qs = subject_grades_percent_queryset(queryset)
    chart = []
    for level in ["التاسع", "العاشر", "الحادي عشر", "الثاني عشر"]:
        level_qs = qs.filter(student__grade_level__contains=level)
        if not level_qs.exists():
            continue
        value = average_grade_percent(level_qs)
        if value <= 0:
            continue
        chart.append({"label": level, "value": value})
    return chart


def _students_registered_in_year(year: AcademicYear | None, grade_level: str = ""):
    if not year:
        return Student.objects.none()
    qs = Student.objects.filter(
        created_at__date__gte=year.start_date,
        created_at__date__lte=year.end_date,
    )
    if grade_level:
        qs = qs.filter(grade_level=grade_level)
    return qs


def _growth_percent(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


def student_enrollment_analytics(grade_level: str = "") -> dict:
    """Enrollment KPIs for the active academic year vs the previous year."""
    year = get_active_academic_year()
    previous_year = None
    if year:
        previous_year = (
            AcademicYear.objects.filter(start_date__lt=year.start_date)
            .order_by("-start_date", "-id")
            .first()
        )

    registered = _students_registered_in_year(year, grade_level).count()
    previous_registered = _students_registered_in_year(previous_year, grade_level).count()
    growth = _growth_percent(registered, previous_registered)

    base_qs = Student.objects.all()
    if grade_level:
        base_qs = base_qs.filter(grade_level=grade_level)

    active_students = base_qs.filter(is_active=True).count()
    inactive_students = base_qs.filter(is_active=False).count()

    # Registrations this year by grade level
    year_regs = _students_registered_in_year(year, grade_level)
    students_chart = []
    for row in (
        year_regs.values("grade_level")
        .annotate(value=Count("id"))
        .order_by("grade_level")
    ):
        label = (row["grade_level"] or "").strip()
        if not label:
            continue
        students_chart.append({"label": label, "value": int(row["value"] or 0)})

    # Registrations per academic year (up to 6 most recent years)
    years = list(AcademicYear.objects.order_by("-start_date", "-id")[:6])
    years.reverse()
    yearly_chart = []
    for y in years:
        count = _students_registered_in_year(y, grade_level).count()
        yearly_chart.append({"label": y.name, "value": count})

    return {
        "registeredStudents": registered,
        "previousYearRegisteredStudents": previous_registered,
        "studentsGrowthPercent": growth,
        "academicYear": year.name if year else None,
        "previousAcademicYear": previous_year.name if previous_year else None,
        "activeStudents": active_students,
        "inactiveStudents": inactive_students,
        "totalStudents": active_students + inactive_students,
        "studentsChart": students_chart,
        "yearlyStudentsChart": yearly_chart,
    }
