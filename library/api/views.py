from __future__ import annotations

import json
import time

from django.core.cache import cache
from django.db import connection
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from library.models import Chapter, ChapterPublishJob, WatermarkExtractionRecord
from library.services.watermark_records import request_extraction_stop

from .serializers import ExtractionRecordSerializer, HealthCheckSerializer, PublishJobStatusSerializer


class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and getattr(request.user, "role", None) == "admin"


# ---------------------------------------------------------------------------
# Health check (no auth)
# ---------------------------------------------------------------------------

@extend_schema(responses=HealthCheckSerializer)
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def health_check(request):
    db_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        db_ok = False

    cache_ok = True
    try:
        cache.set("_health", 1, 5)
        cache.get("_health")
    except Exception:
        cache_ok = False

    all_ok = db_ok and cache_ok
    data = {"db": db_ok, "cache": cache_ok, "status": "ok" if all_ok else "degraded"}
    return Response(data, status=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Publish status
# ---------------------------------------------------------------------------

def _latest_publish_job(chapter_id: int) -> ChapterPublishJob | None:
    return (
        ChapterPublishJob.objects.filter(chapter_id=chapter_id)
        .select_related("chapter", "chapter_version")
        .order_by("-created_at")
        .first()
    )


def _serialize_publish_job(chapter: Chapter, job: ChapterPublishJob | None) -> dict:
    if job is None:
        return {
            "exists": False,
            "job_id": None,
            "status": "",
            "status_display": "",
            "progress_percent": 0,
            "step_label": "",
            "error_message": "",
            "chapter_status": chapter.status,
            "chapter_status_display": chapter.get_status_display(),
        }
    return {
        "exists": True,
        "job_id": job.id,
        "status": job.status,
        "status_display": job.get_status_display(),
        "progress_percent": int(job.progress_percent or 0),
        "step_label": job.step_label or "",
        "error_message": job.error_message or "",
        "chapter_status": chapter.status,
        "chapter_status_display": chapter.get_status_display(),
    }


@extend_schema(responses=PublishJobStatusSerializer)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def chapter_publish_status(request, chapter_id: int):
    chapter = get_object_or_404(Chapter, pk=chapter_id)
    payload = _serialize_publish_job(chapter, _latest_publish_job(chapter.id))
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def chapter_publish_progress_sse(request, chapter_id: int):
    chapter = get_object_or_404(Chapter, pk=chapter_id)

    def event_stream():
        while True:
            job = _latest_publish_job(chapter_id)
            data = json.dumps(_serialize_publish_job(chapter, job))
            yield f"data: {data}\n\n"
            if job is None or not job.is_active:
                yield "event: done\ndata: {}\n\n"
                return
            time.sleep(2)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# ---------------------------------------------------------------------------
# Extraction status
# ---------------------------------------------------------------------------

def _log_entries(record: WatermarkExtractionRecord) -> list[dict]:
    return [entry for entry in list(record.process_log or []) if isinstance(entry, dict)]


def _entries_for_prefix(record: WatermarkExtractionRecord, prefix: str) -> list[dict]:
    return [entry for entry in _log_entries(record) if str(entry.get("stage", "")).startswith(prefix)]


def _summary_entry(record: WatermarkExtractionRecord, stage_name: str) -> dict | None:
    for entry in reversed(_log_entries(record)):
        if entry.get("stage") == stage_name:
            return entry
    return None


def _visible_preview_payload(record: WatermarkExtractionRecord) -> list[dict]:
    previews: list[dict] = []
    for entry in _entries_for_prefix(record, "visible_"):
        preview_url = entry.get("preview_url")
        if not preview_url:
            continue
        previews.append(
            {
                "label": entry.get("label") or "顯影結果",
                "preview_url": preview_url,
                "preview_relative_path": entry.get("preview_relative_path") or "",
            }
        )
    return previews


def _blind_result_payload(entry: dict | None) -> dict | None:
    if entry is None:
        return None
    return {
        "label": entry.get("label") or "",
        "success": bool(entry.get("success")),
        "duration_ms": int(entry.get("duration_ms") or 0),
        "message": entry.get("message") or "",
        "raw_preview": entry.get("raw_preview") or "",
        "reader_id": entry.get("reader_id") or "",
        "yyyymmdd": entry.get("yyyymmdd") or "",
        "selected_method": entry.get("selected_method") or "",
    }


def _serialize_extraction(record: WatermarkExtractionRecord) -> dict:
    s = record.status
    return {
        "id": record.id,
        "source_filename": record.source_filename,
        "status": s,
        "status_display": record.get_status_display(),
        "is_finished": s not in {WatermarkExtractionRecord.Status.PENDING, WatermarkExtractionRecord.Status.RUNNING},
        "cancel_requested": bool(record.cancel_requested),
        "image_width": int(record.image_width or 0),
        "image_height": int(record.image_height or 0),
        "attempt_count": int(record.attempt_count or 0),
        "duration_ms": int(record.duration_ms or 0),
        "selected_method": record.selected_method or "",
        "raw_payload": record.raw_payload or "",
        "parsed_reader_id": record.parsed_reader_id or "",
        "parsed_yyyymmdd": record.parsed_yyyymmdd or "",
        "is_valid": bool(record.is_valid),
        "error_message": record.error_message or "",
        "advanced_extraction": bool(record.advanced_extraction),
        "visible_previews": _visible_preview_payload(record),
        "blind_direct": _blind_result_payload(_summary_entry(record, "blind_direct_summary")),
        "blind_advanced": _blind_result_payload(_summary_entry(record, "blind_advanced_summary")),
        "process_log": _log_entries(record),
    }


@extend_schema(responses=ExtractionRecordSerializer)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def extraction_status(request, record_id: int):
    record = get_object_or_404(WatermarkExtractionRecord.objects.select_related("created_by"), pk=record_id)
    return Response(_serialize_extraction(record))


@api_view(["GET"])
@permission_classes([IsAdminUser])
def extraction_progress_sse(request, record_id: int):
    get_object_or_404(WatermarkExtractionRecord, pk=record_id)

    def event_stream():
        while True:
            record = WatermarkExtractionRecord.objects.get(pk=record_id)
            data = json.dumps(_serialize_extraction(record))
            yield f"data: {data}\n\n"
            if record.status not in {WatermarkExtractionRecord.Status.PENDING, WatermarkExtractionRecord.Status.RUNNING}:
                yield "event: done\ndata: {}\n\n"
                return
            time.sleep(2)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@api_view(["POST"])
@permission_classes([IsAdminUser])
def extraction_stop(request, record_id: int):
    record = get_object_or_404(WatermarkExtractionRecord.objects.select_related("created_by"), pk=record_id)
    request_extraction_stop(record)
    record.refresh_from_db()
    return Response(_serialize_extraction(record))


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

try:
    from drf_spectacular.views import SpectacularAPIView
    schema_view = SpectacularAPIView.as_view()
except ImportError:
    @api_view(["GET"])
    @permission_classes([permissions.AllowAny])
    def schema_view(request):
        return Response({"error": "drf-spectacular not installed"}, status=501)
