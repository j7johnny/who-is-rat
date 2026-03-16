from __future__ import annotations

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from PIL import ImageFont

from accounts.models import User
from library.forms import AntiOcrPresetConfigForm
from library.models import (
    AntiOcrPreset,
    Chapter,
    ChapterStatus,
    CustomFontUpload,
    Novel,
    ReaderChapterGrant,
    ReaderNovelGrant,
    ReaderSiteGrant,
)


USERNAME_HELP = "僅允許 A-Z、a-z、0-9、底線、點與連字號，長度 1 到 16。"


class SetupAdminForm(forms.Form):
    username = forms.CharField(label="管理者帳號", max_length=16, help_text=USERNAME_HELP)
    password1 = forms.CharField(label="密碼", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="再次輸入密碼", widget=forms.PasswordInput, strip=False)

    def clean_username(self):
        username = self.cleaned_data["username"].lower()
        field = User._meta.get_field("username")
        for validator in field.validators:
            validator(username)
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("這個帳號已經存在。")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        username = cleaned_data.get("username")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "兩次輸入的密碼不一致。")
        if password1 and username:
            validate_password(password1, user=User(username=username, role=User.Role.ADMIN))
        return cleaned_data

    def save(self) -> User:
        return User.objects.create_superuser(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password1"],
        )


class ReaderCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="初始密碼", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="再次輸入密碼", widget=forms.PasswordInput, strip=False)

    class Meta:
        model = User
        fields = ["username", "is_active"]
        labels = {
            "username": "閱讀者帳號",
            "is_active": "啟用帳號",
        }
        help_texts = {"username": USERNAME_HELP}

    def clean_username(self):
        return self.cleaned_data["username"].lower()

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        username = cleaned_data.get("username")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "兩次輸入的密碼不一致。")
        if password1 and username:
            validate_password(password1, user=User(username=username, role=User.Role.READER))
        return cleaned_data

    def save(self, commit: bool = True) -> User:
        user = User(
            username=self.cleaned_data["username"],
            is_active=self.cleaned_data["is_active"],
            role=User.Role.READER,
        )
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ReaderUpdateForm(forms.ModelForm):
    password1 = forms.CharField(
        label="重設密碼",
        widget=forms.PasswordInput,
        strip=False,
        required=False,
        help_text="留空表示不變更。若輸入新密碼，系統會立即覆蓋舊密碼。",
    )
    password2 = forms.CharField(
        label="再次輸入新密碼",
        widget=forms.PasswordInput,
        strip=False,
        required=False,
    )

    class Meta:
        model = User
        fields = ["username", "is_active"]
        labels = {
            "username": "閱讀者帳號",
            "is_active": "啟用帳號",
        }
        help_texts = {"username": USERNAME_HELP}

    def clean_username(self):
        return self.cleaned_data["username"].lower()

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "兩次輸入的密碼不一致。")
            if password1:
                validate_password(password1, user=self.instance)
        return cleaned_data

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
            user.password_changed_at = timezone.now()
        if commit:
            user.save()
        return user


class ReaderAccessForm(forms.Form):
    grant_full_site = forms.BooleanField(
        label="授權全站",
        required=False,
        help_text="勾選後，這個閱讀者可以閱讀所有已發布小說與章節。",
    )
    novels = forms.ModelMultipleChoiceField(
        label="授權指定小說",
        queryset=Novel.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="授權整本小說。若小說之後新增新章，閱讀者也會一起看到。",
    )
    chapters = forms.ModelMultipleChoiceField(
        label="授權指定章節",
        queryset=Chapter.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="只授權單獨章節。適合試讀或臨時放行。",
    )

    def __init__(self, *args, reader: User, **kwargs):
        self.reader = reader
        super().__init__(*args, **kwargs)
        self.fields["novels"].queryset = Novel.objects.filter(is_active=True).order_by("title")
        self.fields["chapters"].queryset = Chapter.objects.select_related("novel").order_by(
            "novel__title", "sort_order", "id"
        )
        if reader.pk:
            self.initial.setdefault("grant_full_site", ReaderSiteGrant.objects.filter(reader=reader).exists())
            self.initial.setdefault(
                "novels",
                list(ReaderNovelGrant.objects.filter(reader=reader).values_list("novel_id", flat=True)),
            )
            self.initial.setdefault(
                "chapters",
                list(ReaderChapterGrant.objects.filter(reader=reader).values_list("chapter_id", flat=True)),
            )

    def save(self, actor: User | None = None) -> None:
        if self.cleaned_data["grant_full_site"]:
            ReaderSiteGrant.objects.get_or_create(reader=self.reader, defaults={"granted_by": actor})
        else:
            ReaderSiteGrant.objects.filter(reader=self.reader).delete()

        selected_novels = set(self.cleaned_data["novels"].values_list("id", flat=True))
        existing_novels = {grant.novel_id: grant for grant in ReaderNovelGrant.objects.filter(reader=self.reader)}
        for novel_id, grant in existing_novels.items():
            if novel_id not in selected_novels:
                grant.delete()
        for novel in self.cleaned_data["novels"]:
            ReaderNovelGrant.objects.get_or_create(reader=self.reader, novel=novel, defaults={"granted_by": actor})

        selected_chapters = set(self.cleaned_data["chapters"].values_list("id", flat=True))
        existing_chapters = {
            grant.chapter_id: grant for grant in ReaderChapterGrant.objects.filter(reader=self.reader)
        }
        for chapter_id, grant in existing_chapters.items():
            if chapter_id not in selected_chapters:
                grant.delete()
        for chapter in self.cleaned_data["chapters"]:
            ReaderChapterGrant.objects.get_or_create(
                reader=self.reader, chapter=chapter, defaults={"granted_by": actor}
            )


class NovelBackofficeForm(forms.ModelForm):
    class Meta:
        model = Novel
        fields = ["title", "slug", "description", "is_active"]
        labels = {
            "title": "小說名稱",
            "slug": "小說代稱",
            "description": "簡介",
            "is_active": "啟用小說",
        }
        help_texts = {
            "slug": "用於後台辨識與資料唯一性，前台閱讀網址目前不使用。",
            "description": "讀者書庫頁會顯示這段簡介。",
        }


class ChapterBackofficeForm(forms.ModelForm):
    class Meta:
        model = Chapter
        fields = ["novel", "title", "sort_order", "anti_ocr_preset", "content"]
        labels = {
            "novel": "所屬小說",
            "title": "章節名稱",
            "sort_order": "排序",
            "anti_ocr_preset": "anti7ocr 設定",
            "content": "章節全文",
        }
        help_texts = {
            "sort_order": "決定章節在小說中的前後順序。",
            "anti_ocr_preset": "若未選擇，發布時會自動使用全站預設。",
            "content": "發布時會先產生桌機與手機兩套 anti7ocr 基底圖，完成後才正式對讀者開放。",
        }
        widgets = {
            "content": forms.Textarea(attrs={"rows": 18}),
        }

    def save(self, commit: bool = True) -> Chapter:
        chapter = super().save(commit=False)
        if chapter.pk is None:
            chapter.status = ChapterStatus.DRAFT
        if commit:
            chapter.save()
        return chapter


class AntiOcrPresetSimpleForm(AntiOcrPresetConfigForm):
    pass


class WatermarkExtractToolForm(forms.Form):
    image = forms.ImageField(
        label="上傳圖片",
        help_text="支援站內原圖、單張截圖或長截圖。系統會先產生可見浮水印顯影圖，並直接嘗試 Blind Watermark 原圖提取。",
    )
    advanced_extraction = forms.BooleanField(
        label="啟用進階 Blind 提取",
        required=False,
        help_text="只有在你要額外嘗試裁切、來源比對等耗時流程時才需要勾選。",
    )


class Anti7OcrDiagnosticsForm(forms.Form):
    text = forms.CharField(
        label="診斷文字",
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text="這裡的文字只用於診斷，不會進入正式發布內容。",
    )
    preset = forms.ModelChoiceField(
        label="使用設定",
        queryset=AntiOcrPreset.objects.order_by("-is_default", "name"),
        empty_label=None,
    )
    device_profile = forms.ChoiceField(
        label="裝置版本",
        choices=[("desktop", "桌機"), ("mobile", "手機")],
    )
    seed = forms.IntegerField(
        label="固定 seed",
        required=False,
        help_text="若想重現同一張示範圖，可手動指定。",
    )
    sensitive_keywords = forms.CharField(
        label="敏感詞測試（選填）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="只有診斷工具會使用這些關鍵字，正式章節發布流程不會啟用 sensitive_check。",
    )

    def clean_sensitive_keywords(self):
        raw_value = self.cleaned_data["sensitive_keywords"]
        return [line.strip() for line in raw_value.splitlines() if line.strip()]


class CustomFontUploadForm(forms.ModelForm):
    class Meta:
        model = CustomFontUpload
        fields = ["name", "font_file", "is_active"]
        labels = {
            "name": "字體名稱",
            "font_file": "字體檔案",
            "is_active": "立即啟用",
        }
        help_texts = {
            "name": "建議填入管理者看得懂的名稱，例如「思源黑體粗體」。",
            "font_file": "支援 ttf、otf、ttc、otc。",
        }

    def clean_font_file(self):
        font_file = self.cleaned_data["font_file"]
        current_pos = font_file.tell()
        font_file.seek(0)
        try:
            ImageFont.truetype(font_file, size=24)
        except Exception as exc:
            raise forms.ValidationError("這個檔案無法作為可用字體載入。") from exc
        finally:
            font_file.seek(current_pos)
        return font_file
