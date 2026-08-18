from datetime import timedelta

from django.db.models import Avg, Count, F, FloatField
from django.db.models.functions import Cast, Least

from academics.academic_services import get_active_academic_year
from academics.models import AcademicYear, Student, SubjectGrade

GRADE_CHART_LEVELS = ["التاسع", "العاشر", "الحادي عشر", "الثاني عشر"]


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
    rows = list(
        qs.values("student__grade_level").annotate(
            avg=Avg(
                Least(
                    Cast(F("score"), FloatField()) / Cast(F("max_score"), FloatField()) * 100.0,
                    100.0,
                )
            ),
            n=Count("id"),
        )
    )
    chart = []
    for label in GRADE_CHART_LEVELS:
        weighted = 0.0
        total_n = 0
        for row in rows:
            grade_level = row.get("student__grade_level") or ""
            if label not in grade_level:
                continue
            count = int(row.get("n") or 0)
            weighted += float(row.get("avg") or 0) * count
            total_n += count
        if total_n <= 0:
            continue
        value = round(min(100.0, weighted / total_n), 1)
        if value <= 0:
            continue
        chart.append({"label": label, "value": value})
    return chart


def _year_name_aliases(year: AcademicYear) -> list[str]:
    name = (year.name or "").strip()
    aliases = {name}
    if name:
        aliases.add(name.replace("/", "-"))
        aliases.add(name.replace("-", "/"))
        aliases.add(name.replace("–", "-"))
        aliases.add(name.replace("—", "-"))
    return [alias for alias in aliases if alias]


def _students_registered_in_year(year: AcademicYear | None, grade_level: str = ""):
    """Students on roll for an academic year.

    Prefer Enrollment rows. For the active year with no enrollments yet,
    use the current school roster so analytics do not show 0 while students exist.
    """
    if not year:
        return Student.objects.none()

    aliases = _year_name_aliases(year)
    qs = Student.objects.filter(enrollments__academic_year__in=aliases).distinct()
    if grade_level:
        qs = qs.filter(grade_level=grade_level)
    if qs.exists():
        return qs
    if year.is_active:
        fallback = Student.objects.all()
        if grade_level:
            fallback = fallback.filter(grade_level=grade_level)
        return fallback
    created = Student.objects.filter(
        created_at__gte=year.start_date,
        created_at__lt=year.end_date + timedelta(days=1),
    )
    if grade_level:
        created = created.filter(grade_level=grade_level)
    return created


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
    known_counts = {}
    if year:
        known_counts[year.id] = registered
    if previous_year:
        known_counts[previous_year.id] = previous_registered
    yearly_chart = []
    for y in years:
        count = known_counts.get(y.id)
        if count is None:
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
