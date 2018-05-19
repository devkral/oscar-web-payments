import six

from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.checkout.views import PaymentMethodView as CorePaymentMethodView

from oscar.apps.checkout import signals
from oscar.apps.checkout.exceptions import FailedPreCondition
from oscar.core.loading import get_class, get_classes, get_model

from django.utils.translation import ugettext_lazy as _
from django import http
from django.http.request import split_domain_port, validate_host
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.shortcuts import redirect
try:
    from django.urls import reverse, reverse_lazy
except ImportError:
    from django.core.urlresolvers import reverse, reverse_lazy


from .forms import SelectPaymentForm
#from payments.forms import SelectPaymentForm
import web_payments
from web_payments import PaymentStatus


SourceType = get_model('payment', 'SourceType')
Basket = get_model('basket', 'Basket')
Source = get_model('payment', 'Source')
Order = get_model('order', 'Order')
UnableToPlaceOrder = get_class('order.exceptions', 'UnableToPlaceOrder')
RedirectRequired, UnableToTakePayment, PaymentError \
    = get_classes('payment.exceptions', ['RedirectRequired',
                                         'UnableToTakePayment',
                                         'PaymentError'])

PassedSkipCondition = get_class('checkout.exceptions', 'PassedSkipCondition')
CheckoutSessionData = get_class(
    'checkout.utils', 'CheckoutSessionData')

logger = get_class('checkout.views', 'logger')


class PaymentMethodView(CorePaymentMethodView):
    template_name = 'checkout/payment_method.html'
    pre_conditions = CorePaymentMethodView.pre_conditions + ['check_valid_method']
    def get_context_data(self, **kwargs):
        ctx = super(PaymentMethodView, self).get_context_data(**kwargs)
        data = None
        if self.checkout_session.payment_method():
            data = {'variant': self.checkout_session.payment_method()}
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

    pre_conditions = CorePaymentDetailsView.pre_conditions + ['check_valid_method']

    def skip_unless_payment_is_required(self, request):
        # disable check as it breaks logic
        pass

    def check_basket_is_not_empty(self, request):
        if request.basket.is_empty:
            basket = self.get_submitted_basket()
            basket.strategy = request.basket.strategy

            if basket.is_empty:
                raise FailedPreCondition(
                    url=reverse('basket:summary'),
                    message=_(
                        "You need to add some items to your basket to checkout")
                )

    def check_basket_is_valid(self, request):
        if not self.preview:
            oldbasket = request.basket
            request.basket = self.get_submitted_basket()
            request.basket.strategy = oldbasket.strategy
            super().check_basket_is_valid(request)
            request.basket = oldbasket

    def check_valid_method(self, request):
        try:
            Source.get_provider(self.checkout_session.payment_method())
        except ValueError:
            raise FailedPreCondition(reverse('checkout:payment-method'), message="Invalid Payment Method")

    def post(self, request, *args, **kwargs):
        # Posting to payment-details isn't the right thing to do.  Form
        # submissions should use the preview URL.
        if self.preview:
            return http.HttpResponseBadRequest()

        # We use a custom parameter to indicate if this is an attempt to place
        # an order (normally from the preview page).  Without this, we assume a
        # payment form is being submitted from the payment details view. In
        # this case, the form needs validating and the order preview shown.
        if request.POST.get('action', '') == 'place_order':
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)

    def get(self, request, *args, **kwargs):
        if self.preview:
            self.restore_frozen_basket()
            return self.render_preview(request, **kwargs)
        return self.handle_payment_details_submission(request)

    def render_preview(self, request, **kwargs):
        # basket should not change
        basket = request.basket
        self.freeze_basket(basket)
        self.checkout_session.set_submitted_basket(basket)
        return super().render_preview(request, **kwargs)

    #def check_order_is_created_already(self, request):
    #    if request.basket.is_empty:
    #        return
    #    try:
    #        source = Source.objects.get(id=self.checkout_session.payment_id())
    #    except ObjectDoesNotExist:
    #        return
    #    if source.order:
    #        raise PassedSkipCondition(
    #            url=self.handle_successful_order(source.order)
    #        )

    def handle_place_order_submission(self, request):
        basket = self.get_submitted_basket()
        basket.strategy = request.basket.strategy
        submission = self.build_submission(basket=basket)
        source_type = SourceType.objects.get_or_create(defaults={"name": self.checkout_session.payment_method()}, code=self.checkout_session.payment_method())[0]
        source = Source.objects.create(**{
            "source_type": source_type,
            "currency": submission["basket"].currency,
            "total": submission["order_total"].incl_tax,
            "captured_amount": submission["order_total"].incl_tax,
            "order_number": self.generate_order_number(submission["basket"])
        })
        self.checkout_session.set_payment_id(source.id)
        source.temp_shipping = submission["shipping_address"]
        source.temp_billing = submission["billing_address"]
        source.temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        source.temp_email = submission["order_kwargs"]['guest_email']
        submission["payment_kwargs"]["source"] = source
        try:
            source.temp_form = source.get_form()
        except web_payments.RedirectNeeded as e:
            return http.HttpResponseRedirect(e.args[0])
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=source.message)
        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            return self.render_payment_details(
                self.request, **submission["payment_kwargs"])
        return submit(**submission)

    def handle_payment_details_submission(self, request):
        try:
            source = Source.objects.get(id=self.checkout_session.payment_id())
        except ObjectDoesNotExist as e:
            self.restore_frozen_basket()
            msg = six.text_type(e)
            return self.render_preview(
                self.request, error=msg)
        basket = self.get_submitted_basket()
        basket.strategy = request.basket.strategy
        submission = self.build_submission(basket=basket)

        source.temp_shipping = submission["shipping_address"]
        source.temp_billing = submission["billing_address"]
        source.temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        source.temp_email = submission['order_kwargs']['guest_email']
        submission["payment_kwargs"]["source"] = source
        if source.status not in [PaymentStatus.ERROR, PaymentStatus.REJECTED, PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            try:
                source.temp_form = source.get_form(self.request.POST)
            except web_payments.RedirectNeeded as e:
                return http.HttpResponseRedirect(e.args[0])
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=source.message)

        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            return self.render_payment_details(
                self.request, **submission["payment_kwargs"])
        return self.submit(**submission)

    def get_context_data(self, **kwargs):
        ctx = super(PaymentDetailsView, self).get_context_data(**kwargs)
        extra = Source.get_provider(self.checkout_session.payment_method()).extra
        ctx["payment_method"] = extra.get("verbose_name", extra["name"])
        host = ctx.get("source", None)
        if host:
            host = host.temp_form
        if host:
            host = host.action
        ctx["is_local_url"] = (host == "")
        if host is not None and not ctx["is_local_url"]: #try harder
            domain = split_domain_port(host)[0]
            if domain and validate_host(domain, self._allowed_hosts):
                ctx["is_local_url"] = True
        return ctx

    def handle_payment(self, order_number, total, source, **kwargs):
        self.add_payment_source(source)
