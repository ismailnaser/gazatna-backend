from django.conf import settings
from django.db import models


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "قيد المراجعة"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class StudentFeeBalance(models.Model):
    student = models.OneToOneField("academics.Student", on_delete=models.CASCADE, related_name="fee_balance")
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)

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
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    note = models.TextField(blank=True)
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
        ordering = ["-date"]
