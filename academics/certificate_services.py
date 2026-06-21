from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from academics.academic_services import get_active_academic_year, get_current_academic_term
from academics.models import (
    CertificateConfig,
    ClassSubjectAssignment,
    SubjectGrade,
)


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


def assigned_subject_names(student):
    if not student.school_class_id:
        return []
    names = list(
        ClassSubjectAssignment.objects.filter(school_class=student.school_class)
        .select_related("subject")
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


def _terms_for_certificate(config: CertificateConfig, preview_term=None):
    year = config.academic_year
    if config.issuance_scope == CertificateConfig.SCOPE_TERM:
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


def compute_student_certificate(student, config: CertificateConfig, preview_term=None):
    terms = _terms_for_certificate(config, preview_term=preview_term)
    period_label = _period_label(config, terms)
    subjects = []

    for subject_name in assigned_subject_names(student):
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


def _period_label(config: CertificateConfig, terms):
    if config.issuance_scope == CertificateConfig.SCOPE_YEAR:
        return f"السنة الدراسية {config.academic_year.name}"
    if terms:
        return f"{terms[0].name} — {config.academic_year.name}"
    return config.academic_year.name


def serialize_certificate_config(config: CertificateConfig):
    return {
        "academicYearId": str(config.academic_year_id),
        "issuanceScope": config.issuance_scope,
        "isPublished": config.is_published,
        "publishedAt": config.published_at.isoformat() if config.published_at else None,
        "publishedTermId": str(config.published_term_id) if config.published_term_id else None,
        "honorsEnabled": config.honors_enabled,
        "honorsMinAverage": float(config.honors_min_average),
        "honorsTitle": config.honors_title,
        "honorsMessage": config.honors_message,
        "certificateTitle": config.certificate_title,
        "updatedAt": config.updated_at.isoformat() if config.updated_at else None,
    }


def serialize_parent_certificates(student, config: CertificateConfig | None):
    if not config or not config.is_published:
        return {
            "published": False,
            "message": "لم تصدر الإدارة الشهادات بعد.",
            "config": serialize_certificate_config(config) if config else None,
            "certificate": None,
        }

    certificate = compute_student_certificate(student, config)
    return {
        "published": True,
        "message": "",
        "config": serialize_certificate_config(config),
        "certificate": certificate,
    }


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
def publish_certificates(year, user, term_id=None):
    config = get_or_create_certificate_config(year)
    if not year.is_active:
        raise serializers.ValidationError({"detail": "يمكن إصدار الشهادات للسنة النشطة فقط"})

    if config.issuance_scope == CertificateConfig.SCOPE_TERM:
        from academics.models import AcademicTerm

        term = None
        if term_id:
            term = AcademicTerm.objects.filter(id=term_id, academic_year=year).first()
        if not term:
            term = get_current_academic_term()
        if not term or term.academic_year_id != year.id:
            raise serializers.ValidationError({"termId": "حدد الفصل الدراسي لإصدار الشهادات"})
        config.published_term = term

    config.is_published = True
    config.published_at = timezone.now()
    config.published_by = user if getattr(user, "is_authenticated", False) else None
    config.save()
    return config


@transaction.atomic
def unpublish_certificates(year):
    config = get_or_create_certificate_config(year)
    config.is_published = False
    config.published_at = None
    config.published_by = None
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
