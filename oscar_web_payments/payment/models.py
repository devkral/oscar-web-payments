from django.db import models
from django.contrib.sites.models import Site
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
#from django.db.models import Max
from oscar.apps.payment.abstract_models import AbstractSource
from web_payments.django.models import BasePayment
from web_payments import NotSupported
from decimal import Decimal

CENTS = Decimal("0.01")

class Source(AbstractSource, BasePayment):
    variant = None
    temp_shipping = None
    temp_billing = None
    temp_tax = None
    temp_delivery = None
    temp_email = None
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
        return "{}://{}{}".format(settings.PAYMENT_PROTOCOL, Site.objects.get_current().domain, reverse('checkout:payment'))

    get_failure_url = get_success_url


    def get_shipping_address(self):
        if self.temp_shipping:
            return {
                "first_name": self.temp_shipping.first_name,
                "last_name": self.temp_shipping.last_name,
                "address_1": self.temp_shipping.line1,
                "address_2": self.temp_shipping.line2,
                "city": self.temp_shipping.line4,
                "postcode": self.temp_shipping.postcode,
                "country_code": self.temp_shipping.country.iso_3166_1_a2,
                "country_area": self.temp_shipping.state,
                "phone_number": self.temp_shipping.phone_number,
                "email": self.temp_email
            }
        else:
            return {
                "first_name": self.shipping_address.first_name,
                "last_name": self.shipping_address.last_name,
                "address_1": self.shipping_address.line1,
                "address_2": self.shipping_address.line2,
                "city": self.shipping_address.line4,
                "postcode": self.shipping_address.postcode,
                "country_code": self.shipping_address.country.iso_3166_1_a2,
                "country_area": self.shipping_address.state,
                "phone_number": self.shipping_address.phone_number,
                "email": self.temp_email if not self.order else self.order.guest_email
            }

    def get_billing_address(self):
        if self.temp_billing:
            return {
                "first_name": self.temp_billing.first_name,
                "last_name": self.temp_billing.last_name,
                "address_1": self.temp_billing.line1,
                "address_2": self.temp_billing.line2,
                "city": self.temp_billing.line4,
                "postcode": self.temp_billing.postcode,
                "country_code": self.temp_billing.country.iso_3166_1_a2,
                "country_area": self.temp_billing.state,
                "phone_number": self.temp_billing.phone_number,
                "email": self.temp_email
            }
        else:
            return {
                "first_name": self.billing_address.first_name,
                "last_name": self.billing_address.last_name,
                "address_1": self.billing_address.line1,
                "address_2": self.billing_address.line2,
                "city": self.billing_address.line4,
                "postcode": self.billing_address.postcode,
                "country_code": self.billing_address.country.iso_3166_1_a2,
                "country_area": self.billing_address.state,
                "phone_number": self.billing_address.phone_number,
                "email": self.temp_email if not self.order else self.order.guest_email
            }

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
