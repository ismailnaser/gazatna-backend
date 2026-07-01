from datetime import timedelta

from rest_framework import serializers


def resolve_period_bounds(billing_period, academic_year, academic_term):
    if not academic_year:
        return None, None

    if billing_period == "single_term":
        if not academic_term:
            raise serializers.ValidationError(
                {"academicTermId": "اختر الفصل الدراسي عند تحديد خطة لفصل واحد"}
            )
        if academic_term.academic_year_id != academic_year.id:
            raise serializers.ValidationError(
                {"academicTermId": "الفصل المحدد لا ينتمي للسنة الدراسية المختارة"}
            )
        return academic_term.start_date, academic_term.end_date

    return academic_year.start_date, academic_year.end_date


def validate_installment_schedule(installments_data, period_start, period_end):
    if not installments_data:
        raise serializers.ValidationError({"installments": "يجب إضافة دفعة واحدة على الأقل"})

    if not period_start or not period_end:
        raise serializers.ValidationError(
            {"academicYearId": "اختر السنة الدراسية لربط مواعيد الدفع"}
        )

    rows = sorted(installments_data, key=lambda row: row.get("order") or 0)
    previous_end = None

    for index, row in enumerate(rows, start=1):
        start = row.get("start_date")
        end = row.get("end_date")
        label = f"الدفعة {index}"

        if not start or not end:
            raise serializers.ValidationError(
                {"installments": f"يجب تحديد بداية ونهاية {label}"}
            )

        if end < start:
            raise serializers.ValidationError(
                {"installments": f"تاريخ نهاية {label} يجب أن يكون بعد تاريخ البداية"}
            )

        if start < period_start or end > period_end:
            raise serializers.ValidationError(
                {
                    "installments": (
                        f"مواعيد {label} يجب أن تقع ضمن فترة "
                        f"{period_start.isoformat()} — {period_end.isoformat()}"
                    )
                }
            )

        if previous_end is not None:
            min_start = previous_end + timedelta(days=1)
            if start < min_start:
                raise serializers.ValidationError(
                    {
                        "installments": (
                            f"بداية {label} يجب أن تكون بعد انتهاء الدفعة السابقة "
                            f"({previous_end.isoformat()})"
                        )
                    }
                )

        previous_end = end
