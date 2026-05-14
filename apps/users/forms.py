from allauth.account.forms import SignupForm
from django import forms


class UserSignupForm(SignupForm):
    username = forms.CharField(
        max_length=50,
        required=True,
        label="Username",
        widget=forms.TextInput(attrs={"placeholder": "Pick a username"}),
    )

    def save(self, request):
        user = super().save(request)
        user.username = self.cleaned_data.get("username", "")
        user.save(update_fields=["username"])
        return user