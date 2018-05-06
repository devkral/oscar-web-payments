import six

from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.checkout.views import PaymentMethodView as CorePaymentMethodView

from oscar.apps.checkout import signals
from oscar.apps.checkout.exceptions import FailedPreCondition

from django.core.urlresolvers import reverse, reverse_lazy
from django.utils.translation import ugettext_lazy as _
from django import http
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
        if self.preview or request.POST.get('action', '') == 'place_order':
            super().check_basket_is_not_empty(request)
        else:
            oldbasket = request.basket
            request.basket = self.get_submitted_basket()
            request.basket.strategy = oldbasket.strategy
            super().check_basket_is_not_empty(request)
            request.basket = oldbasket

    def check_basket_is_valid(self, request):
        if self.preview or request.POST.get('action', '') == 'place_order':
            super().check_basket_is_valid(request)
        else:
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
            return super().get(request, *args, **kwargs)
        return self.handle_payment_details_submission(request)

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
        source.temp_email = submission["order_kwargs"]['guest_email']
        submission["payment_kwargs"]["source"] = source


        assert submission["basket"].is_tax_known, (
            "Basket tax must be set before a user can place an order")
        assert submission["shipping_charge"].is_tax_known, (
            "Shipping charge tax must be set before a user can place an order")

        # We generate the order number first as this will be used
        # in payment requests (ie before the order model has been
        # created).  We also save it in the session for multi-stage
        # checkouts (eg where we redirect to a 3rd party site and place
        # the order on a different request).
        order_number = self.generate_order_number(submission["basket"])
        self.checkout_session.set_order_number(order_number)
        logger.info("Order #%s: beginning submission process for basket #%d",
                    order_number, submission["basket"].id)

        # Freeze the basket so it cannot be manipulated while the customer is
        # completing payment on a 3rd party site.  Also, store a reference to
        # the basket in the session so that we know which basket to thaw if we
        # get an unsuccessful payment response when redirecting to a 3rd party
        # site.
        self.freeze_basket(submission["basket"])
        self.checkout_session.set_submitted_basket(submission["basket"])
        return self.submit(**submission)

    def handle_payment_details_submission(self, request):
        try:
            source = Source.objects.get(id=self.checkout_session.payment_id())
        except ObjectDoesNotExist:
            self.restore_frozen_basket()
            return redirect("checkout:preview")
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            return redirect("checkout:preview")
        basket = self.get_submitted_basket()
        basket.strategy = self.request.basket.strategy
        submission = self.build_submission(basket=basket)

        source.temp_shipping = submission["shipping_address"]
        source.temp_billing = submission["billing_address"]
        source.temp_extra = {
            "tax": submission["order_total"].incl_tax-submission["order_total"].excl_tax,
            "delivery": submission["shipping_charge"].incl_tax
        }
        source.temp_email = submission['order_kwargs']['guest_email']
        submission["payment_kwargs"]["source"] = source
        return self.submit(**submission)

    def submit(self, user, basket, shipping_address, shipping_method,  # noqa (too complex (10))
               shipping_charge, billing_address, order_total,
               payment_kwargs=None, order_kwargs=None):
        # We define a general error message for when an unanticipated payment
        # error occurs.
        error_msg = _("A problem occurred while processing payment for this "
                      "order - no payment has been taken.  Please "
                      "contact customer services if this problem persists")
        order_number = self.checkout_session.get_order_number()

        signals.pre_payment.send_robust(sender=self, view=self)

        try:
            self.handle_payment(order_number, order_total, **payment_kwargs)
        except RedirectRequired as e:
            # Redirect required (eg PayPal, 3DS)
            logger.info("Order #%s: redirecting to %s", order_number, e.url)
            return http.HttpResponseRedirect(e.url)
        except UnableToTakePayment as e:
            # Something went wrong with payment but in an anticipated way.  Eg
            # their bankcard has expired, wrong card number - that kind of
            # thing. This type of exception is supposed to set a friendly error
            # message that makes sense to the customer.
            msg = six.text_type(e)
            # We assume that the details submitted on the payment details view
            # were invalid (eg expired bankcard).
            return self.render_payment_details(
                self.request, error=msg, **payment_kwargs)
        except PaymentError as e:
            # A general payment error - Something went wrong which wasn't
            # anticipated.  Eg, the payment gateway is down (it happens), your
            # credentials are wrong - that king of thing.
            # It makes sense to configure the checkout logger to
            # mail admins on an error as this issue warrants some further
            # investigation.
            msg = six.text_type(e)
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
                shipping_charge, billing_address, order_total, **order_kwargs)
        except UnableToPlaceOrder as e:
            # It's possible that something will go wrong while trying to
            # actually place an order.  Not a good situation to be in as a
            # payment transaction may already have taken place, but needs
            # to be handled gracefully.
            msg = six.text_type(e)
            logger.error("Order #%s: unable to place order - %s",
                         order_number, msg, exc_info=True)
            self.restore_frozen_basket()
            return self.render_preview(
                self.request, error=msg, **payment_kwargs)


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
            raise RedirectRequired(reverse("checkout:preview"))
        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            try:
                if self.request.POST.get("action", '') == "place_order":
                    source.temp_form = source.get_form()
                else:
                    source.temp_form = source.get_form(self.request.POST)
            except web_payments.RedirectNeeded as e:
                raise RedirectRequired(e.args[0])
        if source.status in [PaymentStatus.ERROR, PaymentStatus.REJECTED]:
            self.restore_frozen_basket()
            raise RedirectRequired(reverse("checkout:preview"))
        if source.status not in [PaymentStatus.PREAUTH, PaymentStatus.CONFIRMED]:
            raise UnableToTakePayment("")
