from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from finance.services import find_blocking_installment, installment_remaining


def _inst(order, amount, start=None, end=None):
    return SimpleNamespace(order=order, amount=Decimal(str(amount)), start_date=start, end_date=end)


class FeeBlockingTests(SimpleTestCase):
    def test_first_installment_only_not_full_total(self):
        installments = [
            _inst(1, 834, date(2026, 5, 31), date(2026, 6, 29)),
            _inst(2, 834),
            _inst(3, 832),
        ]
        paid = Decimal("0")
        today = date(2026, 6, 16)

        blocking, remaining = find_blocking_installment(installments, paid, today)

        self.assertEqual(blocking.order, 1)
        self.assertEqual(remaining, Decimal("834"))
        self.assertNotEqual(remaining, Decimal("2500"))
        self.assertNotEqual(remaining, Decimal("1000"))

    def test_unblocks_after_first_installment_paid(self):
        installments = [
            _inst(1, 834, date(2026, 5, 31), date(2026, 6, 29)),
            _inst(2, 834, date(2026, 7, 1), date(2026, 7, 31)),
        ]
        paid = Decimal("834")
        today = date(2026, 6, 20)

        blocking, remaining = find_blocking_installment(installments, paid, today)

        self.assertIsNone(blocking)
        self.assertEqual(remaining, Decimal("0"))

    def test_later_installment_blocks_with_remaining_only(self):
        installments = [
            _inst(1, 834, date(2026, 1, 1), date(2026, 1, 31)),
            _inst(2, 834, date(2026, 2, 1), date(2026, 2, 28)),
        ]
        paid = Decimal("834")
        today = date(2026, 3, 1)

        blocking, remaining = find_blocking_installment(installments, paid, today)

        self.assertEqual(blocking.order, 2)
        self.assertEqual(remaining, Decimal("834"))

    def test_installment_remaining_is_per_installment(self):
        installments = [
            _inst(1, 500),
            _inst(2, 500),
        ]
        paid = Decimal("200")
        self.assertEqual(installment_remaining(paid, installments, installments[0]), Decimal("300"))
        self.assertEqual(installment_remaining(paid, installments, installments[1]), Decimal("500"))
