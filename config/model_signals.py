from __future__ import annotations

from django.db.models.signals import post_delete, post_save

from config.events import emit


def _connect(model, event_name: str):
    def _handler(sender, instance, **kwargs):
        emit(event_name, model=sender.__name__, pk=getattr(instance, "pk", None))

    post_save.connect(_handler, sender=model, weak=False)
    post_delete.connect(_handler, sender=model, weak=False)


def register() -> None:
    from academics.models import AcademicTerm, AcademicYear, Grade, SchoolClass, Student
    from content.models import (
        NewsItem,
        Program,
        SchoolStat,
        SchoolValue,
        SiteSettings,
    )
    from finance.models import FeePlan, PaymentNotice, StudentFeeBalance
    from staff.models import TeacherProfile

    for model in (
        NewsItem,
        Program,
        SchoolStat,
        SchoolValue,
        SiteSettings,
    ):
        _connect(model, "content.changed")

    _connect(TeacherProfile, "staff.changed")

    for model in (Grade, SchoolClass, Student, AcademicYear, AcademicTerm):
        _connect(model, "academics.changed")

    for model in (FeePlan, PaymentNotice, StudentFeeBalance):
        _connect(model, "finance.changed")

    def _site_settings_handler(sender, instance, **kwargs):
        emit("site_settings.changed", pk=getattr(instance, "pk", None))

    post_save.connect(_site_settings_handler, sender=SiteSettings, weak=False)
