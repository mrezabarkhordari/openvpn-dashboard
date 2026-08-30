from django import forms
from .models import User, Account

class UserCreationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['name', 'phone', 'info']

class AccountCreationForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['user', 'account_number', 'expiration_date', 'remaining_days', 'status']

    def __init__(self, *args, **kwargs):
        super(AccountCreationForm, self).__init__(*args, **kwargs)
        # Disable autocomplete for the account_number field
        self.fields['account_number'].widget.attrs['autocomplete'] = 'off'
        if self.instance and self.instance.pk:
            self.initial['remaining_days'] = self.instance.days_until_expiration

class AccountStatusForm(forms.Form):
    STATUS_CHOICES = (
        ('activate', 'Activate'),
        ('deactivate', 'Deactivate'),
    )
    status = forms.ChoiceField(choices=STATUS_CHOICES)
