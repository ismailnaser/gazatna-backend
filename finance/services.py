from datetime import date
from decimal import Decimal

from django.utils import timezone

from finance.models import FeeInstallment, FeePlan, StudentFeeBalance


def installment_label(inst) -> str:
    if hasattr(inst, "display_name"):
        return inst.display_name()
    name = (getattr(inst, "name", None) or "").strip()
    order = getattr(inst, "order", "")
    return name if name else f"دفعة {order}"


def load_active_fee_plans_by_grade() -> dict[str, FeePlan]:
    """Load every active fee plan once (for list/analytics). Avoids N+1 grade lookups."""
    by_grade: dict[str, FeePlan] = {}
    plans = (
        FeePlan.objects.filter(is_active=True)
        .prefetch_related("installments", "grades")
        .order_by("id")
    )
    for plan in plans:
        for grade in plan.grades.all():
            name = (grade.name or "").strip()
            if name and name not in by_grade:
                by_grade[name] = plan
    return by_grade


def get_fee_plan_for_student(student, plans_by_grade: dict[str, FeePlan] | None = None):
    if plans_by_grade is not None:
        return plans_by_grade.get(getattr(student, "grade_level", None) or "")
    return (
        FeePlan.objects.filter(is_active=True, grades__name=student.grade_level)
        .prefetch_related("installments")
        .distinct()
        .first()
    )


def apply_plan_to_student(student, plan=None):
    plan = plan or get_fee_plan_for_student(student)
    balance, _ = StudentFeeBalance.objects.get_or_create(student=student)
    if plan:
        balance.fee_plan = plan
        balance.total = plan.total_amount
    else:
        balance.fee_plan = None
        if Decimal(str(balance.paid or 0)) <= 0:
            balance.total = Decimal("0")
    balance.save()
    return balance


def apply_plan_to_students(plan):
    """Assign a fee plan to matching students without per-row signal storms."""
    from config.events import emit

    if not plan.is_active:
        StudentFeeBalance.objects.filter(fee_plan=plan).update(fee_plan=None)
        emit("finance.changed")
        return 0

    grade_names = list(plan.grades.values_list("name", flat=True))
    from academics.models import Student

    student_ids = list(
        Student.objects.filter(grade_level__in=grade_names, is_active=True).values_list("id", flat=True)
    )

    if student_ids:
        existing_ids = set(
            StudentFeeBalance.objects.filter(student_id__in=student_ids).values_list("student_id", flat=True)
        )
        missing = [
            StudentFeeBalance(student_id=student_id, fee_plan=plan, total=plan.total_amount, paid=0)
            for student_id in student_ids
            if student_id not in existing_ids
        ]
        if missing:
            StudentFeeBalance.objects.bulk_create(missing, ignore_conflicts=True)

        StudentFeeBalance.objects.filter(student_id__in=student_ids).update(
            fee_plan=plan,
            total=plan.total_amount,
        )

    StudentFeeBalance.objects.filter(fee_plan=plan).exclude(student_id__in=student_ids).update(fee_plan=None)
    emit("finance.changed")
    return len(student_ids)


def _plan_installments(plan) -> list:
    if plan is None:
        return []
    # Prefer prefetched relation to avoid extra ORDER BY queries in hot loops.
    cached = getattr(plan, "_prefetched_objects_cache", None)
    if cached is not None and "installments" in cached:
        return sorted(plan.installments.all(), key=lambda item: item.order)
    return list(plan.installments.order_by("order"))


def get_installments(balance, student=None, plan=None):
    if plan is not None:
        return _plan_installments(plan)
    if student is None and balance.student_id:
        from academics.models import Student

        student = Student.objects.filter(id=balance.student_id).first()
    if not student:
        if balance.fee_plan_id:
            return _plan_installments(balance.fee_plan)
        return []
    resolved = get_fee_plan_for_student(student)
    if not resolved:
        return []
    return _plan_installments(resolved)


def ensure_fee_plan_linked(student, plans_by_grade: dict[str, FeePlan] | None = None):
    """Keep student balance aligned with the active fee plan for their grade.

    Uses QuerySet.update() (not model.save) so post_save signals do not fire —
    otherwise every GET that "links" plans invalidates analytics and storms Passenger.
    """
    if not hasattr(student, "fee_balance"):
        return None
    balance = student.fee_balance
    plan = get_fee_plan_for_student(student, plans_by_grade)
    fields: dict = {}
    if not plan:
        if balance.fee_plan_id is not None:
            fields["fee_plan_id"] = None
            balance.fee_plan = None
        if balance.paid <= 0 and balance.total != 0:
            fields["total"] = Decimal("0")
            balance.total = Decimal("0")
    else:
        if balance.fee_plan_id != plan.id:
            fields["fee_plan_id"] = plan.id
            balance.fee_plan = plan
        if balance.total != plan.total_amount:
            fields["total"] = plan.total_amount
            balance.total = plan.total_amount
    if fields:
        StudentFeeBalance.objects.filter(pk=balance.pk).update(**fields)
    return balance


def cumulative_required(installments, up_to_order):
    """Sum of installment amounts with order <= up_to_order."""
    total = Decimal("0")
    for inst in installments:
        if inst.order <= up_to_order:
            total += inst.amount
    return total


def installment_remaining(paid, installments, inst):
    """Amount still owed toward a single installment (not cumulative)."""
    prev_required = cumulative_required(installments, inst.order - 1) if inst.order > 1 else Decimal("0")
    paid_toward = max(Decimal("0"), paid - prev_required)
    return max(Decimal("0"), inst.amount - paid_toward)


def find_blocking_installment(installments, paid, today):
    """
    Earliest installment that should block platform access.
    Access resumes after paying the current due installment only — never the full annual fee.
    """
    for inst in installments:
        remaining = installment_remaining(paid, installments, inst)
        if remaining <= 0:
            continue

        has_dates = bool(inst.start_date and inst.end_date)
        if not has_dates:
            if inst.order == 1:
                return inst, remaining
            continue

        if today >= inst.start_date:
            return inst, remaining

    return None, Decimal("0")


def _installment_status(inst, paid, installments, today):
    if not (inst.start_date and inst.end_date):
        return "unscheduled"

    prev_required = cumulative_required(installments, inst.order - 1) if inst.order > 1 else Decimal("0")
    required = cumulative_required(installments, inst.order)
    paid_toward = max(Decimal("0"), paid - prev_required)

    if paid >= required:
        return "paid"
    if today > inst.end_date:
        return "overdue"
    if paid_toward > 0:
        return "partial"
    if inst.start_date <= today <= inst.end_date:
        return "due"
    return "upcoming"


def build_installment_notifications(balance, installments, paid):
    """Return due installment alerts only when the student's balance doesn't cover them."""
    total = Decimal(str(balance.total or 0))
    if total > 0 and paid >= total:
        return []

    scheduled = [inst for inst in installments if inst.start_date and inst.end_date]
    if not scheduled:
        return []

    today = date.today()
    notifications = []
    for inst in scheduled:
        required = cumulative_required(scheduled, inst.order)
        if paid >= required:
            continue

        prev_required = cumulative_required(scheduled, inst.order - 1) if inst.order > 1 else Decimal("0")
        paid_toward = max(Decimal("0"), paid - prev_required)
        remaining = max(Decimal("0"), inst.amount - paid_toward)
        if remaining <= 0:
            continue

        status = _installment_status(inst, paid, scheduled, today)
        notifications.append({
            "id": f"installment-{inst.order}",
            "order": inst.order,
            "name": installment_label(inst),
            "amount": float(inst.amount),
            "remaining": float(remaining),
            "startDate": str(inst.start_date),
            "endDate": str(inst.end_date),
            "status": status,
            "type": "installment",
            "text": (
                f"{installment_label(inst)}: {int(remaining)} ₪ مستحقة — "
                f"من {inst.start_date} إلى {inst.end_date}"
            ),
        })
    return notifications


def restore_student_access_after_fees(student):
    """Re-enable student account when fee obligations no longer block access."""
    from academics.models import Student

    status = build_fee_status(student)
    if status.get("blocked"):
        return status
    if not student.is_active:
        Student.objects.filter(pk=student.pk, is_active=False).update(is_active=True)
        student.is_active = True
    return status


def build_fee_status(
    student,
    *,
    link_plan=True,
    plans_by_grade: dict[str, FeePlan] | None = None,
    detail: bool = True,
):
    """Compute fee gate status.

    Hot paths (analytics / blocked-students list) MUST pass link_plan=False and
    a shared plans_by_grade map so one request does not fan out into N DB writes
    and N plan queries (that pattern piled up Passenger workers past NPROC).
    """
    inactive = not getattr(student, "is_active", True)

    empty = {
        "blocked": False,
        "fullyPaid": True,
        "requiredAmount": 0,
        "message": "",
        "currentInstallment": None,
        "installments": [],
        "notifications": [],
        "accessOverrideUntil": None,
    }

    if not hasattr(student, "fee_balance"):
        if inactive:
            empty["blocked"] = True
            empty["message"] = (
                "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم. "
                "يرجى مراجعة صفحة المالية أو التواصل مع الإدارة."
            )
        return empty

    balance = (
        ensure_fee_plan_linked(student, plans_by_grade) if link_plan else student.fee_balance
    ) or student.fee_balance
    plan = get_fee_plan_for_student(student, plans_by_grade)
    paid = Decimal(str(balance.paid or 0))
    total = Decimal(str(balance.total or 0))
    installments = get_installments(balance, student, plan=plan)
    notifications = build_installment_notifications(balance, installments, paid) if detail else []

    def _pack(*, blocked, fully_paid, required, message, current, override=None, notices=None):
        return {
            "blocked": blocked,
            "fullyPaid": fully_paid,
            "requiredAmount": required,
            "message": message,
            "currentInstallment": current if detail else None,
            "installments": (
                [_serialize_installment(inst, paid, installments, date.today()) for inst in installments]
                if detail
                else []
            ),
            "notifications": notices if notices is not None else notifications,
            "accessOverrideUntil": override,
        }

    if not plan:
        return _pack(
            blocked=False,
            fully_paid=balance.fees_paid,
            required=0,
            message="",
            current=None,
            notices=[],
        )

    override_until = balance.access_override_until
    if override_until and override_until > timezone.now():
        return _pack(
            blocked=False,
            fully_paid=balance.fees_paid,
            required=0,
            message="",
            current=None,
            override=override_until.isoformat(),
        )

    if total > 0 and paid >= total:
        return _pack(
            blocked=False,
            fully_paid=True,
            required=0,
            message="",
            current=None,
            notices=[],
        )

    if not installments:
        return _pack(
            blocked=False,
            fully_paid=balance.fees_paid,
            required=0,
            message="",
            current=None,
            notices=[],
        )

    today = date.today()
    scheduled = [inst for inst in installments if inst.start_date and inst.end_date]

    blocking, remaining = find_blocking_installment(installments, paid, today)
    if blocking:
        label = installment_label(blocking)
        if blocking.order == 1:
            message = (
                f"يجب دفع مبلغ «{label}» ({int(remaining)} ₪) لاستئناف الوصول — "
                f"وليس المبلغ الكلي ({int(total)} ₪)."
            )
        else:
            if blocking.start_date and blocking.end_date and today <= blocking.end_date:
                message = (
                    f"يجب دفع مبلغ «{label}» ({int(remaining)} ₪) لاستئناف الوصول — "
                    f"المطلوب لهذه الدفعة: {int(blocking.amount)} ₪ "
                    f"(من {blocking.start_date} إلى {blocking.end_date})."
                )
            else:
                message = (
                    f"يجب دفع مبلغ «{label}» ({int(remaining)} ₪) لاستئناف الوصول — "
                    f"المطلوب لهذه الدفعة: {int(blocking.amount)} ₪ (انتهى الموعد: {blocking.end_date})."
                )
        if inactive:
            message = (
                "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم المستحقة. "
                f"{message}"
            )
        return _pack(
            blocked=True,
            fully_paid=False,
            required=float(remaining),
            message=message,
            current=_serialize_installment(blocking, paid, installments, today) if detail else None,
        )

    current = next(
        (i for i in scheduled if i.start_date <= today <= i.end_date),
        scheduled[-1] if scheduled else None,
    )
    if inactive:
        return _pack(
            blocked=True,
            fully_paid=balance.fees_paid,
            required=0,
            message=(
                "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم. "
                "يرجى مراجعة صفحة المالية أو التواصل مع الإدارة."
            ),
            current=_serialize_installment(current, paid, installments, today) if current and detail else None,
        )
    return _pack(
        blocked=False,
        fully_paid=balance.fees_paid,
        required=0,
        message="",
        current=_serialize_installment(current, paid, installments, today) if current and detail else None,
    )


def count_fee_blocked_students(queryset=None) -> int:
    """Count blocked active students without mutating balances or N+1 plan queries."""
    from academics.models import Student

    qs = queryset if queryset is not None else Student.objects.filter(is_active=True)
    qs = qs.select_related("fee_balance")
    plans_by_grade = load_active_fee_plans_by_grade()
    blocked = 0
    for student in qs.iterator(chunk_size=200):
        if build_fee_status(
            student,
            link_plan=False,
            plans_by_grade=plans_by_grade,
            detail=False,
        ).get("blocked"):
            blocked += 1
    return blocked


def _serialize_installment(inst, paid, installments, today=None):
    today = today or date.today()
    prev_required = cumulative_required(installments, inst.order - 1) if inst.order > 1 else Decimal("0")
    paid_toward = max(Decimal("0"), paid - prev_required)
    all_installments = installments
    return {
        "order": inst.order,
        "name": installment_label(inst),
        "amount": float(inst.amount),
        "startDate": str(inst.start_date) if inst.start_date else None,
        "endDate": str(inst.end_date) if inst.end_date else None,
        "scheduled": bool(inst.start_date and inst.end_date),
        "status": _installment_status(inst, paid, all_installments, today),
        "paidToward": float(min(paid_toward, inst.amount)),
        "remaining": float(max(Decimal("0"), inst.amount - paid_toward)),
    }


def _serialize_installments(balance, student=None):
    installments = get_installments(balance, student)
    if not installments:
        return []
    paid = Decimal(str(balance.paid or 0))
    today = date.today()
    return [_serialize_installment(inst, paid, installments, today) for inst in installments]
