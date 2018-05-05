from django.db import models
from django.contrib.sites.models import Site
from django.utils.translation import ugettext_lazy as _

from django.conf import settings
#from django.db.models import Max
from oscar.apps.payment.abstract_models import AbstractSource
from web_payments.django.models import BasePayment
from web_payments import NotSupported
from decimal import Decimal

try:
    from django.urls import reverse
except ImportError:
    from django.core.urlresolvers import reverse

CENTI0 = Decimal("0.00")

class Source(AbstractSource, BasePayment):
    variant = None
    temp_shipping = None
    temp_billing = None
    temp_extra = None
    temp_email = None
    temp_form = None

    order = models.ForeignKey(
        'order.Order',
        on_delete=models.CASCADE,
        related_name='sources',
        verbose_name=_("Order"), null=True)
    amount_refunded = models.DecimalField(
        _("Amount Refunded"), decimal_places=2, max_digits=12,
        default=CENTI0)

    currency = models.CharField(max_length=10)

    shipping_method_code = models.CharField(max_length=100, null=True, blank=True)

    def get_success_url(self):
        return "{}://{}{}".format(getattr(settings, "PAYMENT_PROTOCOL", "https"), Site.objects.get_current().domain, reverse('checkout:payment-details'))

    def get_failure_url(self):
        return "{}://{}{}".format(getattr(settings, "PAYMENT_PROTOCOL", "https"), Site.objects.get_current().domain, reverse('checkout:preview'))


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
                "first_name": self.order.shipping_address.first_name,
                "last_name": self.order.shipping_address.last_name,
                "address_1": self.order.shipping_address.line1,
                "address_2": self.order.shipping_address.line2,
                "city": self.order.shipping_address.line4,
                "postcode": self.order.shipping_address.postcode,
                "country_code": self.order.shipping_address.country.iso_3166_1_a2,
                "country_area": self.order.shipping_address.state,
                "phone_number": self.order.shipping_address.phone_number,
                "email": self.order.guest_email
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
                "first_name": self.order.billing_address.first_name,
                "last_name": self.order.billing_address.last_name,
                "address_1": self.order.billing_address.line1,
                "address_2": self.order.billing_address.line2,
                "city": self.order.billing_address.line4,
                "postcode": self.order.billing_address.postcode,
                "country_code": self.order.billing_address.country.iso_3166_1_a2,
                "country_area": self.order.billing_address.state,
                "phone_number": self.order.billing_address.phone_number,
                "email": self.order.guest_email
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

    def get_payment_extra(self):
        if self.temp_extra:
            return self.temp_extra
        else:
            return {
                "tax": self.order.total_incl_tax-self.order.total_excl_tax if self.order else CENTI0,
                "delivery": self.order.shipping_incl_tax if self.order else CENTI0
            }

    @property
    def variant(self):
        return self.source_type.code

    def save(self, *args, **kwargs):
        self.create_token()
        return AbstractSource.save(self, *args, **kwargs)

    @property
    def amount_allocated(self):
        return self.total.quantize(CENTI0)

    @property
    def amount_debited(self):
        return self.captured_amount.quantize(CENTI0)

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
