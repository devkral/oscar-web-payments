from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.checkout.views import PaymentMethodView as CorePaymentMethodView

from oscar.apps.checkout import signals
from oscar.apps.checkout.exceptions import FailedPreCondition

from django.core.urlresolvers import reverse, reverse_lazy
from django.utils.translation import ugettext_lazy as _
from django.http.request import split_domain_port, validate_host
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.shortcuts import redirect

from oscar.core.loading import get_class, get_classes, get_model

from .forms import SelectPaymentForm
#from payments.forms import SelectPaymentForm
import web_payments
from web_payments import PaymentStatus


SourceType = get_model('payment', 'SourceType')
Source = get_model('payment', 'Source')
Order = get_model('order', 'Order')
RedirectRequired, UnableToTakePayment, PaymentError \
    = get_classes('payment.exceptions', ['RedirectRequired',
                                         'UnableToTakePayment',
                                         'PaymentError'])

PassedSkipCondition = get_class('checkout.exceptions', 'PassedSkipCondition')

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

class PaymentDetailsView(CorePaymentDetailsView):
    pre_conditions = CorePaymentDetailsView.pre_conditions + ['check_valid_method']
    # invert templates
    template_name = 'checkout/preview.html'
    template_name_preview = 'checkout/payment_details.html'

    def check_valid_method(self, request):
        try:
            Source.get_provider(self.checkout_session.payment_method())
        except ValueError:
            raise FailedPreCondition(reverse('checkout:payment-method'), message="Invalid Payment Method")

    def get(self, request, *args, **kwargs):
        if not self.preview:
            return super().get(request, *args, **kwargs)
        return self.handle_payment_details_submission(request)

    def render_payment_details(self, request, **kwargs):
        """
        Show the payment details page

        This method is useful if the submission from the payment details view
        is invalid and needs to be re-rendered with form errors showing.
        """
        self.preview = True
        ctx = self.get_context_data(**kwargs)
        return self.render_to_response(ctx)

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
        submission = self.build_submission()
        source_type = SourceType.objects.get_or_create(defaults={"name": self.checkout_session.payment_method()}, code=self.checkout_session.payment_method())[0]
        source = Source.objects.create(**{
            "source_type": source_type,
            "currency": submission["basket"].currency,
            "total": submission["order_total"].incl_tax,
            "captured_amount": submission["order_total"].incl_tax
        })
        self.checkout_session.set_payment_id(source.id)
        source.temp_shipping = submission["shipping_address"]
        source.temp_billing = submission["billing_address"]
        source.temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        source.temp_email = submission['order_kwargs']['guest_email']
        submission["payment_kwargs"]["source"] = source
        return self.submit(**submission)

    def handle_payment_details_submission(self, request):
        try:
            source = Source.objects.get(id=self.checkout_session.payment_id())
        except ObjectDoesNotExist:
            self.restore_frozen_basket()
            return redirect("checkout:payment-details")
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            return redirect("checkout:payment-details")
        submission = self.build_submission()

        source.temp_shipping = submission["shipping_address"]
        source.temp_billing = submission["billing_address"]
        source.temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        source.temp_email = submission['order_kwargs']['guest_email']
        submission["payment_kwargs"]["source"] = source
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
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            raise RedirectRequired(reverse("checkout:payment-details"))
        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            try:
                source.temp_form = source.get_form(self.request.POST)
            except web_payments.RedirectNeeded as e:
                raise RedirectRequired(e.args[0])
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            raise RedirectRequired(reverse("checkout:payment-details"))
        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            raise UnableToTakePayment(source.message)
