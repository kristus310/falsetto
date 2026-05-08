from allauth.account.forms import SignupForm
from django import forms


class UserSignupForm(SignupForm):
    name = forms.CharField(
        max_length=255,
        required=False,
        label="Full name",
        widget=forms.TextInput(attrs={"placeholder": "Your name (optional)"}),
    )

    def save(self, request):
        user = super().save(request)
        user.name = self.cleaned_data.get("name", "")
        user.save(update_fields=["name"])
        return user