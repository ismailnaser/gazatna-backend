from django.db.models import Avg, F, FloatField
from django.db.models.functions import Cast, Least

from academics.models import SubjectGrade


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
