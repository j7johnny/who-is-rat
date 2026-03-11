from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import User
from library.models import ReaderChapterGrant, ReaderNovelGrant, ReaderSiteGrant


class ReaderSiteGrantInline(admin.TabularInline):
    model = ReaderSiteGrant
    fk_name = "reader"
    extra = 0
    autocomplete_fields = ("granted_by",)
    verbose_name = "全站授權"
    verbose_name_plural = "全站授權"


class ReaderNovelGrantInline(admin.TabularInline):
    model = ReaderNovelGrant
    fk_name = "reader"
    extra = 0
    autocomplete_fields = ("novel", "granted_by")
    verbose_name = "小說授權"
    verbose_name_plural = "小說授權"


class ReaderChapterGrantInline(admin.TabularInline):
    model = ReaderChapterGrant
    fk_name = "reader"
    extra = 0
    autocomplete_fields = ("chapter", "granted_by")
    verbose_name = "章節授權"
    verbose_name_plural = "章節授權"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = AdminUserCreationForm
    form = AdminUserChangeForm
    model = User
    list_display = ("username", "role", "is_active", "is_staff", "password_changed_at")
    list_filter = ("role", "is_active", "is_staff")
    ordering = ("username",)
    search_fields = ("username",)
    inlines = (ReaderSiteGrantInline, ReaderNovelGrantInline, ReaderChapterGrantInline)
    fieldsets = (
        ("基本資料", {"fields": ("username", "password")}),
        ("權限", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("時間", {"fields": ("last_login", "date_joined", "password_changed_at")}),
    )
    add_fieldsets = (
        (
            "建立帳號",
            {
                "classes": ("wide",),
                "fields": ("username", "role", "password1", "password2", "is_active"),
            },
        ),
    )

# Register your models here.
