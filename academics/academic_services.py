from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from academics.models import AcademicTerm, AcademicYear, Grade, PromotionPolicy, Student


def get_active_academic_year():
    return AcademicYear.objects.filter(is_active=True).order_by("-start_date").first()


def get_current_academic_term():
    year = get_active_academic_year()
    if not year:
        return None
    term = AcademicTerm.objects.filter(academic_year=year, is_current=True).order_by("sort_order").first()
    if term:
        return term
    return AcademicTerm.objects.filter(academic_year=year).order_by("sort_order").first()


def require_current_academic_term():
    term = get_current_academic_term()
    if not term:
        raise serializers.ValidationError(
            {"detail": "لا يوجد فصل دراسي حالي. يرجى ضبط السنة والفصل من إدارة السنوات الدراسية."}
        )
    return term


def _default_promotion_policy_fields():
    return {
        "evaluation_scope": PromotionPolicy.EVAL_SINGLE_TERM,
        "year_calculation_method": PromotionPolicy.CALC_TERM_AVERAGE,
        "pass_rule": PromotionPolicy.PASS_MINIMUM_COUNT,
        "pass_minimum_count": 1,
        "required_subjects": [],
        "pass_promotion_mode": PromotionPolicy.MODE_AUTOMATIC,
        "fail_handling_mode": PromotionPolicy.FAIL_MANUAL_REVIEW,
    }


def get_promotion_policy_for_grade(grade: Grade) -> PromotionPolicy:
    policy, _ = PromotionPolicy.objects.get_or_create(
        grade=grade,
        defaults=_default_promotion_policy_fields(),
    )
    return policy


def ensure_grade_promotion_policies():
    for grade in Grade.objects.order_by("sort_order", "id"):
        get_promotion_policy_for_grade(grade)


def get_promotion_policy_for_student(student: Student) -> PromotionPolicy:
    grade = Grade.objects.filter(name=student.grade_level).order_by("sort_order", "id").first()
    if grade:
        return get_promotion_policy_for_grade(grade)
    fallback = Grade.objects.order_by("sort_order", "id").first()
    if fallback:
        return get_promotion_policy_for_grade(fallback)
    raise serializers.ValidationError(
        {"detail": "لا توجد صفوف دراسية. يرجى إضافة الصفوف من إدارة الفصول."}
    )


@transaction.atomic
def ensure_default_academic_calendar():
    year = AcademicYear.objects.filter(is_active=True).first()
    if year:
        if not AcademicTerm.objects.filter(academic_year=year).exists():
            _create_default_terms(year)
        return year

    existing = AcademicYear.objects.order_by("-start_date").first()
    if existing:
        if not existing.is_active and existing.status != AcademicYear.STATUS_ARCHIVED:
            existing.is_active = True
            existing.status = AcademicYear.STATUS_ACTIVE
            existing.save(update_fields=["is_active", "status"])
        if not AcademicTerm.objects.filter(academic_year=existing).exists():
            _create_default_terms(existing)
        return existing

    today = timezone.localdate()
    year = AcademicYear.objects.create(
        name=_default_year_name(today),
        start_date=date(today.year, 9, 1),
        end_date=date(today.year + 1, 6, 30),
        status=AcademicYear.STATUS_ACTIVE,
        is_active=True,
    )
    _create_default_terms(year, mark_first_current=True)
    return year


def _default_year_name(today: date | None = None):
    today = today or timezone.localdate()
    if today.month >= 9:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _create_default_terms(year, mark_first_current=False):
    start_year = year.start_date.year
    term_one = AcademicTerm.objects.create(
        academic_year=year,
        name="الفصل الأول",
        sort_order=1,
        start_date=date(start_year, 9, 1),
        end_date=date(start_year, 1, 31),
        is_current=mark_first_current,
    )
    AcademicTerm.objects.create(
        academic_year=year,
        name="الفصل الثاني",
        sort_order=2,
        start_date=date(start_year, 2, 1),
        end_date=year.end_date,
        is_current=False,
    )
    if mark_first_current:
        set_current_academic_term(term_one)
    return term_one


@transaction.atomic
def set_active_academic_year(year: AcademicYear):
    AcademicYear.objects.exclude(id=year.id).update(is_active=False, status=AcademicYear.STATUS_ARCHIVED)
    year.is_active = True
    year.status = AcademicYear.STATUS_ACTIVE
    year.save(update_fields=["is_active", "status"])
    if not AcademicTerm.objects.filter(academic_year=year).exists():
        _create_default_terms(year, mark_first_current=True)
    elif not AcademicTerm.objects.filter(academic_year=year, is_current=True).exists():
        first_term = AcademicTerm.objects.filter(academic_year=year).order_by("sort_order").first()
        if first_term:
            set_current_academic_term(first_term)


@transaction.atomic
def set_current_academic_term(term: AcademicTerm):
    AcademicTerm.objects.filter(academic_year=term.academic_year).exclude(id=term.id).update(is_current=False)
    term.is_current = True
    term.save(update_fields=["is_current"])
    if not term.academic_year.is_active:
        set_active_academic_year(term.academic_year)


def serialize_academic_term(term: AcademicTerm):
    return {
        "id": str(term.id),
        "academicYearId": str(term.academic_year_id),
        "name": term.name,
        "sortOrder": term.sort_order,
        "startDate": term.start_date.isoformat(),
        "endDate": term.end_date.isoformat(),
        "isCurrent": term.is_current,
    }


def serialize_promotion_policy(policy: PromotionPolicy):
    return {
        "gradeId": str(policy.grade_id),
        "evaluationScope": policy.evaluation_scope,
        "yearCalculationMethod": policy.year_calculation_method,
        "evaluationTermId": str(policy.evaluation_term_id) if policy.evaluation_term_id else None,
        "passRule": policy.pass_rule,
        "passMinimumCount": policy.pass_minimum_count,
        "requiredSubjects": policy.required_subjects or [],
        "passScoreRatio": float(policy.pass_score_ratio),
        "passPromotionMode": policy.pass_promotion_mode,
        "failHandlingMode": policy.fail_handling_mode,
        "updatedAt": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def serialize_academic_year(year: AcademicYear):
    terms = [serialize_academic_term(term) for term in year.terms.order_by("sort_order", "id")]
    current_term = next((term for term in terms if term["isCurrent"]), terms[0] if terms else None)
    return {
        "id": str(year.id),
        "name": year.name,
        "startDate": year.start_date.isoformat(),
        "endDate": year.end_date.isoformat(),
        "status": year.status,
        "isActive": year.is_active,
        "terms": terms,
        "currentTermId": current_term["id"] if current_term else None,
        "createdAt": year.created_at.isoformat() if year.created_at else None,
    }


def serialize_academic_context():
    year = get_active_academic_year() or ensure_default_academic_calendar()
    term = get_current_academic_term()
    return {
        "academicYear": serialize_academic_year(year) if year else None,
        "currentTerm": serialize_academic_term(term) if term else None,
    }
