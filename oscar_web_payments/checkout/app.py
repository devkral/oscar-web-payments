
from oscar.apps.checkout import app
from . import views

try:
    from django.urls import path_re as url
except ImportError:
    from django.conf.urls import url

class CheckoutApplication(app.CheckoutApplication):
    payment_method_view = views.PaymentMethodView
    payment_details_view = views.PaymentDetailsView
    def get_urls(self):
        urls = [
            url(r'^$', self.index_view.as_view(), name='index'),

            # Shipping/user address views
            url(r'shipping-address/$',
                self.shipping_address_view.as_view(), name='shipping-address'),
            url(r'user-address/edit/(?P<pk>\d+)/$',
                self.user_address_update_view.as_view(),
                name='user-address-update'),
            url(r'user-address/delete/(?P<pk>\d+)/$',
                self.user_address_delete_view.as_view(),
                name='user-address-delete'),

            # Shipping method views
            url(r'shipping-method/$',
                self.shipping_method_view.as_view(), name='shipping-method'),

            # Payment views
            url(r'payment-method/$',
                self.payment_method_view.as_view(), name='payment-method'),
            url(r'payment-details/$',
                self.payment_details_view.as_view(), name='payment-details'),

            # Preview and thankyou
            url(r'preview/$',
                self.payment_details_view.as_view(preview=True),
                name='preview'),
            url(r'payment/$',
                self.payment_details_view.as_view(payment=True, preview=False), name='payment'),
            url(r'thank-you/$', self.thankyou_view.as_view(),
                name='thank-you'),
        ]
        return self.post_process_urls(urls)


application = CheckoutApplication()
