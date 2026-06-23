from datetime import date
from decimal import Decimal

from django.utils import timezone

from finance.models import FeeInstallment, FeePlan, StudentFeeBalance


def get_fee_plan_for_student(student):
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
    balance.save()
    return balance


def apply_plan_to_students(plan):
    grade_names = list(plan.grades.values_list("name", flat=True))
    if not grade_names:
        return 0
    from academics.models import Student

    students = Student.objects.filter(grade_level__in=grade_names, is_active=True)
    count = 0
    for student in students:
        apply_plan_to_student(student, plan)
        count += 1
    return count


def get_installments(balance, student=None):
    if student is None and balance.student_id:
        from academics.models import Student

        student = Student.objects.filter(id=balance.student_id).first()
    if not student:
        if balance.fee_plan_id:
            return list(balance.fee_plan.installments.order_by("order"))
        return []
    plan = get_fee_plan_for_student(student)
    if not plan:
        return []
    return list(plan.installments.order_by("order"))


def ensure_fee_plan_linked(student):
    """Keep student balance aligned with the active fee plan for their grade."""
    if not hasattr(student, "fee_balance"):
        return None
    balance = student.fee_balance
    plan = get_fee_plan_for_student(student)
    if not plan:
        updates = []
        if balance.fee_plan_id is not None:
            balance.fee_plan = None
            updates.append("fee_plan")
        if balance.paid <= 0 and balance.total != 0:
            balance.total = Decimal("0")
            updates.append("total")
        if updates:
            balance.save(update_fields=updates)
        return balance
    updates = []
    if balance.fee_plan_id != plan.id:
        balance.fee_plan = plan
        updates.append("fee_plan")
    if balance.total != plan.total_amount:
        balance.total = plan.total_amount
        updates.append("total")
    if updates:
        balance.save(update_fields=updates)
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
            "amount": float(inst.amount),
            "remaining": float(remaining),
            "startDate": str(inst.start_date),
            "endDate": str(inst.end_date),
            "status": status,
            "type": "installment",
            "text": (
                f"دفعة {inst.order}: {int(remaining)} ₪ مستحقة — "
                f"من {inst.start_date} إلى {inst.end_date}"
            ),
        })
    return notifications


def build_fee_status(student):
    inactive = not getattr(student, "is_active", True)

    if not hasattr(student, "fee_balance"):
        if inactive:
            return {
                "blocked": True,
                "fullyPaid": True,
                "requiredAmount": 0,
                "message": (
                    "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم. "
                    "يرجى مراجعة صفحة المالية أو التواصل مع الإدارة."
                ),
                "currentInstallment": None,
                "installments": [],
                "notifications": [],
                "accessOverrideUntil": None,
            }
        return {
            "blocked": False,
            "fullyPaid": True,
            "requiredAmount": 0,
            "message": "",
            "currentInstallment": None,
            "installments": [],
            "notifications": [],
            "accessOverrideUntil": None,
        }

    balance = ensure_fee_plan_linked(student) or student.fee_balance
    plan = get_fee_plan_for_student(student)
    paid = Decimal(str(balance.paid or 0))
    total = Decimal(str(balance.total or 0))
    installments = get_installments(balance, student)
    notifications = build_installment_notifications(balance, installments, paid)

    if not plan:
        return {
            "blocked": False,
            "fullyPaid": balance.fees_paid,
            "requiredAmount": 0,
            "message": "",
            "currentInstallment": None,
            "installments": [],
            "notifications": [],
            "accessOverrideUntil": None,
        }

    override_until = balance.access_override_until
    if override_until and override_until > timezone.now():
        return {
            "blocked": False,
            "fullyPaid": balance.fees_paid,
            "requiredAmount": 0,
            "message": "",
            "currentInstallment": None,
            "installments": _serialize_installments(balance, student),
            "notifications": notifications,
            "accessOverrideUntil": override_until.isoformat(),
        }

    if total > 0 and paid >= total:
        return {
            "blocked": False,
            "fullyPaid": True,
            "requiredAmount": 0,
            "message": "",
            "currentInstallment": None,
            "installments": _serialize_installments(balance, student),
            "notifications": [],
            "accessOverrideUntil": None,
        }

    if not installments:
        return {
            "blocked": False,
            "fullyPaid": balance.fees_paid,
            "requiredAmount": 0,
            "message": "",
            "currentInstallment": None,
            "installments": [],
            "notifications": [],
            "accessOverrideUntil": None,
        }

    today = date.today()
    scheduled = [inst for inst in installments if inst.start_date and inst.end_date]

    blocking, remaining = find_blocking_installment(installments, paid, today)
    if blocking:
        if blocking.order == 1:
            message = (
                f"يجب دفع مبلغ الدفعة الأولى ({int(remaining)} ₪) لاستئناف الوصول — "
                f"وليس المبلغ الكلي ({int(total)} ₪)."
            )
        else:
            if blocking.start_date and blocking.end_date and today <= blocking.end_date:
                message = (
                    f"يجب دفع مبلغ الدفعة رقم {blocking.order} ({int(remaining)} ₪) لاستئناف الوصول — "
                    f"المطلوب لهذه الدفعة: {int(blocking.amount)} ₪ "
                    f"(من {blocking.start_date} إلى {blocking.end_date})."
                )
            else:
                message = (
                    f"يجب دفع مبلغ الدفعة رقم {blocking.order} ({int(remaining)} ₪) لاستئناف الوصول — "
                    f"المطلوب لهذه الدفعة: {int(blocking.amount)} ₪ (انتهى الموعد: {blocking.end_date})."
                )
        if inactive:
            message = (
                "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم المستحقة. "
                f"{message}"
            )
        return {
            "blocked": True,
            "fullyPaid": False,
            "requiredAmount": float(remaining),
            "message": message,
            "currentInstallment": _serialize_installment(blocking, paid, installments, today),
            "installments": _serialize_installments(balance, student),
            "notifications": notifications,
            "accessOverrideUntil": None,
        }

    current = next(
        (i for i in scheduled if i.start_date <= today <= i.end_date),
        scheduled[-1] if scheduled else None,
    )
    if inactive:
        return {
            "blocked": True,
            "fullyPaid": balance.fees_paid,
            "requiredAmount": 0,
            "message": (
                "تم إيقاف الوصول إلى حساب الطالب بسبب الرسوم. "
                "يرجى مراجعة صفحة المالية أو التواصل مع الإدارة."
            ),
            "currentInstallment": _serialize_installment(current, paid, installments, today) if current else None,
            "installments": _serialize_installments(balance, student),
            "notifications": notifications,
            "accessOverrideUntil": None,
        }
    return {
        "blocked": False,
        "fullyPaid": balance.fees_paid,
        "requiredAmount": 0,
        "message": "",
        "currentInstallment": _serialize_installment(current, paid, installments, today) if current else None,
        "installments": _serialize_installments(balance, student),
        "notifications": notifications,
        "accessOverrideUntil": None,
    }


def _serialize_installment(inst, paid, installments, today=None):
    today = today or date.today()
    prev_required = cumulative_required(installments, inst.order - 1) if inst.order > 1 else Decimal("0")
    paid_toward = max(Decimal("0"), paid - prev_required)
    all_installments = installments
    return {
        "order": inst.order,
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
