from datetime import date, timedelta
import re

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from academics.models import AcademicTerm, AcademicYear, Grade, PromotionPolicy, Student

TERM_ORDINALS = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس"]
_AUTO_TERM_CODE = re.compile(r"^T\d+$", re.I)


def term_display_name(term):
    name = (term.name or "").strip()
    if not name or _AUTO_TERM_CODE.match(name):
        ordinal = (
            TERM_ORDINALS[term.sort_order - 1]
            if 1 <= term.sort_order <= len(TERM_ORDINALS)
            else str(term.sort_order)
        )
        return f"الفصل {ordinal}"
    return name


def validate_academic_terms(year: AcademicYear, terms_data: list[dict]):
    """Ensure term dates stay within the academic year and do not overlap."""
    if not terms_data:
        raise serializers.ValidationError({"terms": "يجب تحديد فصل دراسي واحد على الأقل"})

    sorted_terms = sorted(terms_data, key=lambda item: item["sortOrder"])
    year_start = year.start_date
    year_end = year.end_date

    for item in sorted_terms:
        name = str(item.get("name") or "الفصل").strip() or "الفصل"
        start = item["startDate"]
        end = item["endDate"]

        if end < start:
            raise serializers.ValidationError(
                {"terms": f"تاريخ نهاية «{name}» يجب أن يكون بعد تاريخ البداية"}
            )
        if start < year_start:
            raise serializers.ValidationError(
                {
                    "terms": (
                        f"بداية «{name}» يجب أن تكون ضمن السنة الدراسية "
                        f"({year_start.isoformat()} — {year_end.isoformat()})"
                    )
                }
            )
        if end > year_end:
            raise serializers.ValidationError(
                {
                    "terms": (
                        f"نهاية «{name}» يجب أن تكون ضمن السنة الدراسية "
                        f"({year_start.isoformat()} — {year_end.isoformat()})"
                    )
                }
            )

    for index in range(1, len(sorted_terms)):
        previous = sorted_terms[index - 1]
        current = sorted_terms[index]
        prev_name = str(previous.get("name") or "الفصل السابق").strip() or "الفصل السابق"
        curr_name = str(current.get("name") or "الفصل").strip() or "الفصل"
        if current["startDate"] <= previous["endDate"]:
            next_allowed = previous["endDate"] + timedelta(days=1)
            raise serializers.ValidationError(
                {
                    "terms": (
                        f"«{curr_name}» يتداخل مع «{prev_name}». "
                        f"يجب أن يبدأ في {next_allowed.isoformat()} أو بعده."
                    )
                }
            )


def get_active_academic_year():
    return AcademicYear.objects.filter(is_active=True).order_by("-start_date").first()


def get_current_academic_term():
    year = get_active_academic_year()
    if not year:
        return None
    term = (
        AcademicTerm.objects.filter(academic_year=year, is_current=True, is_closed=False)
        .order_by("sort_order")
        .first()
    )
    if term:
        return term
    return activate_due_academic_term(year)


def _all_prior_terms_closed(term: AcademicTerm, ordered_terms) -> bool:
    for item in ordered_terms:
        if item.id == term.id:
            return True
        if not item.is_closed:
            return False
    return True


@transaction.atomic
def activate_due_academic_term(year: AcademicYear | None = None, *, reset_grades=True):
    """Promote the next open term to current when its start date has arrived."""
    year = year or get_active_academic_year()
    if not year:
        return None

    today = timezone.localdate()
    ordered_terms = list(year.terms.order_by("sort_order", "id"))
    for term in ordered_terms:
        if term.is_closed or term.start_date > today:
            continue
        if not _all_prior_terms_closed(term, ordered_terms):
            continue
        was_current = term.is_current
        set_current_academic_term(term)
        if reset_grades and not was_current:
            from academics.grade_reset_services import reset_grade_inputs_for_term

            reset_grade_inputs_for_term(term)
        return term
    return None


def next_term_activates_on_closure(closing_term: AcademicTerm, following_term: AcademicTerm) -> bool:
    return closing_term.end_date == following_term.start_date


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


def ensure_default_academic_calendar():
    """Return the active academic year if configured; never auto-create calendar data."""
    return get_active_academic_year()


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
    activate_due_academic_term(year)


@transaction.atomic
def set_current_academic_term(term: AcademicTerm):
    if term.is_closed:
        raise serializers.ValidationError({"detail": "لا يمكن تعيين فصل مُغلق كفصل حالي"})
    AcademicTerm.objects.filter(academic_year=term.academic_year).exclude(id=term.id).update(is_current=False)
    term.is_current = True
    term.save(update_fields=["is_current"])


def serialize_academic_term(term: AcademicTerm):
    return {
        "id": str(term.id),
        "academicYearId": str(term.academic_year_id),
        "name": term.name,
        "displayName": term_display_name(term),
        "sortOrder": term.sort_order,
        "startDate": term.start_date.isoformat(),
        "endDate": term.end_date.isoformat(),
        "isCurrent": term.is_current,
        "isClosed": term.is_closed,
        "closedAt": term.closed_at.isoformat() if term.closed_at else None,
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
        "isConfigured": bool(policy.is_configured),
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
    year = get_active_academic_year()
    term = get_current_academic_term()
    return {
        "academicYear": serialize_academic_year(year) if year else None,
        "currentTerm": serialize_academic_term(term) if term else None,
    }
