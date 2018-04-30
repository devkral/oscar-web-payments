from django.db import models
from django.utils.translation import ugettext_lazy as _
#from django.db.models import Max
from oscar.apps.payment.abstract_models import AbstractSource
from web_payments.django.models import BasePayment
from web_payments import NotSupported
from decimal import Decimal

CENTS = Decimal("0.01")

class Source(AbstractSource, BasePayment):
    variant = None
    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='sources',
        verbose_name=_("Order"), null=True)
    amount_refunded = models.DecimalField(
        _("Amount Refunded"), decimal_places=2, max_digits=12,
        default=Decimal('0.0'))

    currency = models.CharField(max_length=10)

    shipping_method_code = models.CharField(max_length=100, null=True, blank=True)

    def get_success_url(self):
        return "https://{}{}".format(Site.objects.get_current().domain, reverse('checkout:payment-details', kwargs={"status": "success"}))

    def get_failure_url(self):
        return "https://{}{}".format(Site.objects.get_current().domain, reverse('checkout:payment-details', kwargs={"status": "failure"}))

    def allocate(self, amount, reference='', status=''):
        """
        Convenience method for ring-fencing money against this source
        """
        raise NotSupported()

    def debit(self, amount=None, reference='', status=''):
        """
        Convenience method for recording debits against this source
        """
        if amount is None:
            amount = self.balance
        self.amount_debited += amount
        self.save()
        self._create_transaction(
            AbstractTransaction.DEBIT, amount, reference, status)
    debit.alters_data = True

    def refund(self, amount, reference='', status=''):
        """
        Convenience method for recording refunds against this source
        amount None: all
        """
        amount = BasicPayments.refund(self, amount)
        self.amount_refunded += amount
        self._create_transaction(
            AbstractTransaction.REFUND, amount, reference, status)
    refund.alters_data = True

    @property
    def variant(self):
        return self.source_type.code

    def save(self, *args, **kwargs):
        self.create_token()
        return AbstractSource.save(self, *args, **kwargs)

    @property
    def amount_allocated(self):
        return self.total.quantize(CENTS)

    @property
    def amount_debited(self):
        return self.captured_amount.quantize(CENTS)

    @property
    def balance(self):
        """
        Return the balance of this source
        """
        return self.captured_amount

    @property
    def amount_available_for_refund(self):
        """
        Return the amount available to be refunded
        """
        return self.captured_amount
from oscar.apps.payment.models import *  # noqa isort:skip
