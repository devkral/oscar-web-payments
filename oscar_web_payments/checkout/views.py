from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.checkout.views import PaymentMethodView as CorePaymentMethodView

from oscar.apps.checkout import signals
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
UnableToPlaceOrder = get_class('order.exceptions', 'UnableToPlaceOrder')

logger = get_class('checkout.views', 'logger')


class PaymentMethodView(CorePaymentMethodView):
    template_name = 'checkout/payment_method.html'
    pre_conditions += ['check_valid_method']
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

class PaymentDetailsView(CorePaymentDetailsView):
    payment = False
    pre_conditions += ['check_valid_method']

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

        if self.payment:
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)

    def get(self, request, *args, **kwargs):
        if self.payment:
            return self.handle_place_order_submission(request)
        return self.handle_payment_details_submission(request)

    def get_context_data(self, **kwargs):
        ctx = super(PaymentDetailsView, self).get_context_data(**kwargs)
        extra = Source.get_provider(self.checkout_session.payment_method()).extra
        ctx["payment_method"] = extra.get("verbose_name", extra["name"])
        return ctx

    def handle_order_placement(self, order_number, user, basket,
                               shipping_address, shipping_method,
                               shipping_charge, billing_address, order_total, source,
                               **kwargs):
        """
        Write out the order models and return the appropriate HTTP response

        We deliberately pass the basket in here as the one tied to the request
        isn't necessarily the correct one to use in placing the order.  This
        can happen when a basket gets frozen.
        """
        order = self.place_order(
            order_number=order_number, user=user, basket=basket,
            shipping_address=shipping_address, shipping_method=shipping_method,
            shipping_charge=shipping_charge, order_total=order_total,
            billing_address=billing_address, **kwargs)
        basket.submit()
        source.order = order
        source.save()
        return self.handle_successful_order(order)

    def build_submission(self, **kwargs):
        submission = super().build_submission(**kwargs)
        source_type = SourceType.objects.get_or_create(defaults={"name": self.checkout_session.payment_method()}, code=self.checkout_session.payment_method())[0]
        submission["payment_kwargs"].update({
            "source_type": source_type,
            "currency": submission["basket"].currency,
            "total": submission["order_total"].incl_tax,
            "captured_amount": submission["order_total"].incl_tax,
        })
        return submission

    def submit(self, user, basket, shipping_address, shipping_method,
               shipping_charge, billing_address, order_total,
               payment_kwargs=None, order_kwargs=None):

        if payment_kwargs is None:
            payment_kwargs = {}
        if order_kwargs is None:
            order_kwargs = {}


        # We define a general error message for when an unanticipated payment
        # error occurs.
        error_msg = _("A problem occurred while processing payment for this "
                      "order - no payment has been taken.  Please "
                      "contact customer services if this problem persists")

        try:
            pay_id = self.checkout_session.payment_id()
            # id=None seems to match some cases, so be sure
            if not pay_id:
                raise ObjectDoesNotExist()
            source = Source.objects.get(id=pay_id)
        except ObjectDoesNotExist:
            # either session has not a paymentid (ObjectDoesNotExist)
            # or payment does not exist (ObjectDoesNotExist)
            source = Source.objects.create(**payment_kwargs)
            self.checkout_session.set_payment_id(source.id)

            # Taxes must be known at this point
            assert basket.is_tax_known, (
                "Basket tax must be set before a user can place an order")
            assert shipping_charge.is_tax_known, (
                "Shipping charge tax must be set before a user can place an order")

            # We generate the order number first as this will be used
            # in payment requests (ie before the order model has been
            # created).  We also save it in the session for multi-stage
            # checkouts (eg where we redirect to a 3rd party site and place
            # the order on a different request).

            order_number = self.generate_order_number(basket)
            self.checkout_session.set_order_number(order_number)
            logger.info("Order #%s: beginning submission process for basket #%d",
                        order_number, basket.id)

            # Freeze the basket so it cannot be manipulated while the customer is
            # completing payment on a 3rd party site.  Also, store a reference to
            # the basket in the session so that we know which basket to thaw if we
            # get an unsuccessful payment response when redirecting to a 3rd party
            # site.
            self.freeze_basket(basket)
            self.checkout_session.set_submitted_basket(basket)
            signals.pre_payment.send_robust(sender=self, view=self)

        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.checkout_session.set_payment_id(None)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=source.message, **payment_kwargs)
        elif source.status in [PaymentStatus.INPUT, PaymentStatus.WAITING]:
            source.temp_shipping = shipping_address
            source.temp_billing = billing_address
            source.temp_extra = {"tax": order_total.tax, "delivery": shipping_charge}
            source.temp_email = self.checkout_session.get_guest_email()

        order_number = self.checkout_session.get_order_number()

        # is finished but for whatever reason still on this page
        if source.order:
            return self.handle_successful_order(source.order)

        try:
            if self.request.method == "GET":
                form = source.get_form()
            else:
                form = source.get_form(data=self.request.POST)
            if source.status not in [PaymentStatus.CONFIRMED, PaymentStatus.PREAUTH]:
                return self.render_payment_details(self.request, paymentform=form)
        except web_payments.RedirectNeeded as e:
            # Redirect required (eg PayPal, 3DS)
            logger.info("Order #%s: redirecting to %s", order_number, e.args[0])
            return http.HttpResponseRedirect(e.args[0])
        except web_payments.PaymentError as e:
            # A general payment error - Something went wrong which wasn't
            # anticipated.  Eg, the payment gateway is down (it happens), your
            # credentials are wrong - that king of thing.
            # It makes sense to configure the checkout logger to
            # mail admins on an error as this issue warrants some further
            # investigation.
            msg = str(e)
            logger.error("Order #%s: payment error (%s)", order_number, msg,
                         exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=error_msg, **payment_kwargs)
        except Exception as e:
            # Unhandled exception - hopefully, you will only ever see this in
            # development...
            logger.error(
                "Order #%s: unhandled exception while taking payment (%s)",
                order_number, e, exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=error_msg, **payment_kwargs)

        signals.post_payment.send_robust(sender=self, view=self)


        # If all is ok with payment, try and place order
        logger.info("Order #%s: payment successful, placing order",
                    order_number)
        try:
            return self.handle_order_placement(
                order_number, user, basket, shipping_address, shipping_method,
                shipping_charge, billing_address, order_total, source=source, **order_kwargs)
        except UnableToPlaceOrder as e:
            # It's possible that something will go wrong while trying to
            # actually place an order.  Not a good situation to be in as a
            # payment transaction may already have taken place, but needs
            # to be handled gracefully.
            msg = str(e)
            logger.error("Order #%s: unable to place order - %s",
                         order_number, msg, exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=msg, **payment_kwargs)
