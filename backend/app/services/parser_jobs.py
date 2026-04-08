import os
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from parser.full_auto_parser_CURL import CurlParser

from ..database import SessionLocal
from ..models import ParseJob


_lock = threading.Lock()


def _run_parser_job(job_id: str, project_root: Path) -> None:
    db: Session = SessionLocal()
    try:
        job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
        if not job:
            return

        job.status = "running"
        db.commit()

        parser = CurlParser()

        # Важно: ядро парсера использует файлы из CWD (Cook/categories_config.txt)
        # Поэтому выполняем запуск из корня проекта.
        prev_cwd = os.getcwd()
        try:
            os.chdir(project_root)
            output_file = parser.run(
                selected_categories=job.selected_categories,
                max_products_per_cat=job.max_products,
            )
            job.output_file = str(project_root / output_file)
            job.status = "done"
            job.error = None
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
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
