from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from celery import current_app
from django.db.models import Q
from django.utils import timezone
from django.utils.text import get_valid_filename

from accounts.models import User
from library.models import AuditLog, WatermarkExtractionRecord

from .audit import log_event
from .storage import ensure_parent, media_relative
from .visible_watermark import extract_visible_watermark_from_path
from .watermark import ExtractionStopped, extract_watermark_from_path

BLIND_EXTRACTION_KIND = "blind"
VISIBLE_EXTRACTION_KIND = "visible"

BLIND_UPLOAD_PREFIXES = ("watermark_extract_uploads/", "blind_watermark_extract_uploads/")
VISIBLE_UPLOAD_PREFIXES = ("visible_watermark_extract_uploads/",)


def get_extraction_kind_prefixes(kind: str) -> tuple[str, ...]:
    if kind == VISIBLE_EXTRACTION_KIND:
        return VISIBLE_UPLOAD_PREFIXES
    return BLIND_UPLOAD_PREFIXES


def get_extraction_kind_filter(kind: str) -> Q:
    query = Q()
    for prefix in get_extraction_kind_prefixes(kind):
        query |= Q(upload_relative_path__startswith=prefix)
    return query


def infer_extraction_kind(upload_relative_path: str) -> str:
    for prefix in VISIBLE_UPLOAD_PREFIXES:
        if upload_relative_path.startswith(prefix):
            return VISIBLE_EXTRACTION_KIND
    return BLIND_EXTRACTION_KIND


def extraction_upload_relative_path(filename: str, *, kind: str) -> str:
    safe_name = get_valid_filename(Path(filename).name) or "upload.png"
    today = timezone.localdate().strftime("%Y%m%d")
    root = "visible_watermark_extract_uploads" if kind == VISIBLE_EXTRACTION_KIND else "watermark_extract_uploads"
    return media_relative(root, today, f"{timezone.now():%H%M%S}-{uuid4().hex[:12]}-{safe_name}")


def create_extraction_record(
    uploaded_file,
    *,
    actor: User | None = None,
    kind: str = BLIND_EXTRACTION_KIND,
    advanced_extraction: bool = False,
) -> WatermarkExtractionRecord:
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    file_bytes = uploaded_file.read()
    image = cv2.imdecode(np.frombuffer(file_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    image_width = image.shape[1] if image is not None else 0
    image_height = image.shape[0] if image is not None else 0

    relative_path = extraction_upload_relative_path(uploaded_file.name, kind=kind)
    absolute_path = ensure_parent(relative_path)
    absolute_path.write_bytes(file_bytes)

    return WatermarkExtractionRecord.objects.create(
        created_by=actor,
        source_filename=uploaded_file.name,
        upload_relative_path=relative_path,
        image_width=image_width,
        image_height=image_height,
        advanced_extraction=advanced_extraction,
        process_log=[
            {
                "stage": "upload",
                "label": "Upload received",
                "success": True,
                "duration_ms": 0,
                "message": f"Image uploaded ({image_width}x{image_height}).",
                "advanced_extraction": bool(advanced_extraction),
            }
        ],
    )


def append_extraction_log(record: WatermarkExtractionRecord, entry: dict) -> None:
    current_log = list(record.process_log or [])
    current_log.append(entry)
    record.process_log = current_log
    record.save(update_fields=["process_log"])


def request_extraction_stop(record: WatermarkExtractionRecord) -> None:
    if record.status not in {
        WatermarkExtractionRecord.Status.PENDING,
        WatermarkExtractionRecord.Status.RUNNING,
    }:
        return
    record.cancel_requested = True
    record.save(update_fields=["cancel_requested"])
    if record.celery_task_id:
        current_app.control.revoke(record.celery_task_id, terminate=False)


def _prefixed_entry(prefix: str, entry: dict) -> dict:
    copied = dict(entry)
    stage = str(copied.get("stage") or "step")
    copied["stage"] = f"{prefix}_{stage}"
    return copied


def _append_blind_summary(
    record: WatermarkExtractionRecord,
    *,
    stage: str,
    label: str,
    result: dict,
    method_prefix: str,
) -> None:
    parsed = result.get("parsed")
    message = "Blind Watermark 成功提取。"
    if parsed is None:
        message = "Blind Watermark 尚未成功提取。"
    append_extraction_log(
        record,
        {
            "stage": stage,
            "label": label,
            "success": parsed is not None,
            "duration_ms": int(result.get("duration_ms") or 0),
            "message": message,
            "raw_preview": result.get("raw_payload", ""),
            "reader_id": parsed["reader_id"] if parsed else "",
            "yyyymmdd": parsed["yyyymmdd"] if parsed else "",
            "selected_method": (
                f"{method_prefix} / {result['selected_method']}"
                if result.get("selected_method")
                else method_prefix
            ),
        },
    )


def process_extraction_record(
    record_id: int,
    *,
    kind: str | None = None,
    task_id: str | None = None,
) -> WatermarkExtractionRecord:
    record = WatermarkExtractionRecord.objects.get(pk=record_id)
    extractor_kind = kind or infer_extraction_kind(record.upload_relative_path)
    if task_id:
        record.celery_task_id = task_id

    if record.cancel_requested:
        record.status = WatermarkExtractionRecord.Status.CANCELED
        record.finished_at = timezone.now()
        record.save(update_fields=["status", "finished_at", "celery_task_id"])
        append_extraction_log(
            record,
            {
                "stage": "finish",
                "label": "Canceled",
                "success": False,
                "duration_ms": 0,
                "message": "Extraction was canceled before start.",
            },
        )
        return record

    record.status = WatermarkExtractionRecord.Status.RUNNING
    record.started_at = timezone.now()
    record.error_message = ""
    record.save(update_fields=["status", "started_at", "error_message", "celery_task_id"])
    append_extraction_log(
        record,
        {
            "stage": "start",
            "label": "Start",
            "success": True,
            "duration_ms": 0,
            "message": (
                "Started combined watermark extraction."
                if extractor_kind == BLIND_EXTRACTION_KIND
                else "Started visible watermark extraction."
            ),
        },
    )

    checks = {"count": 0}

    def should_stop() -> bool:
        checks["count"] += 1
        if checks["count"] % 6:
            return False
        return WatermarkExtractionRecord.objects.filter(pk=record.id, cancel_requested=True).exists()

    def make_progress_callback(prefix: str):
        def _callback(entry: dict) -> None:
            if should_stop():
                raise ExtractionStopped("Extraction canceled by user.")
            append_extraction_log(record, _prefixed_entry(prefix, entry))

        return _callback

    try:
        visible_result = extract_visible_watermark_from_path(
            str(record.absolute_upload_path),
            progress_callback=make_progress_callback("visible"),
            debug_prefix=f"record-{record.id}",
            should_stop=should_stop,
        )
        append_extraction_log(
            record,
            {
                "stage": "visible_summary",
                "label": "可見浮水印顯影",
                "success": bool(visible_result.get("is_valid")),
                "duration_ms": int(visible_result.get("duration_ms") or 0),
                "message": f"已產生 {int(visible_result.get('attempt_count') or 0)} 張顯影圖。",
                "selected_method": visible_result.get("selected_method", ""),
            },
        )

        direct_result = extract_watermark_from_path(
            str(record.absolute_upload_path),
            allow_crops=False,
            progress_callback=make_progress_callback("blind_direct"),
            should_stop=should_stop,
        )
        _append_blind_summary(
            record,
            stage="blind_direct_summary",
            label="Blind 原圖直接提取",
            result=direct_result,
            method_prefix="blind direct",
        )

        final_result = direct_result
        if direct_result.get("parsed") is None and record.advanced_extraction:
            append_extraction_log(
                record,
                {
                    "stage": "blind_advanced_start",
                    "label": "進入進階 Blind 提取",
                    "success": False,
                    "duration_ms": 0,
                    "message": "開始執行裁切、來源比對與其他進階 Blind 提取流程。",
                },
            )
            advanced_result = extract_watermark_from_path(
                str(record.absolute_upload_path),
                allow_crops=True,
                progress_callback=make_progress_callback("blind_advanced"),
                should_stop=should_stop,
            )
            _append_blind_summary(
                record,
                stage="blind_advanced_summary",
                label="Blind 進階提取",
                result=advanced_result,
                method_prefix="blind advanced",
            )
            final_result = advanced_result
    except ExtractionStopped as exc:
        record.status = WatermarkExtractionRecord.Status.CANCELED
        record.error_message = str(exc)
        record.finished_at = timezone.now()
        record.save(update_fields=["status", "error_message", "finished_at"])
        append_extraction_log(
            record,
            {
                "stage": "finish",
                "label": "Canceled",
                "success": False,
                "duration_ms": 0,
                "message": "Extraction was canceled by user.",
            },
        )
        return record
    except Exception as exc:
        record.status = WatermarkExtractionRecord.Status.FAILED
        record.error_message = str(exc)
        record.finished_at = timezone.now()
        record.save(update_fields=["status", "error_message", "finished_at"])
        append_extraction_log(
            record,
            {
                "stage": "finish",
                "label": "Failed",
                "success": False,
                "duration_ms": 0,
                "message": f"Extraction failed: {exc}",
            },
        )
        return record

    final_parsed = final_result.get("parsed")
    record.raw_payload = final_result.get("raw_payload", "")
    record.attempt_count = int(final_result.get("attempt_count") or 0)
    record.duration_ms = int(final_result.get("duration_ms") or 0)
    record.finished_at = timezone.now()

    if final_parsed is not None:
        record.parsed_reader_id = final_parsed["reader_id"]
        record.parsed_yyyymmdd = final_parsed["yyyymmdd"]
        record.is_valid = True
        record.selected_method = (
            f"blind / {final_result['selected_method']}"
            if final_result.get("selected_method")
            else "blind"
        )
        record.status = WatermarkExtractionRecord.Status.SUCCEEDED
        finish_message = f"Blind 提取成功：{record.parsed_reader_id}|{record.parsed_yyyymmdd}"
        finish_success = True
    elif visible_result.get("is_valid"):
        record.parsed_reader_id = ""
        record.parsed_yyyymmdd = ""
        record.is_valid = True
        record.selected_method = (
            f"visible / {visible_result['selected_method']}"
            if visible_result.get("selected_method")
            else "visible"
        )
        record.status = WatermarkExtractionRecord.Status.SUCCEEDED
        if record.advanced_extraction:
            finish_message = "可見浮水印顯影圖已產生；Blind 直接與進階提取都未成功。"
        else:
            finish_message = "可見浮水印顯影圖已產生；Blind 原圖直接提取未成功。"
        finish_success = True
    else:
        record.parsed_reader_id = ""
        record.parsed_yyyymmdd = ""
        record.is_valid = False
        record.selected_method = final_result.get("selected_method", "")
        record.status = WatermarkExtractionRecord.Status.FAILED
        finish_message = "Visible 與 Blind 提取都未得到可用結果。"
        finish_success = False

    append_extraction_log(
        record,
        {
            "stage": "finish",
            "label": "Finished",
            "success": finish_success,
            "duration_ms": 0,
            "message": finish_message,
        },
    )
    record.save(
        update_fields=[
            "raw_payload",
            "is_valid",
            "selected_method",
            "attempt_count",
            "duration_ms",
            "finished_at",
            "parsed_reader_id",
            "parsed_yyyymmdd",
            "status",
        ]
    )

    log_event(
        AuditLog.EventType.WATERMARK_EXTRACTED,
        user=record.created_by,
        details={
            "record_id": record.id,
            "status": record.status,
            "is_valid": record.is_valid,
            "reader_id": record.parsed_reader_id,
            "yyyymmdd": record.parsed_yyyymmdd,
            "selected_method": record.selected_method,
            "attempt_count": record.attempt_count,
            "extractor_kind": extractor_kind,
            "advanced_extraction": record.advanced_extraction,
        },
    )
    return record
