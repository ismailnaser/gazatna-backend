from django.utils import timezone

from assignments.models import AssignmentStatus


def homework_is_open(homework, now=None):
    if homework.status == AssignmentStatus.CLOSED:
        return False
    now = now or timezone.now()
    if homework.start_at and now < homework.start_at:
        return False
    if homework.end_at and now > homework.end_at:
        return False
    return True


def homework_window_status(homework, now=None):
    if homework.status == AssignmentStatus.CLOSED:
        return "closed"
    now = now or timezone.now()
    if homework.start_at and now < homework.start_at:
        return "scheduled"
    if homework.end_at and now > homework.end_at:
        return "ended"
    return "active"
