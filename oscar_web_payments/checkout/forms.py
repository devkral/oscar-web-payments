from django import forms
from django.utils.translation import ugettext_lazy as _

from oscar.core.loading import get_model

Source = get_model('payment', 'Source')

class SelectPaymentForm(forms.Form):
    variants = list(map(lambda v: (v.extra["name"], v.extra.get("verbose_name", v.extra["name"])), Source.list_providers()))
    variant = forms.ChoiceField(choices=variants, required=True, label=_("Payment Method"))
