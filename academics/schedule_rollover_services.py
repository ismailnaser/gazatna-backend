from rest_framework import serializers

from academics.academic_services import get_active_academic_year, get_current_academic_term, term_display_name
from content.models import Schedule


def normalize_schedule_rollover_mode(value) -> str:
    mode = str(value or "copy").strip().lower()
    if mode in {"fresh", "new", "delete"}:
        return "fresh"
    return "copy"


def get_previous_operational_term():
    from academics.models import AcademicTerm, AcademicYear

    current = get_current_academic_term()
    if not current:
        return None

    year = current.academic_year
    if current.sort_order > 1:
        return (
            AcademicTerm.objects.filter(
                academic_year=year,
                sort_order__lt=current.sort_order,
                is_closed=True,
            )
            .order_by("-sort_order", "-id")
            .first()
        )

    active_year = get_active_academic_year()
    if not active_year or active_year.id != year.id:
        return None

    archived_year = (
        AcademicYear.objects.filter(status=AcademicYear.STATUS_ARCHIVED)
        .order_by("-start_date", "-id")
        .first()
    )
    if not archived_year:
        return None

    return AcademicTerm.objects.filter(academic_year=archived_year).order_by("-sort_order", "-id").first()


def _school_class_label(school_class):
    section = school_class.section or ""
    label = f"{school_class.grade_level} - {section}".strip(" -")
    return label or school_class.name


def get_pending_adoption_classes(schedule_type, current_term, previous_term):
    if not current_term or not previous_term:
        return []

    current_class_ids = set(
        Schedule.objects.filter(academic_term=current_term, schedule_type=schedule_type).values_list(
            "school_classes__id", flat=True
        )
    )

    pending = []
    seen_class_ids = set()
    previous_schedules = (
        Schedule.objects.filter(academic_term=previous_term, schedule_type=schedule_type)
        .prefetch_related("school_classes")
        .order_by("-updated_at", "-id")
    )
    for schedule in previous_schedules:
        for school_class in schedule.school_classes.all():
            if school_class.id in seen_class_ids or school_class.id in current_class_ids:
                continue
            seen_class_ids.add(school_class.id)
            pending.append(
                {
                    "classId": str(school_class.id),
                    "classLabel": _school_class_label(school_class),
                    "previousScheduleId": str(schedule.id),
                    "previousScheduleName": schedule.name,
                }
            )
    return pending


def copy_schedule_for_class(source_schedule, class_id, target_term):
    if Schedule.objects.filter(
        academic_term=target_term,
        schedule_type=source_schedule.schedule_type,
        school_classes__id=class_id,
    ).exists():
        return None

    new_schedule = Schedule.objects.create(
        name=source_schedule.name,
        schedule_type=source_schedule.schedule_type,
        entries=source_schedule.entries,
        is_published=source_schedule.is_published,
        academic_term=target_term,
    )
    new_schedule.school_classes.set([class_id])
    return new_schedule


def discard_previous_schedule_for_class(class_id, previous_term, schedule_type):
    schedules = Schedule.objects.filter(
        academic_term=previous_term,
        schedule_type=schedule_type,
        school_classes__id=class_id,
    ).prefetch_related("school_classes")

    removed = 0
    for schedule in schedules:
        remaining_ids = list(schedule.school_classes.exclude(id=class_id).values_list("id", flat=True))
        if not remaining_ids:
            schedule.delete()
        else:
            schedule.school_classes.remove(class_id)
        removed += 1
    return removed


def adopt_schedules(class_ids, schedule_type, mode, current_term=None, previous_term=None):
    from academics.term_operational_services import require_operational_term

    mode = normalize_schedule_rollover_mode(mode)
    current_term = current_term or require_operational_term()
    previous_term = previous_term or get_previous_operational_term()

    if not previous_term:
        raise serializers.ValidationError({"detail": "لا توجد جداول سابقة للاعتماد عليها"})
    if not class_ids:
        raise serializers.ValidationError({"classIds": "حدد الشعب المستهدفة"})

    results = []
    for class_id in class_ids:
        if mode == "copy":
            source = (
                Schedule.objects.filter(
                    academic_term=previous_term,
                    schedule_type=schedule_type,
                    school_classes__id=class_id,
                )
                .order_by("-updated_at", "-id")
                .first()
            )
            if not source:
                continue
            created = copy_schedule_for_class(source, class_id, current_term)
            if created:
                results.append({"classId": str(class_id), "scheduleId": str(created.id), "mode": mode})
        else:
            discard_previous_schedule_for_class(class_id, previous_term, schedule_type)
            results.append({"classId": str(class_id), "mode": mode})

    return results


def serialize_schedule_rollover_context(schedule_type=None):
    from config.serializers import ScheduleSerializer

    current_term = get_current_academic_term()
    previous_term = get_previous_operational_term()

    def schedules_for(term):
        if not term:
            return []
        qs = Schedule.objects.filter(academic_term=term).prefetch_related("school_classes").order_by(
            "-updated_at", "-id"
        )
        if schedule_type in ("exam", "class"):
            qs = qs.filter(schedule_type=schedule_type)
        return ScheduleSerializer(qs, many=True).data

    pending = []
    if schedule_type in ("exam", "class"):
        pending = get_pending_adoption_classes(schedule_type, current_term, previous_term)

    return {
        "currentTerm": {
            "id": str(current_term.id),
            "name": term_display_name(current_term),
            "academicYearName": current_term.academic_year.name,
        }
        if current_term
        else None,
        "previousTerm": {
            "id": str(previous_term.id),
            "name": term_display_name(previous_term),
            "academicYearName": previous_term.academic_year.name,
        }
        if previous_term
        else None,
        "currentSchedules": schedules_for(current_term),
        "previousSchedules": schedules_for(previous_term),
        "pendingAdoptions": pending,
    }
