from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.checkout.views import PaymentMethodView as CorePaymentMethodView

from oscar.apps.checkout import signals
from oscar.apps.checkout.exceptions import FailedPreCondition
from oscar.apps.payment.exceptions import RedirectRequired, UnableToTakePayment, UserCancelled

from django.core.urlresolvers import reverse, reverse_lazy
from django.utils.translation import ugettext_lazy as _
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.views.generic import TemplateView
from django.contrib import messages
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.shortcuts import redirect

from oscar.core.loading import get_class, get_classes, get_model

from .forms import SelectPaymentForm
#from payments.forms import SelectPaymentForm
import web_payments
from web_payments import PaymentStatus

from time import sleep
import logging

SourceType = get_model('payment', 'SourceType')
Source = get_model('payment', 'Source')
Order = get_model('order', 'Order')
RedirectRequired, UnableToTakePayment, PaymentError \
    = get_classes('payment.exceptions', ['RedirectRequired',
                                         'UnableToTakePayment',
                                         'PaymentError'])

logger = get_class('checkout.views', 'logger')


class PaymentMethodView(CorePaymentMethodView):
    template_name = 'checkout/payment_method.html'
    pre_conditions = CorePaymentMethodView.pre_conditions + ['check_valid_method']
    def get_context_data(self, **kwargs):
        ctx = super(PaymentMethodView, self).get_context_data(**kwargs)
        data = None
        if self.checkout_session.payment_method():
            data = {'variant': self.checkout_session.payment_method()}
        # see own forms
        ctx['form'] = SelectPaymentForm(data)
        return ctx

    def get(self, request, *args, **kwargs):
        ctx = self.get_context_data(**kwargs)
        return self.render_to_response(ctx)

    def post(self, request, *args, **kwargs):
        self.checkout_session.pay_by(request.POST["variant"])
        return self.get_success_response()

    def check_valid_method(self, request):
        if request.method != 'POST':
            return
        form = SelectPaymentForm(request.POST)
        if not form.is_valid():
            raise FailedPreCondition(reverse('checkout:payment-method'), message="Invalid Payment Method")

    def get_success_response(self):
        return redirect('checkout:preview')

class PaymentDetailsView(CorePaymentDetailsView):
    payment = False
    pre_conditions = CorePaymentDetailsView.pre_conditions + ['check_valid_method']

    def check_valid_method(self, request):
        try:
            Source.get_provider(self.checkout_session.payment_method())
        except ValueError:
            raise FailedPreCondition(reverse('checkout:payment-method'), message="Invalid Payment Method")

    def post(self, request, *args, **kwargs):
        # We use a custom parameter to indicate if this is an attempt to place
        # an order (normally from the preview page).  Without this, we assume a
        # payment form is being submitted from the payment details view. In
        # this case, the form needs validating and the order preview shown.

        if not self.preview:
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)

    def get(self, request, *args, **kwargs):
        if not self.preview:
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)

    def handle_place_order_submission(self, request):
        submission = self.build_submission()
        source_type = SourceType.objects.get_or_create(defaults={"name": self.checkout_session.payment_method()}, code=self.checkout_session.payment_method())[0]
        submission["payment_kwargs"]["source"] = Source.objects.get_or_create(defaults={
            "source_type": source_type,
            "currency": submission["basket"].currency,
            "total": submission["order_total"].incl_tax,
            "captured_amount": submission["order_total"].incl_tax
        }, id=self.checkout_session.payment_id())[0]
        submission["payment_kwargs"]["source"].temp_shipping = submission["shipping_address"]
        submission["payment_kwargs"]["source"].temp_billing = submission["billing_address"]
        submission["payment_kwargs"]["source"].temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        submission["payment_kwargs"]["source"].temp_email = submission['order_kwargs']['guest_email']
        return self.submit(**submission)

    def handle_payment_details_submission(self, request):
        source_type = SourceType.objects.get_or_create(defaults={"name": self.checkout_session.payment_method()}, code=self.checkout_session.payment_method())[0]
        submission = self.build_submission()
        source = Source.objects.create(**{
            "source_type": source_type,
            "currency": submission["basket"].currency,
            "total": submission["order_total"].incl_tax,
            "captured_amount": submission["order_total"].incl_tax,
        })
        self.checkout_session.set_payment_id(source.id)
        source.temp_shipping = submission["shipping_address"]
        source.temp_billing = submission["billing_address"]
        source.temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        source.temp_email = submission['order_kwargs']['guest_email']

        url = None
        try:
            form = source.get_form()
        except web_payments.RedirectNeeded as e:
            form = None
            url = e.args[0]

        return self.render_preview(request, paymentform=form, redirecturl=url)

    def get_context_data(self, **kwargs):
        ctx = super(PaymentDetailsView, self).get_context_data(**kwargs)
        extra = Source.get_provider(self.checkout_session.payment_method()).extra
        ctx["payment_method"] = extra.get("verbose_name", extra["name"])
        return ctx

    def handle_payment(self, order_number, total, source, **kwargs):
        self.add_payment_source(source)
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            raise RedirectRequired(reverse("checkout:preview"))
        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            try:
                source.temp_form = source.get_form(self.request.POST)
            except web_payments.RedirectNeeded as e:
                raise RedirectRequired(e.args[0])

        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            raise UnableToTakePayment(source.message)
