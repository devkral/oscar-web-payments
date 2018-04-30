from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.checkout.views import PaymentMethodView as CorePaymentMethodView
from oscar.apps.checkout.exceptions import FailedPreCondition
from oscar.apps.payment.exceptions import RedirectRequired, UnableToTakePayment, UserCancelled

from django.core.urlresolvers import reverse, reverse_lazy
from django.utils.translation import ugettext_lazy as _
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django import http
from django.views.generic import TemplateView
from django.contrib import messages
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site

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


adminlogger = logging.getLogger("django.request")

class PaymentMethodView(CorePaymentMethodView):
    template_name = 'checkout/payment_method.html'
    def get_context_data(self, **kwargs):
        ctx = super(PaymentMethodView, self).get_context_data(**kwargs)
        minage = self.request.basket.minimum_age
        data = None
        if "payment_method" in self.request.session:
            data = {'variant': self.request.session["payment_method"]}
        # see own forms
        ctx['form'] = SelectPaymentForm(data)
        return ctx
    def get_pre_conditions(self, request):
        return super(PaymentMethodView, self).get_pre_conditions(request).copy() + ['check_valid_method']

    def get(self, request, *args, **kwargs):
        ctx = self.get_context_data(**kwargs)
        return self.render_to_response(ctx)

    def post(self, request, *args, **kwargs):
        request.session["payment_method"] = request.POST["variant"]
        return self.get_success_response()

    def check_valid_method(self, request):
        if request.method != 'POST':
            return
        form = SelectPaymentForm(request.POST)
        if not form.is_valid():
            raise FailedPreCondition(reverse('checkout:payment-method'), message="Invalid Payment Method")

class PaymentDetailsView(CorePaymentDetailsView):
    def post(self, request, *args, **kwargs):
        # We use a custom parameter to indicate if this is an attempt to place
        # an order (normally from the preview page).  Without this, we assume a
        # payment form is being submitted from the payment details view. In
        # this case, the form needs validating and the order preview shown.

        if request.POST.get('action', '') == 'place_order':
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)
    def get(self, request, *args, **kwargs):
        return self.handle_payment_details_submission(request)

    def dispatch(self, request, *args, **kwargs):
        if "payment_method" not in self.request.session:
            return redirect("checkout:payment-method")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super(PaymentDetailsView, self).get_context_data(**kwargs)
        ctx["payment_method"] = settings.PAYMENT_VARIANTS_API[self.request.session["payment_method"]][2]["verbose_name"]
        return ctx

    def handle_place_order_submission(self, request):

        # No form data to validate by default, so we simply render the preview
        # page.  If validating form data and it's invalid, then call the
        # render_payment_details view.

        self.preview = False
        ctx = self.get_context_data()

        #build payment object:
        source_type = SourceType.objects.get_or_create(defaults={"name": request.session["payment_method"]}, code=request.session["payment_method"])[0]
        self.create_shipping_address(self.request.user, ctx["shipping_address"])
        if ctx["billing_address"]:
            self.create_billing_address(self.request.user, ctx["billing_address"])
        ctx["basket"].freeze()
        try:
            pay = Source.objects.get(models.Q(status=PaymentStatus.WAITING)|models.Q(status=PaymentStatus.INPUT), source_type=source_type, id=request.session["paymentid"], basket=ctx["basket"])
        except (ObjectDoesNotExist, KeyError):
            if request.user.is_authenticated:
                email = request.user.email
            else:
                email = self.checkout_session.get_guest_email()

            ctx["basket"].strategy = Selector().strategy()
            order = OrderCreator().place_order(
                user=self.basket.owner, total=Price(self.currency, self.total-self.tax, incl_tax=self.total),
                order_number=self.id, basket=self.basket,
                shipping_address=self.shipping_address, shipping_method=self.get_shipping_method(),
                shipping_charge=Price(self.currency, self.delivery, incl_tax=self.delivery),
                billing_address=self.billing_address
            )
            order.guest_email = email
            # create source
            order.save()
            pay = Source.objects.create(
                order=order,
                source_type=source_type,
                basket=ctx["basket"],
                currency="EUR",
                total=ctx["order_total"].incl_tax,
                captured_amount=ctx["order_total"].incl_tax,
                tax=ctx["order_total"].tax,
                delivery=ctx["shipping_charge"].incl_tax,
                billing_email=email
                shipping_method_code=ctx["shipping_method"].code,
            )
            pay.save()
            request.session["paymentid"] = pay.id
        try:
            ctx["paymentform"] = pay.get_form(data=request.POST)
            #ctx["place_order"] = True
        except web_payments.RedirectNeeded as e:
            return http.HttpResponseRedirect(str(e))
        except web_payments.PaymentError as e:
            ctx["basket"].thaw()
            adminlogger.error(e)
            messages.error(self.request, _("Payment failed"))
            return self.handle_payment_details_submission(request)
        return self.render_to_response(ctx)
