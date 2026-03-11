from django.contrib import messages
from django.contrib.auth import authenticate, login, logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import FormView

from library.models import AuditLog
from library.services.audit import log_event

from .forms import ReaderLoginForm, ReaderPasswordChangeForm
from .models import User
from .services import clear_login_failures, get_client_ip, get_login_lock_reason, record_login_failure


class ReaderLoginView(FormView):
    form_class = ReaderLoginForm
    template_name = "accounts/login.html"

    def dispatch(self, request, *args, **kwargs):
        if not User.objects.filter(role=User.Role.ADMIN).exists():
            return redirect("backoffice:setup")
        if request.user.is_authenticated:
            if request.user.role == User.Role.ADMIN:
                return redirect("backoffice:dashboard")
            return redirect("reader:library")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        username = form.cleaned_data["username"].lower()
        password = form.cleaned_data["password"]
        ip_address = get_client_ip(self.request)
        lock_reason = get_login_lock_reason(username, ip_address)
        if lock_reason:
            form.add_error(None, lock_reason)
            return self.form_invalid(form)

        user = authenticate(self.request, username=username, password=password)
        if user is None or not user.is_active:
            record_login_failure(username, ip_address, request=self.request)
            form.add_error(None, "帳號或密碼錯誤。")
            return self.form_invalid(form)

        login(self.request, user)
        clear_login_failures(username, ip_address)
        log_event(AuditLog.EventType.LOGIN_SUCCESS, user=user, request=self.request)
        if user.role == User.Role.ADMIN:
            return HttpResponseRedirect(reverse_lazy("backoffice:dashboard"))
        return redirect("reader:library")


class ReaderPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    form_class = ReaderPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("reader:library")

    def get_success_url(self):
        if self.request.user.role == User.Role.ADMIN:
            return reverse_lazy("backoffice:dashboard")
        return super().get_success_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.password_changed_at = timezone.now()
        self.request.user.save(update_fields=["password_changed_at"])
        messages.success(self.request, "密碼已更新。")
        log_event(AuditLog.EventType.PASSWORD_CHANGED, user=self.request.user, request=self.request)
        return response


class ReaderLogoutView(FormView):
    http_method_names = ["get", "post"]

    def get(self, request, *args, **kwargs):
        return self._logout_and_redirect()

    def post(self, request, *args, **kwargs):
        return self._logout_and_redirect()

    def _logout_and_redirect(self):
        auth_logout(self.request)
        return redirect("login")
