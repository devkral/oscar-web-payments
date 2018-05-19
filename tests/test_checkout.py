from decimal import Decimal as D
import sys
from importlib import import_module

from django.test.utils import override_settings
from django.conf import settings
from django.urls import clear_url_caches, reverse

from oscar.test.testcases import WebTestCase
from oscar.test import factories
from oscar.test.factories import create_product
from oscar.core.loading import get_class, get_classes, get_model

Basket = get_model('basket', 'Basket')
Source = get_model('payment', 'Source')
CheckoutSessionData = get_class('checkout.utils', 'CheckoutSessionData')

UserAddress = get_model('address', 'UserAddress')
Country = get_model('address', 'Country')
GatewayForm = get_class('checkout.forms', 'GatewayForm')

# Python 3 compat
try:
    from imp import reload
except ImportError:
    pass


def reload_url_conf():
    # Reload URLs to pick up the overridden settings
    if settings.ROOT_URLCONF in sys.modules:
        reload(sys.modules[settings.ROOT_URLCONF])
    import_module(settings.ROOT_URLCONF)
    clear_url_caches()

# stolen from django oscar tests
class CheckoutMixin(object):

    def create_digital_product(self):
        product_class = factories.ProductClassFactory(
            requires_shipping=False, track_stock=False)
        product = factories.ProductFactory(product_class=product_class)
        factories.StockRecordFactory(
            num_in_stock=None, price_excl_tax=D('12.00'), product=product)
        return product

    def add_product_to_basket(self, product=None):
        if product is None:
            product = factories.ProductFactory()
            factories.StockRecordFactory(
                num_in_stock=10, price_excl_tax=D('12.00'), product=product)
        detail_page = self.get(product.get_absolute_url())
        form = detail_page.forms['add_to_basket_form']
        return form.submit()

    def add_voucher_to_basket(self, voucher=None):
        if voucher is None:
            voucher = factories.create_voucher()
        basket_page = self.get(reverse('basket:summary'))
        form = basket_page.forms['voucher_form']
        form['code'] = voucher.code
        return form.submit()

    def enter_guest_details(self, email='guest@example.com'):
        # why redirect instead correct page
        index_page = self.get(reverse('checkout:index'))
        index_page.form['username'] = email
        index_page.form.select('options', GatewayForm.GUEST)
        return index_page.form.submit()

    def create_shipping_country(self):
        return factories.CountryFactory(
            iso_3166_1_a2='GB', is_shipping_country=True)

    def enter_shipping_address(self):
        self.create_shipping_country()
        address_page = self.get(reverse('checkout:shipping-address'))
        form = address_page.forms['new_shipping_address']
        form['first_name'] = 'John'
        form['last_name'] = 'Doe'
        form['line1'] = '1 Egg Road'
        form['line4'] = 'Shell City'
        form['postcode'] = 'N12 9RT'
        form.submit()

    def enter_shipping_method(self):
        self.get(reverse('checkout:shipping-method'))

    def place_order(self):
        payment_details = self.get(
            reverse('checkout:shipping-method')).follow().follow()
        preview = payment_details.click(linkid="view_preview")
        return preview.forms['place_order_form'].submit().follow()

    def reach_payment_details_page(self, is_guest=False):
        if is_guest:
            self.enter_guest_details('hello@egg.com')
        self.enter_shipping_address()
        return self.get(
            reverse('checkout:shipping-method')).follow().follow()

    def ready_to_place_an_order(self, is_guest=False):
        payment_details = self.reach_payment_details_page(is_guest)
        return payment_details.click(linkid="view_preview")


@override_settings(OSCAR_ALLOW_ANON_CHECKOUT=True)
class CheckoutTestCase(CheckoutMixin, WebTestCase):
    is_anonymous = True

    def setUp(self):
        reload_url_conf()
        super(CheckoutTestCase, self).setUp()

    def test_checkout(self):
        ret = self.add_product_to_basket()
        # why have we no product in basket yet?
        payment_selection = self.reach_payment_details_page(is_guest=True)
        self.assertIn('payment_method_form', payment_selection.forms)
        form = payment_selection.form['payment_method_form']
        form.variant = "dummy_capture"
        preview = form.submit().follow()
        self.assertIn('place_order_form', preview.form)
        details = preview.forms["place_order_form"].submit().follow()
        self.assertIn('payment_form', details.form)
        form = details.forms["payment_form"]
        # transmit error
        #form.status =
