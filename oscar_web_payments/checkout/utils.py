from oscar.apps.checkout.utils import CheckoutSessionData as CoreCheckoutSessionData

class CheckoutSessionData(CoreCheckoutSessionData):
    def set_payment_id(self, paymentid):
        self._set('payment', 'paymentid', paymentid)

    def payment_id(self):
        return self._get('payment', 'paymentid')
