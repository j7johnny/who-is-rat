from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from library.services.anti7ocr_config import (
    ANTI7OCR_CONFIG_VERSION,
    ANTI7OCR_ENGINE_NAME,
    DEFAULT_BASE_PRESET_NAME,
    build_default_desktop_config,
    build_default_mobile_config,
    build_default_shared_config,
    build_snapshot,
    validate_preset_configs,
)


class DeviceProfile(models.TextChoices):
    DESKTOP = "desktop", "桌機"
    MOBILE = "mobile", "手機"


class ChapterStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    PUBLISHED = "published", "已發布"
    UNPUBLISHED = "unpublished", "已下架"


class Novel(models.Model):
    title = models.CharField("小說名稱", max_length=200)
    slug = models.SlugField("小說代稱", max_length=220, unique=True, allow_unicode=True)
    description = models.TextField("簡介", blank=True)
    is_active = models.BooleanField("啟用", default=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "小說"
        verbose_name_plural = "小說"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class AntiOcrPreset(models.Model):
    name = models.CharField("設定名稱", max_length=100, unique=True)
    is_default = models.BooleanField("預設設定", default=False)
    engine = models.CharField("引擎", max_length=32, default=ANTI7OCR_ENGINE_NAME, editable=False)
    base_preset_name = models.CharField("anti7ocr 基底 preset", max_length=64, default=DEFAULT_BASE_PRESET_NAME)
    shared_config = models.JSONField("共用設定", default=build_default_shared_config)
    desktop_config = models.JSONField("桌機設定", default=build_default_desktop_config)
    mobile_config = models.JSONField("手機設定", default=build_default_mobile_config)
    config_version = models.PositiveIntegerField("設定版本", default=ANTI7OCR_CONFIG_VERSION, editable=False)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]
        verbose_name = "anti7ocr 設定"
        verbose_name_plural = "anti7ocr 設定"

    def clean(self):
        if self.engine != ANTI7OCR_ENGINE_NAME:
            raise ValidationError({"engine": "目前僅支援 anti7ocr。"})
        self.shared_config, self.desktop_config, self.mobile_config = validate_preset_configs(
            self.shared_config,
            self.desktop_config,
            self.mobile_config,
        )

    def as_snapshot(self) -> dict:
        return build_snapshot(
            base_preset_name=self.base_preset_name,
            shared_config=self.shared_config,
            desktop_config=self.desktop_config,
            mobile_config=self.mobile_config,
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class CustomFontUpload(models.Model):
    name = models.CharField("字體名稱", max_length=100, unique=True)
    font_file = models.FileField(
        "字體檔案",
        upload_to="custom_fonts/%Y%m%d",
        validators=[FileExtensionValidator(allowed_extensions=["ttf", "otf", "ttc", "otc"])],
    )
    is_active = models.BooleanField("啟用", default=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "自訂字體"
        verbose_name_plural = "自訂字體"

    @property
    def absolute_path(self) -> Path:
        return Path(settings.MEDIA_ROOT) / self.font_file.name

    def __str__(self) -> str:
        return self.name


class Chapter(models.Model):
    novel = models.ForeignKey(Novel, on_delete=models.CASCADE, related_name="chapters", verbose_name="小說")
    title = models.CharField("章節名稱", max_length=200)
    slug = models.SlugField("章節代稱", max_length=220, allow_unicode=True)
    sort_order = models.PositiveIntegerField("排序", default=1)
    content = models.TextField("章節全文", blank=True)
    status = models.CharField("狀態", max_length=20, choices=ChapterStatus.choices, default=ChapterStatus.DRAFT)
    anti_ocr_preset = models.ForeignKey(
        AntiOcrPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chapters",
        verbose_name="anti7ocr 設定",
    )
    current_version = models.ForeignKey(
        "ChapterVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="目前版本",
    )
    published_at = models.DateTimeField("發布時間", null=True, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        ordering = ["novel__title", "sort_order", "id"]
        verbose_name = "章節"
        verbose_name_plural = "章節"
        constraints = [
            models.UniqueConstraint(fields=["novel", "slug"], name="unique_chapter_slug_per_novel"),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.novel.title} / {self.title}"


class ChapterVersion(models.Model):
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="versions", verbose_name="章節")
    version_number = models.PositiveIntegerField("版本號")
    content = models.TextField("版本全文")
    source_sha256 = models.CharField("原文雜湊", max_length=64)
    preset_snapshot = models.JSONField("設定快照", default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_chapter_versions",
        verbose_name="建立者",
    )
    published_at = models.DateTimeField("建立時間點", default=timezone.now)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-id"]
        verbose_name = "章節版本"
        verbose_name_plural = "章節版本"
        constraints = [
            models.UniqueConstraint(fields=["chapter", "version_number"], name="unique_version_per_chapter"),
        ]

    def __str__(self) -> str:
        return f"{self.chapter} v{self.version_number}"


class ChapterPublishJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待中"
        RUNNING = "running", "處理中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失敗"
        CANCELED = "canceled", "已取消"

    chapter = models.ForeignKey(
        Chapter,
        on_delete=models.CASCADE,
        related_name="publish_jobs",
        verbose_name="章節",
    )
    chapter_version = models.OneToOneField(
        ChapterVersion,
        on_delete=models.CASCADE,
        related_name="publish_job",
        verbose_name="目標版本",
    )
    status = models.CharField("狀態", max_length=20, choices=Status.choices, default=Status.PENDING)
    progress_percent = models.PositiveSmallIntegerField("進度(%)", default=0)
    step_label = models.CharField("目前步驟", max_length=120, blank=True)
    error_message = models.TextField("錯誤訊息", blank=True)
    celery_task_id = models.CharField("Celery Task ID", max_length=100, blank=True)
    cancel_requested = models.BooleanField("已要求取消", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chapter_publish_jobs",
        verbose_name="建立者",
    )
    started_at = models.DateTimeField("開始時間", null=True, blank=True)
    finished_at = models.DateTimeField("完成時間", null=True, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "章節發布工作"
        verbose_name_plural = "章節發布工作"
        indexes = [
            models.Index(fields=["chapter", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    @property
    def is_active(self) -> bool:
        return self.status in {self.Status.PENDING, self.Status.RUNNING}

    def __str__(self) -> str:
        return f"{self.chapter} -> v{self.chapter_version.version_number} ({self.status})"


class ReaderSiteGrant(models.Model):
    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="site_grants",
        verbose_name="閱讀者",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_site_permissions",
        verbose_name="授權者",
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["reader__username"]
        verbose_name = "全站授權"
        verbose_name_plural = "全站授權"
        constraints = [
            models.UniqueConstraint(fields=["reader"], name="unique_reader_site_grant"),
        ]

    def __str__(self) -> str:
        return f"{self.reader} -> 全站"


class ReaderNovelGrant(models.Model):
    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="novel_grants",
        verbose_name="閱讀者",
    )
    novel = models.ForeignKey(Novel, on_delete=models.CASCADE, related_name="reader_novel_grants", verbose_name="小說")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_novel_permissions",
        verbose_name="授權者",
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["novel__title", "reader__username"]
        verbose_name = "小說授權"
        verbose_name_plural = "小說授權"
        constraints = [
            models.UniqueConstraint(fields=["reader", "novel"], name="unique_reader_novel_grant"),
        ]

    def __str__(self) -> str:
        return f"{self.reader} -> {self.novel}"


class ReaderChapterGrant(models.Model):
    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chapter_grants",
        verbose_name="閱讀者",
    )
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="reader_grants", verbose_name="章節")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_chapter_permissions",
        verbose_name="授權者",
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["chapter__novel__title", "chapter__sort_order"]
        verbose_name = "章節授權"
        verbose_name_plural = "章節授權"
        constraints = [
            models.UniqueConstraint(fields=["reader", "chapter"], name="unique_reader_chapter_grant"),
        ]

    def __str__(self) -> str:
        return f"{self.reader} -> {self.chapter}"


class BasePage(models.Model):
    chapter_version = models.ForeignKey(
        ChapterVersion,
        on_delete=models.CASCADE,
        related_name="base_pages",
        verbose_name="章節版本",
    )
    device_profile = models.CharField("裝置", max_length=20, choices=DeviceProfile.choices)
    page_index = models.PositiveIntegerField("頁碼")
    relative_path = models.CharField("相對路徑", max_length=255)
    char_count = models.PositiveIntegerField("中文字數", default=0)
    image_width = models.PositiveIntegerField("圖片寬度", default=0)
    image_height = models.PositiveIntegerField("圖片高度", default=0)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["page_index"]
        verbose_name = "基底圖"
        verbose_name_plural = "基底圖"
        constraints = [
            models.UniqueConstraint(
                fields=["chapter_version", "device_profile", "page_index"],
                name="unique_base_page",
            ),
        ]

    @property
    def absolute_path(self) -> Path:
        return Path(settings.MEDIA_ROOT) / self.relative_path


class DailyPageCache(models.Model):
    chapter_version = models.ForeignKey(
        ChapterVersion,
        on_delete=models.CASCADE,
        related_name="daily_pages",
        verbose_name="章節版本",
    )
    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_pages",
        verbose_name="閱讀者",
    )
    device_profile = models.CharField("裝置", max_length=20, choices=DeviceProfile.choices)
    for_date = models.DateField("日期")
    page_index = models.PositiveIntegerField("頁碼")
    relative_path = models.CharField("相對路徑", max_length=255)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["page_index"]
        verbose_name = "每日快取圖"
        verbose_name_plural = "每日快取圖"
        constraints = [
            models.UniqueConstraint(
                fields=["chapter_version", "reader", "device_profile", "for_date", "page_index"],
                name="unique_daily_page",
            ),
        ]

    @property
    def absolute_path(self) -> Path:
        return Path(settings.MEDIA_ROOT) / self.relative_path


class AuditLog(models.Model):
    class EventType(models.TextChoices):
        LOGIN_SUCCESS = "login_success", "登入成功"
        LOGIN_FAILURE = "login_failure", "登入失敗"
        PASSWORD_CHANGED = "password_changed", "密碼變更"
        CHAPTER_PUBLISHED = "chapter_published", "章節發布"
        CHAPTER_OPENED = "chapter_opened", "章節開啟"
        WATERMARK_EXTRACTED = "watermark_extracted", "浮水印提取"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="使用者",
    )
    event_type = models.CharField("事件類型", max_length=50, choices=EventType.choices)
    ip_address = models.GenericIPAddressField("IP 位址", null=True, blank=True)
    details = models.JSONField("事件細節", default=dict, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "稽核紀錄"
        verbose_name_plural = "稽核紀錄"

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class WatermarkExtractionRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待中"
        RUNNING = "running", "執行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失敗"
        CANCELED = "canceled", "已取消"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="watermark_extraction_records",
        verbose_name="建立者",
    )
    status = models.CharField("狀態", max_length=20, choices=Status.choices, default=Status.PENDING)
    source_filename = models.CharField("來源檔名", max_length=255)
    upload_relative_path = models.CharField("上傳相對路徑", max_length=255)
    image_width = models.PositiveIntegerField("圖片寬度", default=0)
    image_height = models.PositiveIntegerField("圖片高度", default=0)
    raw_payload = models.TextField("原始輸出", blank=True)
    parsed_reader_id = models.CharField("解析後 reader_id", max_length=16, blank=True)
    parsed_yyyymmdd = models.CharField("解析後日期", max_length=8, blank=True)
    is_valid = models.BooleanField("提取成功", default=False)
    selected_method = models.CharField("採用方法", max_length=160, blank=True)
    attempt_count = models.PositiveIntegerField("嘗試次數", default=0)
    duration_ms = models.PositiveIntegerField("耗時毫秒", default=0)
    advanced_extraction = models.BooleanField("啟用進階 Blind 提取", default=False)
    process_log = models.JSONField("處理紀錄", default=list, blank=True)
    error_message = models.TextField("錯誤訊息", blank=True)
    celery_task_id = models.CharField("Celery Task ID", max_length=100, blank=True)
    cancel_requested = models.BooleanField("已要求取消", default=False)
    started_at = models.DateTimeField("開始時間", null=True, blank=True)
    finished_at = models.DateTimeField("完成時間", null=True, blank=True)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "浮水印提取紀錄"
        verbose_name_plural = "浮水印提取紀錄"

    @property
    def absolute_upload_path(self) -> Path:
        return Path(settings.MEDIA_ROOT) / self.upload_relative_path

    def __str__(self) -> str:
        return f"{self.source_filename} ({self.get_status_display()})"
