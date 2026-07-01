from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from academics.academic_services import get_active_academic_year, get_current_academic_term, term_display_name
from academics.models import (
    CertificateConfig,
    ClassSubjectAssignment,
    SubjectGrade,
)

PARENT_CERTIFICATE_GRACE_DAYS = 14


def _certificate_grace_anchor_date(term, config: CertificateConfig):
    if term.closed_at:
        return timezone.localdate(term.closed_at)
    if config.published_term_id == term.id and config.term_published_at:
        return timezone.localdate(config.term_published_at)
    return None


def _term_certificate_in_grace_window(term, config: CertificateConfig) -> bool:
    if not term or not term.is_closed or not config.is_term_published:
        return False
    anchor = _certificate_grace_anchor_date(term, config)
    if not anchor:
        return False
    last_visible = anchor + timedelta(days=PARENT_CERTIFICATE_GRACE_DAYS - 1)
    return timezone.localdate() <= last_visible


def _certificate_visible_until(term, config: CertificateConfig):
    anchor = _certificate_grace_anchor_date(term, config)
    if not anchor:
        return None
    return (anchor + timedelta(days=PARENT_CERTIFICATE_GRACE_DAYS - 1)).isoformat()


def _year_last_term_id(config: CertificateConfig):
    return config.academic_year.terms.order_by("-sort_order", "-id").values_list("id", flat=True).first()


def _term_certificates_for_parent_main_section(config: CertificateConfig, current_term):
    if not config or not config.is_term_published:
        return []

    terms = []
    seen = set()
    published_term = config.published_term
    last_term_id = _year_last_term_id(config) if config.is_year_published else None

    if (
        current_term
        and not current_term.is_closed
        and published_term
        and published_term.id == current_term.id
        and current_term.academic_year_id == config.academic_year_id
    ):
        terms.append(current_term)
        seen.add(current_term.id)

    for term in config.academic_year.terms.filter(is_closed=True).order_by("sort_order", "id"):
        if last_term_id and term.id == last_term_id:
            continue
        if term.id in seen:
            continue
        if _term_certificate_in_grace_window(term, config):
            terms.append(term)
            seen.add(term.id)

    return terms


def _term_certificates_for_parent_archive(config: CertificateConfig):
    if not config or not config.is_term_published:
        return []

    last_term_id = _year_last_term_id(config) if config.is_year_published else None
    archived = []
    for term in config.academic_year.terms.filter(is_closed=True).order_by("sort_order", "id"):
        if last_term_id and term.id == last_term_id:
            continue
        if _term_certificate_in_grace_window(term, config):
            continue
        archived.append(term)
    return archived


def default_honors_message():
    return (
        "تقديراً للتميز والاجتهاد، تُمنح هذه الشهادة اعترافاً بالمعدل العالي "
        "والأداء المتميز طوال الفترة الدراسية."
    )


def get_or_create_certificate_config(year):
    config, _ = CertificateConfig.objects.get_or_create(
        academic_year=year,
        defaults={
            "honors_message": default_honors_message(),
        },
    )
    return config


def assigned_subject_names(student, terms=None):
    if terms:
        graded = list(
            SubjectGrade.objects.filter(student=student, academic_term__in=terms)
            .order_by("subject")
            .values_list("subject", flat=True)
            .distinct()
        )
        if graded:
            return graded

    if not student.school_class_id:
        return list(
            SubjectGrade.objects.filter(student=student)
            .order_by("subject")
            .values_list("subject", flat=True)
            .distinct()
        )

    from academics.academic_services import get_current_academic_term

    term = get_current_academic_term()
    assignment_qs = ClassSubjectAssignment.objects.filter(school_class=student.school_class)
    if term:
        assignment_qs = assignment_qs.filter(academic_term=term)
    names = list(
        assignment_qs.select_related("subject")
        .order_by("subject__name")
        .values_list("subject__name", flat=True)
    )
    if names:
        return names
    return list(
        SubjectGrade.objects.filter(student=student)
        .order_by("subject")
        .values_list("subject", flat=True)
        .distinct()
    )


def _terms_for_certificate(config: CertificateConfig, preview_term=None, scope=None):
    year = config.academic_year
    effective_scope = scope or config.issuance_scope
    if effective_scope == CertificateConfig.SCOPE_TERM:
        term = preview_term or config.published_term or get_current_academic_term()
        return [term] if term and term.academic_year_id == year.id else []
    return list(year.terms.order_by("sort_order", "id"))


def _subject_percent_for_terms(student, subject_name, terms):
    grades = list(
        SubjectGrade.objects.filter(
            student=student,
            subject=subject_name,
            academic_term__in=terms,
        )
    )
    if not grades:
        return None, None, None

    percents = []
    score_total = Decimal("0")
    max_total = Decimal("0")
    for grade in grades:
        max_score = Decimal(str(grade.max_score))
        if max_score <= 0:
            continue
        score = Decimal(str(grade.score))
        percents.append(float(score / max_score * 100))
        score_total += score
        max_total += max_score

    if not percents:
        return None, None, None

    if len(percents) == 1:
        percent = percents[0]
        return float(score_total), float(max_total), round(percent, 2)

    percent = round(sum(percents) / len(percents), 2)
    return float(score_total), float(max_total), percent


def compute_student_certificate(student, config: CertificateConfig, preview_term=None, scope=None):
    effective_scope = scope or config.issuance_scope
    terms = _terms_for_certificate(config, preview_term=preview_term, scope=effective_scope)
    period_label = _period_label(config, terms, scope=effective_scope)
    subjects = []

    for subject_name in assigned_subject_names(student, terms=terms):
        score, max_score, percent = _subject_percent_for_terms(student, subject_name, terms)
        subjects.append(
            {
                "subject": subject_name,
                "score": round(score, 2) if score is not None else None,
                "maxScore": round(max_score, 2) if max_score is not None else None,
                "percent": percent,
                "hasGrade": percent is not None,
            }
        )

    graded = [item for item in subjects if item["percent"] is not None]
    average = round(sum(item["percent"] for item in graded) / len(graded), 2) if graded else None
    honors_min = float(config.honors_min_average or 0)
    qualifies_honors = bool(
        config.honors_enabled and average is not None and average >= honors_min
    )

    return {
        "studentId": str(student.id),
        "studentName": student.name,
        "studentNumber": student.student_number or "",
        "gradeLevel": student.grade_level,
        "section": student.section or "",
        "periodLabel": period_label,
        "subjects": subjects,
        "gradedSubjectsCount": len(graded),
        "assignedSubjectsCount": len(subjects),
        "averagePercent": average,
        "qualifiesHonors": qualifies_honors,
        "honorsMinAverage": honors_min,
    }


def _period_label(config: CertificateConfig, terms, scope=None):
    effective_scope = scope or config.issuance_scope
    if effective_scope == CertificateConfig.SCOPE_YEAR:
        return f"السنة الدراسية {config.academic_year.name}"
    if terms:
        return f"{term_display_name(terms[0])} — {config.academic_year.name}"
    return config.academic_year.name


def _certificate_scope_label(scope, config: CertificateConfig, terms):
    if scope == CertificateConfig.SCOPE_YEAR:
        return f"شهادة نهاية السنة الدراسية {config.academic_year.name}"
    if terms:
        return f"شهادة {term_display_name(terms[0])}"
    return config.certificate_title


def _honors_scope_label(scope, config: CertificateConfig, terms):
    if scope == CertificateConfig.SCOPE_YEAR:
        return f"شهادة تقدير نهاية السنة {config.academic_year.name}"
    if terms:
        return f"شهادة تقدير {term_display_name(terms[0])}"
    return config.honors_title


def _sync_publish_flags(config: CertificateConfig, user=None, published_at=None):
    now = published_at or timezone.now()
    config.is_published = bool(config.is_term_published or config.is_year_published)
    if config.is_published:
        timestamps = [value for value in (config.term_published_at, config.year_published_at) if value]
        config.published_at = max(timestamps) if timestamps else now
        if user and getattr(user, "is_authenticated", False):
            config.published_by = user
    else:
        config.published_at = None
        config.published_by = None


def serialize_certificate_config(config: CertificateConfig):
    return {
        "academicYearId": str(config.academic_year_id),
        "issuanceScope": config.issuance_scope,
        "isPublished": config.is_published,
        "publishedAt": config.published_at.isoformat() if config.published_at else None,
        "isTermPublished": config.is_term_published,
        "termPublishedAt": config.term_published_at.isoformat() if config.term_published_at else None,
        "isYearPublished": config.is_year_published,
        "yearPublishedAt": config.year_published_at.isoformat() if config.year_published_at else None,
        "publishedTermId": str(config.published_term_id) if config.published_term_id else None,
        "honorsEnabled": config.honors_enabled,
        "honorsMinAverage": float(config.honors_min_average),
        "honorsTitle": config.honors_title,
        "honorsMessage": config.honors_message,
        "certificateTitle": config.certificate_title,
        "updatedAt": config.updated_at.isoformat() if config.updated_at else None,
    }


def _serialize_parent_certificate_entry(student, config: CertificateConfig, scope, preview_term=None):
    terms = _terms_for_certificate(config, preview_term=preview_term, scope=scope)
    certificate = compute_student_certificate(student, config, preview_term=preview_term, scope=scope)
    payload = {
        "scope": scope,
        "academicYearId": str(config.academic_year_id),
        "academicYearName": config.academic_year.name,
        "scopeLabel": _certificate_scope_label(scope, config, terms),
        "honorsTitle": _honors_scope_label(scope, config, terms),
        "certificate": certificate,
        "config": serialize_certificate_config(config),
    }
    if scope == CertificateConfig.SCOPE_TERM and preview_term and preview_term.is_closed:
        visible_until = _certificate_visible_until(preview_term, config)
        if visible_until and _term_certificate_in_grace_window(preview_term, config):
            payload["visibleUntil"] = visible_until
            payload["archiveAfterGrace"] = True
    return payload


def certificate_configs_for_student(student):
    from academics.models import AcademicYear, CertificateConfig, Enrollment

    configs = []
    seen_year_ids = set()

    active = get_active_academic_year()
    if active:
        config = (
            CertificateConfig.objects.filter(academic_year=active)
            .select_related("academic_year", "published_term")
            .first()
        )
        if config and config.is_published:
            configs.append(config)
            seen_year_ids.add(active.id)

    enrollment_names = Enrollment.objects.filter(student=student).values_list("academic_year", flat=True)
    archived_configs = (
        CertificateConfig.objects.filter(
            academic_year__name__in=enrollment_names,
            is_published=True,
        )
        .exclude(academic_year_id__in=seen_year_ids)
        .select_related("academic_year", "published_term")
        .order_by("-academic_year__start_date", "-id")
    )
    configs.extend(archived_configs)
    return configs


def _certificate_entries_for_config(student, config: CertificateConfig, *, archive_only=False, current_only=False):
    if not config or not config.is_published:
        return []

    entries = []
    current_term = get_current_academic_term()
    published_term = config.published_term if config.is_term_published else None

    if config.is_term_published:
        if archive_only:
            for term in _term_certificates_for_parent_archive(config):
                entries.append(
                    _serialize_parent_certificate_entry(
                        student,
                        config,
                        CertificateConfig.SCOPE_TERM,
                        preview_term=term,
                    )
                )
        elif current_only:
            for term in _term_certificates_for_parent_main_section(config, current_term):
                entries.append(
                    _serialize_parent_certificate_entry(
                        student,
                        config,
                        CertificateConfig.SCOPE_TERM,
                        preview_term=term,
                    )
                )
        elif published_term:
            entries.append(
                _serialize_parent_certificate_entry(
                    student,
                    config,
                    CertificateConfig.SCOPE_TERM,
                    preview_term=published_term,
                )
            )

    if config.is_year_published:
        include_year = archive_only or (not archive_only and not current_only)
        if current_only:
            include_year = False
        if include_year:
            entries.append(
                _serialize_parent_certificate_entry(student, config, CertificateConfig.SCOPE_YEAR)
            )

    if not entries and not archive_only and not current_only:
        entries.append(
            _serialize_parent_certificate_entry(student, config, config.issuance_scope)
        )

    return entries


def _assemble_parent_certificate_payload(student, entries, fallback_config=None):
    if not entries:
        return {
            "published": False,
            "message": "لم تصدر الإدارة الشهادات بعد.",
            "config": serialize_certificate_config(fallback_config) if fallback_config else None,
            "certificate": None,
            "certificates": [],
        }

    primary = entries[-1]["certificate"]
    return {
        "published": True,
        "message": "",
        "config": entries[-1].get("config") or (
            serialize_certificate_config(fallback_config) if fallback_config else None
        ),
        "certificate": primary,
        "certificates": entries,
    }


def serialize_parent_current_certificates(student):
    active = get_active_academic_year()
    config = None
    entries = []
    if active:
        from academics.models import CertificateConfig

        config = CertificateConfig.objects.filter(academic_year=active).select_related(
            "academic_year", "published_term"
        ).first()
        if config and config.is_published:
            entries.extend(_certificate_entries_for_config(student, config, current_only=True))

    if not entries:
        return {
            "published": False,
            "message": (
                "لا توجد شهادات معروضة حالياً. بعد إغلاق الفصل تبقى شهادته هنا لمدة أسبوعين "
                "ثم تنتقل تلقائياً إلى أرشيف الشهادات."
            ),
            "config": serialize_certificate_config(config) if config else None,
            "certificate": None,
            "certificates": [],
        }

    return _assemble_parent_certificate_payload(student, entries, config)


def serialize_parent_archived_certificates(student):
    configs = certificate_configs_for_student(student)
    entries = []
    for config in configs:
        entries.extend(_certificate_entries_for_config(student, config, archive_only=True))

    if not entries:
        return {
            "published": False,
            "message": "لا توجد شهادات مؤرشفة بعد.",
            "config": None,
            "certificate": None,
            "certificates": [],
        }

    return _assemble_parent_certificate_payload(student, entries, configs[0] if configs else None)


def serialize_parent_all_certificates(student):
    configs = certificate_configs_for_student(student)
    if not configs:
        return {
            "published": False,
            "message": "لم تصدر الإدارة الشهادات بعد.",
            "config": None,
            "certificate": None,
            "certificates": [],
        }

    certificates = []
    for config in configs:
        certificates.extend(_certificate_entries_for_config(student, config))

    if not certificates:
        return {
            "published": False,
            "message": "لم تصدر الإدارة الشهادات بعد.",
            "config": serialize_certificate_config(configs[0]),
            "certificate": None,
            "certificates": [],
        }

    return _assemble_parent_certificate_payload(student, certificates, configs[0])


def serialize_parent_certificates(student, config: CertificateConfig | None):
    if not config or not config.is_published:
        return {
            "published": False,
            "message": "لم تصدر الإدارة الشهادات بعد.",
            "config": serialize_certificate_config(config) if config else None,
            "certificate": None,
            "certificates": [],
        }

    entries = _certificate_entries_for_config(student, config)
    return _assemble_parent_certificate_payload(student, entries, config)


@transaction.atomic
def update_certificate_config(year, payload):
    config = get_or_create_certificate_config(year)
    mapping = {
        "issuanceScope": "issuance_scope",
        "honorsEnabled": "honors_enabled",
        "honorsMinAverage": "honors_min_average",
        "honorsTitle": "honors_title",
        "honorsMessage": "honors_message",
        "certificateTitle": "certificate_title",
    }
    for key, field in mapping.items():
        if key in payload:
            setattr(config, field, payload[key])

    if "publishedTermId" in payload:
        term_id = payload.get("publishedTermId")
        if term_id:
            from academics.models import AcademicTerm

            term = AcademicTerm.objects.filter(id=term_id, academic_year=year).first()
            if not term:
                raise serializers.ValidationError({"publishedTermId": "الفصل غير صالح"})
            config.published_term = term
        else:
            config.published_term = None

    config.save()
    return config


@transaction.atomic
def publish_term_certificates(year, user, term_id=None):
    from academics.models import AcademicTerm

    config = get_or_create_certificate_config(year)
    if not year.is_active:
        raise serializers.ValidationError({"detail": "يمكن إصدار الشهادات للسنة النشطة فقط"})

    term = None
    if term_id:
        term = AcademicTerm.objects.filter(id=term_id, academic_year=year).first()
    if not term:
        term = get_current_academic_term()
    if not term or term.academic_year_id != year.id:
        raise serializers.ValidationError({"termId": "حدد الفصل الدراسي لإصدار الشهادات"})

    now = timezone.now()
    config.issuance_scope = CertificateConfig.SCOPE_TERM
    config.published_term = term
    config.is_term_published = True
    config.term_published_at = now
    _sync_publish_flags(config, user=user, published_at=now)
    config.save()
    return config


@transaction.atomic
def publish_year_certificates(year, user):
    config = get_or_create_certificate_config(year)
    if not year.is_active:
        raise serializers.ValidationError({"detail": "يمكن إصدار الشهادات للسنة النشطة فقط"})

    now = timezone.now()
    config.issuance_scope = CertificateConfig.SCOPE_YEAR
    config.is_year_published = True
    config.year_published_at = now
    _sync_publish_flags(config, user=user, published_at=now)
    config.save()
    return config


@transaction.atomic
def publish_year_end_certificates(year, user, term=None):
    config = get_or_create_certificate_config(year)
    if not year.is_active:
        raise serializers.ValidationError({"detail": "يمكن إصدار الشهادات للسنة النشطة فقط"})

    now = timezone.now()
    config.is_year_published = True
    config.year_published_at = now
    config.issuance_scope = CertificateConfig.SCOPE_YEAR
    if not (config.certificate_title or "").strip():
        config.certificate_title = f"شهادة نهاية السنة {year.name}"
    if not (config.honors_title or "").strip() or config.honors_title == "شهادة تقدير":
        config.honors_title = f"شهادة تقدير نهاية السنة {year.name}"
    _sync_publish_flags(config, user=user, published_at=now)
    config.save()
    return config


@transaction.atomic
def publish_certificates(year, user, term_id=None):
    config = get_or_create_certificate_config(year)
    if config.issuance_scope == CertificateConfig.SCOPE_YEAR:
        return publish_year_certificates(year, user)
    return publish_term_certificates(year, user, term_id=term_id)


@transaction.atomic
def unpublish_certificates(year):
    config = get_or_create_certificate_config(year)
    config.is_published = False
    config.published_at = None
    config.published_by = None
    config.is_term_published = False
    config.term_published_at = None
    config.is_year_published = False
    config.year_published_at = None
    config.save()
    return config


def active_certificate_config():
    year = get_active_academic_year()
    if not year:
        return None
    return get_or_create_certificate_config(year)


def _build_preview_context(config: CertificateConfig, overrides=None):
    overrides = overrides or {}
    from academics.models import AcademicTerm

    preview_term = config.published_term
    if overrides.get("termId"):
        preview_term = AcademicTerm.objects.filter(
            id=overrides["termId"],
            academic_year=config.academic_year,
        ).first()
    elif config.issuance_scope == CertificateConfig.SCOPE_TERM and not preview_term:
        preview_term = get_current_academic_term()

    class PreviewContext:
        pass

    ctx = PreviewContext()
    ctx.academic_year = config.academic_year
    ctx.academic_year_id = config.academic_year_id
    ctx.issuance_scope = overrides.get("issuanceScope", config.issuance_scope)
    ctx.published_term = preview_term
    ctx.published_term_id = preview_term.id if preview_term else None
    ctx.honors_enabled = overrides.get("honorsEnabled", config.honors_enabled)
    ctx.honors_min_average = overrides.get("honorsMinAverage", config.honors_min_average)
    ctx.honors_title = overrides.get("honorsTitle", config.honors_title)
    ctx.honors_message = overrides.get("honorsMessage", config.honors_message)
    ctx.certificate_title = overrides.get("certificateTitle", config.certificate_title)
    ctx.is_published = config.is_published
    ctx.published_at = config.published_at
    ctx.published_by = config.published_by
    ctx.updated_at = config.updated_at
    return ctx, preview_term


def _serialize_preview_config(ctx: CertificateConfig):
    return {
        "academicYearId": str(ctx.academic_year_id),
        "issuanceScope": ctx.issuance_scope,
        "isPublished": ctx.is_published,
        "publishedAt": ctx.published_at.isoformat() if ctx.published_at else None,
        "publishedTermId": str(ctx.published_term_id) if ctx.published_term_id else None,
        "honorsEnabled": ctx.honors_enabled,
        "honorsMinAverage": float(ctx.honors_min_average),
        "honorsTitle": ctx.honors_title,
        "honorsMessage": ctx.honors_message,
        "certificateTitle": ctx.certificate_title,
        "updatedAt": ctx.updated_at.isoformat() if ctx.updated_at else None,
    }


def preview_certificates(year, overrides=None):
    from academics.models import Student

    if not year.is_active:
        raise serializers.ValidationError({"detail": "معاينة الشهادات متاحة للسنة النشطة فقط"})

    config = get_or_create_certificate_config(year)
    ctx, preview_term = _build_preview_context(config, overrides)
    terms = _terms_for_certificate(ctx, preview_term=preview_term)

    if ctx.issuance_scope == CertificateConfig.SCOPE_TERM and not terms:
        raise serializers.ValidationError({"termId": "حدد الفصل الدراسي لمعاينة الشهادات"})

    students = Student.objects.filter(is_active=True).select_related("school_class").order_by(
        "grade_level", "section", "name"
    )

    rows = []
    summary = {
        "total": 0,
        "withAverage": 0,
        "withoutAverage": 0,
        "honors": 0,
    }

    for student in students:
        row = compute_student_certificate(student, ctx, preview_term=preview_term)
        rows.append(row)
        summary["total"] += 1
        if row["averagePercent"] is not None:
            summary["withAverage"] += 1
        else:
            summary["withoutAverage"] += 1
        if row["qualifiesHonors"]:
            summary["honors"] += 1

    period_label = _period_label(ctx, terms)

    return {
        "academicYearId": str(year.id),
        "academicYearName": year.name,
        "periodLabel": period_label,
        "config": _serialize_preview_config(ctx),
        "summary": summary,
        "students": rows,
    }
