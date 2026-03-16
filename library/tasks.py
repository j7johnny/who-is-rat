from __future__ import annotations

from datetime import date

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from library.models import ChapterPublishJob, ChapterVersion
from library.services.audit import log_event
from library.services.publishing import (
    build_remaining_daily_pages,
    cleanup_daily_cache,
    cleanup_failed_version,
    finalize_chapter_publish,
    render_base_pages_for_version,
)
from library.services.watermark_records import process_extraction_record


def _update_publish_job(job: ChapterPublishJob, **fields) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    if fields:
        update_fields = list(fields.keys())
        if "status" in fields and "finished_at" not in fields and fields["status"] in {
            ChapterPublishJob.Status.SUCCEEDED,
            ChapterPublishJob.Status.FAILED,
            ChapterPublishJob.Status.CANCELED,
        }:
            job.finished_at = timezone.now()
            update_fields.append("finished_at")
        job.save(update_fields=update_fields)


def _is_job_cancel_requested(job_id: int) -> bool:
    return ChapterPublishJob.objects.filter(pk=job_id, cancel_requested=True).exists()


@shared_task(bind=True, queue="publish")
def run_chapter_publish_job_task(self, publish_job_id: int) -> int:
    job = ChapterPublishJob.objects.select_related("chapter", "chapter_version", "created_by").get(pk=publish_job_id)
    if job.cancel_requested:
        _update_publish_job(
            job,
            status=ChapterPublishJob.Status.CANCELED,
            progress_percent=0,
            step_label="Canceled before start",
            finished_at=timezone.now(),
        )
        cleanup_failed_version(job.chapter_version)
        return job.id

    _update_publish_job(
        job,
        status=ChapterPublishJob.Status.RUNNING,
        progress_percent=5,
        step_label="開始產製桌機版基底圖…",
        started_at=timezone.now(),
        celery_task_id=self.request.id or job.celery_task_id,
    )

    def _desktop_progress(current: int, total: int) -> None:
        pct = 5 + int(40 * current / max(total, 1))
        _update_publish_job(job, progress_percent=pct, step_label=f"桌機版基底圖 {current}/{total} 頁")

    def _mobile_progress(current: int, total: int) -> None:
        pct = 50 + int(40 * current / max(total, 1))
        _update_publish_job(job, progress_percent=pct, step_label=f"手機版基底圖 {current}/{total} 頁")

    try:
        render_base_pages_for_version(job.chapter_version, "desktop", force=True, progress_callback=_desktop_progress)
        if _is_job_cancel_requested(job.id):
            raise RuntimeError("PUBLISH_JOB_CANCELED")
        _update_publish_job(job, progress_percent=50, step_label="開始產製手機版基底圖…")

        render_base_pages_for_version(job.chapter_version, "mobile", force=True, progress_callback=_mobile_progress)
        if _is_job_cancel_requested(job.id):
            raise RuntimeError("PUBLISH_JOB_CANCELED")
        _update_publish_job(job, progress_percent=92, step_label="正在完成發布…")

        with transaction.atomic():
            finalize_chapter_publish(job.chapter, job.chapter_version)

        _update_publish_job(
            job,
            status=ChapterPublishJob.Status.SUCCEEDED,
            progress_percent=100,
            step_label="發布完成",
            finished_at=timezone.now(),
        )
        log_event(
            "chapter_published",
            user=job.created_by,
            details={
                "chapter_id": job.chapter_id,
                "chapter_version_id": job.chapter_version_id,
                "publish_job_id": job.id,
            },
        )
        return job.id
    except RuntimeError as exc:
        if str(exc) != "PUBLISH_JOB_CANCELED":
            raise
        cleanup_failed_version(job.chapter_version)
        _update_publish_job(
            job,
            status=ChapterPublishJob.Status.CANCELED,
            progress_percent=0,
            step_label="Canceled",
            finished_at=timezone.now(),
        )
        return job.id
    except Exception as exc:
        cleanup_failed_version(job.chapter_version)
        _update_publish_job(
            job,
            status=ChapterPublishJob.Status.FAILED,
            progress_percent=0,
            step_label="Failed",
            error_message=str(exc),
            finished_at=timezone.now(),
        )
        return job.id


@shared_task
def render_base_pages_task(chapter_version_id: int, device_profile: str) -> int:
    chapter_version = ChapterVersion.objects.get(pk=chapter_version_id)
    pages = render_base_pages_for_version(chapter_version, device_profile, force=True)
    return len(pages)


@shared_task
def build_daily_pages_task(
    chapter_version_id: int,
    reader_id: int,
    for_date_iso: str,
    device_profile: str,
    start_page: int = 1,
) -> None:
    chapter_version = ChapterVersion.objects.get(pk=chapter_version_id)
    reader = User.objects.get(pk=reader_id)
    build_remaining_daily_pages(
        chapter_version,
        reader,
        date.fromisoformat(for_date_iso),
        device_profile,
        start_page=start_page,
    )


@shared_task
def cleanup_daily_cache_task() -> int:
    return cleanup_daily_cache()


@shared_task(bind=True, queue="extract")
def run_watermark_extraction_task(self, record_id: int, kind: str | None = None) -> int:
    record = process_extraction_record(record_id, kind=kind, task_id=self.request.id)
    return record.id
