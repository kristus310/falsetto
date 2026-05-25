from allauth.account.forms import SignupForm
from django import forms
from .models import User, UserProfile
from .validators import validate_avatar

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

class UsernameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "Username"}),
        }

class EmailForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email"]
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "email@example.com"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That email is already in use.")
        return email

class AvatarForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["avatar"]
        widgets = {
            "avatar": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def clean_avatar(self):
        f = self.cleaned_data.get("avatar")
        if f:
            validate_avatar(f)
        return f

class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        label="Confirm your password",
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••", "autocomplete": "current-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.user.check_password(password):
            raise forms.ValidationError("Incorrect password. Please try again.")
        return password