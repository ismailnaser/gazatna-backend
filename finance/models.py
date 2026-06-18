from django.conf import settings
from django.db import models


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "قيد المراجعة"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class PaymentSource(models.TextChoices):
    PARENT = "parent", "من المنصة"
    MANUAL = "manual", "يدوي"


class FeePlan(models.Model):
    name = models.CharField(max_length=120)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    installments_count = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    grades = models.ManyToManyField("academics.Grade", related_name="fee_plans", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "خطة رسوم"
        verbose_name_plural = "خطط الرسوم"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class FeeInstallment(models.Model):
    fee_plan = models.ForeignKey(FeePlan, on_delete=models.CASCADE, related_name="installments")
    order = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "قسط"
        verbose_name_plural = "أقساط"
        ordering = ["order"]
        unique_together = [("fee_plan", "order")]

    def __str__(self):
        return f"{self.fee_plan.name} — دفعة {self.order}"


class StudentFeeBalance(models.Model):
    student = models.OneToOneField("academics.Student", on_delete=models.CASCADE, related_name="fee_balance")
    fee_plan = models.ForeignKey(FeePlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_balances")
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    access_override_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "رصيد رسوم"
        verbose_name_plural = "أرصدة الرسوم"

    @property
    def remaining(self):
        return self.total - self.paid

    @property
    def fees_paid(self):
        return self.remaining <= 0


class PaymentNotice(models.Model):
    student = models.ForeignKey("academics.Student", on_delete=models.CASCADE, related_name="payment_notices")
    declared_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    source = models.CharField(max_length=20, choices=PaymentSource.choices, default=PaymentSource.PARENT)
    note = models.TextField(blank=True)
    receipt = models.ImageField(upload_to="payments/", blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_payments",
    )

    class Meta:
        verbose_name = "إشعار دفع"
        verbose_name_plural = "إشعارات الدفع"
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if not self.declared_amount:
            self.declared_amount = self.amount
        super().save(*args, **kwargs)
