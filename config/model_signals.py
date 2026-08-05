from __future__ import annotations

from django.db.models.signals import post_delete, post_save

from config.events import emit

_registered = False


def _connect(model, event_name: str):
    def _handler(sender, instance, **kwargs):
        emit(event_name, model=sender.__name__, pk=getattr(instance, "pk", None))

    post_save.connect(_handler, sender=model, weak=False, dispatch_uid=f"ghazatna.{event_name}.{model._meta.label}.save")
    post_delete.connect(_handler, sender=model, weak=False, dispatch_uid=f"ghazatna.{event_name}.{model._meta.label}.delete")


def register() -> None:
    global _registered
    if _registered:
        return
    _registered = True

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
    ):
        _connect(model, "content.changed")

    _connect(TeacherProfile, "staff.changed")

    for model in (Grade, SchoolClass, Student, AcademicYear, AcademicTerm):
        _connect(model, "academics.changed")

    for model in (FeePlan, PaymentNotice, StudentFeeBalance):
        _connect(model, "finance.changed")

    def _site_settings_handler(sender, instance, **kwargs):
        emit("site_settings.changed", pk=getattr(instance, "pk", None))

    post_save.connect(
        _site_settings_handler,
        sender=SiteSettings,
        weak=False,
        dispatch_uid="ghazatna.site_settings.save",
    )
    post_delete.connect(
        _site_settings_handler,
        sender=SiteSettings,
        weak=False,
        dispatch_uid="ghazatna.site_settings.delete",
    )
