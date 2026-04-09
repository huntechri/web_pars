import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from parser.full_auto_parser_CURL import CurlParser

from ..config import settings
from ..database import SessionLocal
from ..models import ParseJob, ParseResult
from .storage import is_object_storage_enabled, upload_csv


_lock = threading.Lock()
_progress_lock = threading.Lock()
_job_progress: dict[str, dict[str, Any]] = {}


def _save_job_results(db: Session, job_id: str, parsed_items: list[dict[str, Any]]) -> None:
    db.query(ParseResult).filter(ParseResult.job_id == job_id).delete()
    if not parsed_items:
        return

    rows = []
    for item in parsed_items:
        rows.append(
            ParseResult(
                job_id=job_id,
                article=item.get("article") or None,
                name=item.get("name") or "",
                unit=item.get("unit") or None,
                price=item.get("price") or None,
                brand=item.get("brand") or None,
                weight=item.get("weight") or None,
                level1=item.get("level1") or None,
                level2=item.get("level2") or None,
                level3=item.get("level3") or None,
                level4=item.get("level4") or None,
                image=item.get("image") or None,
                url=item.get("url") or None,
                supplier=item.get("supplier") or None,
            )
        )

    db.bulk_save_objects(rows)


def _set_job_progress(job_id: str, payload: dict[str, Any]) -> None:
    with _progress_lock:
        prev = _job_progress.get(job_id, {})
        prev.update(payload)
        _job_progress[job_id] = prev


def get_job_progress(job_id: str) -> dict[str, Any]:
    with _progress_lock:
        return dict(_job_progress.get(job_id, {}))


def recover_stale_running_jobs() -> int:
    """Переводит зависшие после рестарта сервера job из running в failed."""
    db: Session = SessionLocal()
    try:
        stale_jobs = db.query(ParseJob).filter(ParseJob.status == "running").all()
        if not stale_jobs:
            return 0

        for job in stale_jobs:
            job.status = "failed"
            if not job.error:
                job.error = "Job interrupted: server restarted before completion"

        db.commit()
        return len(stale_jobs)
    finally:
        db.close()


def _run_parser_job(job_id: str, project_root: Path) -> None:
    db: Session = SessionLocal()
    try:
        job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if not job:
            return

        job.status = "running"
        db.commit()
        _set_job_progress(
            job_id,
            {
                "status": "running",
                "progress_percent": 0,
                "products_collected": 0,
                "categories_done": 0,
                "categories_total": 0,
            },
        )

        def on_progress(progress_payload: dict[str, Any] | float) -> None:
            if isinstance(progress_payload, dict):
                percent = progress_payload.get("progress_percent")
                if isinstance(percent, (float, int)):
                    progress_payload["progress_percent"] = int(max(0, min(100, round(float(percent) * 100))))
                _set_job_progress(job_id, progress_payload)
                return

            if isinstance(progress_payload, (float, int)):
                _set_job_progress(
                    job_id,
                    {"progress_percent": int(max(0, min(100, round(float(progress_payload) * 100))))},
                )

        parser = CurlParser(
            cookies_raw=settings.parser_cookies,
            headers_raw=settings.parser_headers,
            progress_callback=on_progress,
            max_category_workers=settings.parser_max_category_workers,
            retry_base_delay_seconds=settings.parser_retry_base_delay_seconds,
            rate_limit_wait_cap_seconds=settings.parser_rate_limit_wait_cap_seconds,
        )

        # Важно: ядро парсера использует файлы из CWD (Cook/categories_config.txt)
        # Поэтому выполняем запуск из корня проекта.
        prev_cwd = os.getcwd()
        try:
            os.chdir(project_root)
            output_file, parsed_items = parser.run(
                selected_categories=job.selected_categories,
                max_products_per_cat=job.max_products,
                return_items=True,
            )
            local_output = project_root / output_file

            _save_job_results(db, job.id, parsed_items)

            if is_object_storage_enabled():
                dt = job.created_at or datetime.utcnow()
                date_prefix = dt.strftime("%Y/%m/%d")
                object_key = f"exports/{date_prefix}/{job.id}/{local_output.name}"
                upload_csv(local_output, object_key)
                job.output_file = object_key
                try:
                    local_output.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                job.output_file = str(local_output)

            job.status = "done"
            job.error = None
            _set_job_progress(job_id, {"status": "done", "progress_percent": 100})
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            _set_job_progress(job_id, {"status": "failed"})
        finally:
            os.chdir(prev_cwd)

        db.commit()
    finally:
        db.close()


def start_job(job_id: str, project_root: Path) -> None:
    # Блокировка от одновременной смены CWD разными тредами.
    def wrapped():
        with _lock:
            _run_parser_job(job_id, project_root)

    thread = threading.Thread(target=wrapped, daemon=True)
    thread.start()
