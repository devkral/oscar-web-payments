oscar-web-payments
======================

Web payments integration in oscar

Documentation
=============

Installation
------------

like django.oscar plus:
* add web_payments.django to INSTALLED_APPS

* add oscar_web_payments.checkout oscar_web_payments.payment as get_core_apps arguments:

  get_core_apps(['oscar_web_payments.checkout', 'oscar_web_payments.payment'])

* set PAYMENT_MODEL to 'payment.Source'

* set PAYMENT_VARIANTS_API with extra argument verbose_name per provider


Example:
--------

    INSTALLED_APPS = [
        ...
        "web_payments.django"
    ] + get_core_apps(['oscar_web_payments.checkout', 'oscar_web_payments.payment'])


    #PAYMENT_PROTOCOL="http" # to disable https, don't recommend, only for testing
    #PAYMENT_HOST="example.com" # what is the servername? If you don't want to use Sites
    #def PAYMENT_HOST(provider): # can be also a function, taking a provider
    #    if provider.extras["name"] == "foo":
    #        return "bar.example.com"
    #    else:
    #        return "example.com"

    PAYMENT_MODEL = 'payment.Source'
    PAYMENT_VARIANTS_API = {
        'dummy_capture': ('web_payments_dummy.DummyProvider', {}, {"verbose_name": "dummy capturing"}),
        'dummy_nocapture': ('web_payments_dummy.DummyProvider', {"capture": False}, {"verbose_name": "dummy not capturing"}),
        'directwithform': ('web_payments_externalpayments.DirectPaymentProvider', {'skipform': False, 'confirm': True}, {"verbose_name": "direct payment with form"}),
        'direct': ('web_payments_externalpayments.DirectPaymentProvider', {}, {"verbose_name": "direct payment"}),
        'iban': ('web_payments_externalpayments.BankTransferProvider', {
            "iban": "XX5604449899990000",
            "bic": "DABAIE2D"}, {"verbose_name": "IBAN"}
            ),
        }

TODO
====

* Implementation

Note: I use semantic versioning.
