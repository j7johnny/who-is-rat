from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import threading

from django.conf import settings
from django import db
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import User
from library.models import (
    BasePage,
    Chapter,
    ChapterPublishJob,
    ChapterStatus,
    ChapterVersion,
    DailyPageCache,
    DeviceProfile,
)

from .antiocr import (
    build_source_sha256,
    get_default_preset,
    render_chapter_page_images,
    save_base_page_image,
)
from .audit import log_event
from .signing import build_signed_page_key
from .storage import delete_relative_path, ensure_parent, media_relative
from .visible_watermark import build_visible_watermark_payload, embed_visible_watermark
from .watermark import build_watermark_payload, embed_watermark

daily_page_layout_version = "v10"


def _run_in_background_thread(func, *args):
    """Run a callable in a daemon thread, closing DB connections afterward."""
    def _wrapper():
        try:
            func(*args)
        finally:
            db.connections.close_all()
    thread = threading.Thread(target=_wrapper, daemon=True)
    thread.start()
    return thread


def _maybe_enqueue(task, *args, eager_mode: str = "skip"):
    if settings.CELERY_TASK_ALWAYS_EAGER:
        if eager_mode == "sync":
            task(*args)
        elif eager_mode == "thread":
            _run_in_background_thread(task, *args)
        return
    with contextlib.suppress(Exception):
        task.delay(*args)


def delete_queryset_files(queryset) -> None:
    for item in queryset:
        delete_relative_path(item.relative_path)
    queryset.delete()


def purge_old_assets_for_chapter(chapter: Chapter, keep_version_id: int) -> None:
    old_versions = chapter.versions.exclude(id=keep_version_id)
    delete_queryset_files(BasePage.objects.filter(chapter_version__in=old_versions))
    delete_queryset_files(DailyPageCache.objects.filter(chapter_version__in=old_versions))


def build_chapter_version(chapter: Chapter, actor: User | None = None) -> ChapterVersion:
    preset = chapter.anti_ocr_preset or get_default_preset()
    latest_version = chapter.versions.aggregate(max_version=Max("version_number"))["max_version"] or 0
    return ChapterVersion.objects.create(
        chapter=chapter,
        version_number=latest_version + 1,
        content=chapter.content,
        source_sha256=build_source_sha256(chapter.content),
        preset_snapshot=preset.as_snapshot(),
        created_by=actor,
        published_at=timezone.now(),
    )


def finalize_chapter_publish(chapter: Chapter, version: ChapterVersion) -> None:
    with transaction.atomic():
        chapter.refresh_from_db()
        chapter.current_version = version
        chapter.status = ChapterStatus.PUBLISHED
        chapter.published_at = timezone.now()
        chapter.save(update_fields=["current_version", "status", "published_at", "updated_at"])
        purge_old_assets_for_chapter(chapter, version.id)


def cleanup_failed_version(version: ChapterVersion) -> None:
    delete_queryset_files(BasePage.objects.filter(chapter_version=version))
    if version.pk:
        version.delete()


def active_publish_job_for_chapter(chapter: Chapter) -> ChapterPublishJob | None:
    return (
        ChapterPublishJob.objects.filter(
            chapter=chapter,
            status__in=[ChapterPublishJob.Status.PENDING, ChapterPublishJob.Status.RUNNING],
        )
        .order_by("-created_at")
        .first()
    )


def publish_chapter(chapter: Chapter, actor: User | None = None, request=None) -> ChapterVersion:
    if not chapter.content.strip():
        raise ValueError("章節全文不可為空，請先貼入內容再發布。")
    version = build_chapter_version(chapter, actor=actor)

    try:
        render_base_pages_for_version(version, DeviceProfile.DESKTOP, force=True)
        render_base_pages_for_version(version, DeviceProfile.MOBILE, force=True)
    except Exception:
        cleanup_failed_version(version)
        raise

    finalize_chapter_publish(chapter, version)

    log_event(
        "chapter_published",
        user=actor,
        request=request,
        details={"chapter_id": chapter.id, "chapter_version_id": version.id},
    )
    return version


def schedule_chapter_publish(chapter: Chapter, actor: User | None = None, request=None) -> ChapterPublishJob:
    if not chapter.content.strip():
        raise ValueError("章節全文不可為空，請先貼入內容再發布。")

    existing_job = active_publish_job_for_chapter(chapter)
    if existing_job is not None:
        return existing_job

    version = build_chapter_version(chapter, actor=actor)
    job = ChapterPublishJob.objects.create(
        chapter=chapter,
        chapter_version=version,
        status=ChapterPublishJob.Status.PENDING,
        progress_percent=5,
        step_label="Queued",
        created_by=actor,
    )

    from library.tasks import run_chapter_publish_job_task

    if settings.CELERY_TASK_ALWAYS_EAGER:
        _run_in_background_thread(run_chapter_publish_job_task, job.id)
    else:
        async_result = run_chapter_publish_job_task.delay(job.id)
        ChapterPublishJob.objects.filter(pk=job.pk).update(celery_task_id=async_result.id)
        job.celery_task_id = async_result.id

    log_event(
        "chapter_publish_queued",
        user=actor,
        request=request,
        details={"chapter_id": chapter.id, "chapter_version_id": version.id, "job_id": job.id},
    )
    return job


def render_base_pages_for_version(
    chapter_version: ChapterVersion,
    device_profile: str,
    force: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[BasePage]:
    if force:
        delete_queryset_files(BasePage.objects.filter(chapter_version=chapter_version, device_profile=device_profile))

    rendered_pages = render_chapter_page_images(
        chapter_version.content,
        chapter_version.preset_snapshot,
        device_profile,
    )
    total = len(rendered_pages)

    pages: list[BasePage] = []
    try:
        for index, (image, char_count) in enumerate(rendered_pages, start=1):
            pages.append(save_base_page_image(chapter_version, device_profile, index, image, char_count))
            image.close()
            if progress_callback:
                progress_callback(index, total)
    finally:
        for image, _ in rendered_pages[len(pages):]:
            image.close()

    stale_pages = BasePage.objects.filter(
        chapter_version=chapter_version,
        device_profile=device_profile,
        page_index__gt=len(rendered_pages),
    )
    delete_queryset_files(stale_pages)
    return pages


def ensure_base_pages(chapter_version: ChapterVersion, device_profile: str) -> list[BasePage]:
    pages = list(
        BasePage.objects.filter(chapter_version=chapter_version, device_profile=device_profile).order_by("page_index")
    )
    if not pages:
        return render_base_pages_for_version(chapter_version, device_profile, force=True)
    if any(not page.absolute_path.exists() for page in pages):
        return render_base_pages_for_version(chapter_version, device_profile, force=True)
    return pages


def ensure_base_page(chapter_version: ChapterVersion, device_profile: str, page_index: int) -> BasePage:
    pages = ensure_base_pages(chapter_version, device_profile)
    if page_index < 1 or page_index > len(pages):
        raise IndexError("page_index out of range")
    return pages[page_index - 1]


def get_page_count(chapter_version: ChapterVersion, device_profile: str) -> int:
    return len(ensure_base_pages(chapter_version, device_profile))


def daily_page_relative_path(
    chapter_version_id: int,
    reader_id: int,
    for_date: date,
    device_profile: str,
    page_index: int,
) -> str:
    return media_relative(
        "daily_pages",
        daily_page_layout_version,
        for_date.strftime("%Y%m%d"),
        f"reader_{reader_id}",
        f"version_{chapter_version_id}",
        device_profile,
        f"page_{page_index:04d}.png",
    )


def build_daily_page(
    chapter_version: ChapterVersion,
    reader: User,
    for_date: date,
    device_profile: str,
    page_index: int,
    *,
    base_page: BasePage | None = None,
) -> DailyPageCache:
    page = DailyPageCache.objects.filter(
        chapter_version=chapter_version,
        reader=reader,
        for_date=for_date,
        device_profile=device_profile,
        page_index=page_index,
    ).first()
    expected_prefix = f"daily_pages/{daily_page_layout_version}/"
    if page and page.absolute_path.exists() and page.relative_path.startswith(expected_prefix):
        return page

    base_page = base_page or ensure_base_page(chapter_version, device_profile, page_index)
    relative_path = daily_page_relative_path(chapter_version.id, reader.id, for_date, device_profile, page_index)
    absolute_path = ensure_parent(relative_path)
    blind_payload = build_watermark_payload(reader.reader_id, for_date)
    visible_payload = build_visible_watermark_payload(reader.reader_id, for_date)
    file_descriptor, temp_name = tempfile.mkstemp(suffix=".png")
    temp_path = Path(temp_name)
    try:
        embed_watermark(
            str(base_page.absolute_path),
            str(temp_path),
            blind_payload,
            expected_reader_id=reader.reader_id,
            expected_yyyymmdd=for_date.strftime("%Y%m%d"),
        )
        embed_visible_watermark(
            str(temp_path),
            str(absolute_path),
            visible_payload,
            device_profile=device_profile,
        )
    finally:
        with contextlib.suppress(OSError):
            os.close(file_descriptor)
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()

    if page and page.relative_path != relative_path:
        delete_relative_path(page.relative_path)

    page, _ = DailyPageCache.objects.update_or_create(
        chapter_version=chapter_version,
        reader=reader,
        for_date=for_date,
        device_profile=device_profile,
        page_index=page_index,
        defaults={"relative_path": relative_path},
    )
    return page


def ensure_daily_bundle(
    chapter_version: ChapterVersion,
    reader: User,
    device_profile: str,
    for_date: date | None = None,
) -> dict:
    for_date = for_date or timezone.localdate()
    base_pages = ensure_base_pages(chapter_version, device_profile)
    page_count = len(base_pages)
    if page_count < 1:
        raise IndexError("No base pages available for chapter version.")
    first_page = build_daily_page(
        chapter_version,
        reader,
        for_date,
        device_profile,
        1,
        base_page=base_pages[0],
    )

    from library.tasks import build_daily_pages_task

    if page_count > 1:
        _maybe_enqueue(
            build_daily_pages_task,
            chapter_version.id,
            reader.id,
            for_date.isoformat(),
            device_profile,
            2,
            eager_mode="thread",
        )

    return {
        "first_page": first_page,
        "page_count": page_count,
        "signed_key": build_signed_page_key(chapter_version.id, reader.reader_id, for_date, device_profile),
    }


def build_remaining_daily_pages(
    chapter_version: ChapterVersion,
    reader: User,
    for_date: date,
    device_profile: str,
    start_page: int = 1,
) -> None:
    base_pages = ensure_base_pages(chapter_version, device_profile)
    page_count = len(base_pages)
    for page_index in range(start_page, page_count + 1):
        build_daily_page(
            chapter_version,
            reader,
            for_date,
            device_profile,
            page_index,
            base_page=base_pages[page_index - 1],
        )


def cleanup_daily_cache() -> int:
    cutoff = timezone.localdate() - timedelta(days=settings.DAILY_CACHE_RETENTION_DAYS)
    queryset = DailyPageCache.objects.filter(for_date__lt=cutoff)
    count = queryset.count()
    delete_queryset_files(queryset)
    return count
