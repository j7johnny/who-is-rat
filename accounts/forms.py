from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserChangeForm, UserCreationForm

from .models import User


class ReaderLoginForm(forms.Form):
    username = forms.CharField(label="帳號", max_length=16)
    password = forms.CharField(label="密碼", widget=forms.PasswordInput)


class ReaderPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label="舊密碼", widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="新密碼", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="確認新密碼", widget=forms.PasswordInput)


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "role", "is_active")


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
