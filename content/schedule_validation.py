import re
from typing import Any


def _normalize_teacher(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _parse_duration_minutes(value: Any) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else 60
    except (TypeError, ValueError):
        return 60


def _time_to_minutes(value: str) -> int | None:
    match = re.match(r"^(\d{1,2}):(\d{2})$", (value or "").strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _ranges_overlap(
    a_start: str,
    a_duration: int,
    b_start: str,
    b_duration: int,
) -> bool:
    a_start_min = _time_to_minutes(a_start)
    b_start_min = _time_to_minutes(b_start)
    if a_start_min is None or b_start_min is None or a_duration <= 0 or b_duration <= 0:
        return False
    a_end = a_start_min + a_duration
    b_end = b_start_min + b_duration
    return a_start_min < b_end and a_end > b_start_min


def collect_class_schedule_lessons(entries: list | None) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        teacher_display = str(entry.get("teacher") or "").strip()
        teacher = _normalize_teacher(teacher_display)
        day = str(entry.get("day") or "").strip()
        time_value = str(entry.get("time") or "").strip()
        if not teacher or not day or not time_value:
            continue
        lessons.append(
            {
                "teacher": teacher,
                "teacher_display": teacher_display,
                "day": day,
                "time": time_value,
                "duration": _parse_duration_minutes(entry.get("duration")),
                "subject": str(entry.get("subject") or "").strip(),
                "period": str(entry.get("period") or "").strip(),
            }
        )
    return lessons


def _lesson_pair_teacher_conflict(
    left: dict[str, Any],
    right: dict[str, Any],
) -> str | None:
    if left["teacher"] != right["teacher"]:
        return None
    if left["day"] != right["day"]:
        return None
    if not _ranges_overlap(
        left["time"],
        left["duration"],
        right["time"],
        right["duration"],
    ):
        return None
    return (
        f"المعلم {left['teacher_display']} لديه أكثر من حصة في "
        f"«{left['day']}» في نفس الوقت"
    )


def find_teacher_schedule_conflict(
    lessons_a: list[dict[str, Any]],
    lessons_b: list[dict[str, Any]],
) -> str | None:
    if lessons_a is lessons_b:
        for index in range(len(lessons_a)):
            for other_index in range(index + 1, len(lessons_a)):
                conflict = _lesson_pair_teacher_conflict(
                    lessons_a[index],
                    lessons_a[other_index],
                )
                if conflict:
                    return conflict
        return None

    for left in lessons_a:
        for right in lessons_b:
            conflict = _lesson_pair_teacher_conflict(left, right)
            if conflict:
                return conflict
    return None


def validate_class_schedule_teacher_conflicts(
    entries: list | None,
    *,
    other_entries_lists: list[list | None] | None = None,
) -> str | None:
    lessons = collect_class_schedule_lessons(entries)
    same_schedule_error = find_teacher_schedule_conflict(lessons, lessons)
    if same_schedule_error:
        return same_schedule_error

    for other_entries in other_entries_lists or []:
        other_lessons = collect_class_schedule_lessons(other_entries)
        conflict = find_teacher_schedule_conflict(lessons, other_lessons)
        if conflict:
            return conflict
    return None


def validate_unique_class_schedule_classes(class_ids, *, instance=None, academic_term=None):
    from content.models import Schedule, ScheduleType

    if not class_ids:
        return None
    qs = Schedule.objects.filter(
        schedule_type=ScheduleType.CLASS,
        school_classes__id__in=class_ids,
    )
    if academic_term is not None:
        qs = qs.filter(academic_term=academic_term)
    if instance is not None:
        qs = qs.exclude(pk=instance.pk)
    existing = qs.distinct().first()
    if not existing:
        return None
    overlap = existing.school_classes.filter(id__in=class_ids).first()
    if not overlap:
        return "يوجد جدول حصص مسبقاً لإحدى الشعب المختارة"
    section = overlap.section or ""
    label = f"{overlap.grade_level} - {section}".strip(" -") or overlap.name
    return (
        f"لا يمكن إنشاء أكثر من جدول حصص لنفس الشعبة. "
        f"يوجد جدول مسبقاً لـ «{label}» ({existing.name})"
    )
