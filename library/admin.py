from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.urls import reverse
from django.utils.html import format_html

from library.forms import AntiOcrPresetAdminForm, ChapterAdminForm, NovelAdminForm
from library.models import (
    AntiOcrPreset,
    AuditLog,
    BasePage,
    Chapter,
    ChapterVersion,
    CustomFontUpload,
    DailyPageCache,
    Novel,
    ReaderChapterGrant,
    ReaderNovelGrant,
    ReaderSiteGrant,
    WatermarkExtractionRecord,
)
from library.services.anti7ocr_config import summarize_preset
from library.services.publishing import schedule_chapter_publish

admin.site.site_header = "CatchingRat 管理後台"
admin.site.site_title = "CatchingRat 管理後台"
admin.site.index_title = "Django admin 備援入口"


@admin.register(Novel)
class NovelAdmin(admin.ModelAdmin):
    form = NovelAdminForm
    list_display = ("title", "slug", "is_active", "updated_at")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(AntiOcrPreset)
class AntiOcrPresetAdmin(admin.ModelAdmin):
    form = AntiOcrPresetAdminForm
    list_display = ("name", "is_default", "base_preset_name", "desktop_summary", "mobile_summary", "updated_at")
    list_filter = ("is_default", "base_preset_name")
    search_fields = ("name", "base_preset_name")
    fieldsets = tuple(
        (
            group["title"],
            {
                "fields": group["fields"],
                "description": group["description"],
            },
        )
        for group in AntiOcrPresetAdminForm.group_definitions
    )

    @admin.display(description="桌機摘要")
    def desktop_summary(self, obj: AntiOcrPreset) -> str:
        summary = summarize_preset(obj.as_snapshot())
        return f'{summary["desktop_width"]} px / 字級 {summary["desktop_font_range"]}'

    @admin.display(description="手機摘要")
    def mobile_summary(self, obj: AntiOcrPreset) -> str:
        summary = summarize_preset(obj.as_snapshot())
        return f'{summary["mobile_width"]} px / 字級 {summary["mobile_font_range"]}'


@admin.register(CustomFontUpload)
class CustomFontUploadAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "font_file", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "font_file")


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    form = ChapterAdminForm
    list_display = ("title", "novel", "status", "sort_order", "published_at", "publish_link")
    list_filter = ("status", "novel")
    search_fields = ("title", "novel__title", "content")
    autocomplete_fields = ("novel", "anti_ocr_preset", "current_version")
    actions = ("publish_selected",)
    fieldsets = (
        (
            "章節內容",
            {
                "fields": ("novel", "title", "sort_order", "status", "content"),
                "description": "正式發布時會先完成桌機與手機兩套基底圖，完成後才讓讀者看到。",
            },
        ),
        (
            "發布資訊",
            {
                "fields": ("anti_ocr_preset", "current_version", "published_at"),
            },
        ),
    )

    @admin.display(description="快速發布")
    def publish_link(self, obj: Chapter):
        return format_html('<a class="button" href="{}">立即發布</a>', reverse("backoffice:chapter-publish", args=[obj.pk]))

    @admin.action(description="發布選取章節")
    def publish_selected(self, request, queryset: QuerySet):
        for chapter in queryset:
            try:
                schedule_chapter_publish(chapter, actor=request.user, request=request)
            except ValueError:
                continue


@admin.register(ChapterVersion)
class ChapterVersionAdmin(admin.ModelAdmin):
    list_display = ("chapter", "version_number", "published_at", "created_by")
    list_filter = ("published_at",)
    readonly_fields = ("source_sha256", "preset_snapshot", "content")
    search_fields = ("chapter__title", "chapter__novel__title")


@admin.register(ReaderSiteGrant)
class ReaderSiteGrantAdmin(admin.ModelAdmin):
    list_display = ("reader", "granted_by", "created_at")
    search_fields = ("reader__username", "granted_by__username")
    autocomplete_fields = ("reader", "granted_by")


@admin.register(ReaderNovelGrant)
class ReaderNovelGrantAdmin(admin.ModelAdmin):
    list_display = ("reader", "novel", "granted_by", "created_at")
    search_fields = ("reader__username", "novel__title", "granted_by__username")
    autocomplete_fields = ("reader", "novel", "granted_by")


@admin.register(ReaderChapterGrant)
class ReaderChapterGrantAdmin(admin.ModelAdmin):
    list_display = ("reader", "chapter", "granted_by", "created_at")
    search_fields = ("reader__username", "chapter__title", "chapter__novel__title", "granted_by__username")
    autocomplete_fields = ("reader", "chapter", "granted_by")


@admin.register(BasePage)
class BasePageAdmin(admin.ModelAdmin):
    list_display = ("chapter_version", "device_profile", "page_index", "char_count", "image_width", "image_height")
    list_filter = ("device_profile",)
    readonly_fields = ("relative_path",)


@admin.register(DailyPageCache)
class DailyPageCacheAdmin(admin.ModelAdmin):
    list_display = ("chapter_version", "reader", "for_date", "device_profile", "page_index", "created_at")
    list_filter = ("device_profile", "for_date")
    readonly_fields = ("relative_path",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "ip_address", "created_at")
    list_filter = ("event_type", "created_at")
    readonly_fields = ("details",)


@admin.register(WatermarkExtractionRecord)
class WatermarkExtractionRecordAdmin(admin.ModelAdmin):
    list_display = (
        "source_filename",
        "status",
        "is_valid",
        "advanced_extraction",
        "parsed_reader_id",
        "parsed_yyyymmdd",
        "selected_method",
        "created_at",
    )
    list_filter = ("status", "is_valid", "created_at")
    search_fields = ("source_filename", "raw_payload", "parsed_reader_id", "parsed_yyyymmdd")
    readonly_fields = (
        "upload_relative_path",
        "raw_payload",
        "parsed_reader_id",
        "parsed_yyyymmdd",
        "is_valid",
        "selected_method",
        "attempt_count",
        "duration_ms",
        "advanced_extraction",
        "process_log",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
    )
