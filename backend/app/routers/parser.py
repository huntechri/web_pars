from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT
from ..database import get_db
from ..deps import get_current_user
from ..models import ParseJob, User
from ..schemas import ParseJobResponse, StartParseRequest
from ..services.parser_jobs import start_job


router = APIRouter(prefix="/api/parser", tags=["parser"])


@router.post("/run", response_model=ParseJobResponse)
def run_parser(
    payload: StartParseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.selected_categories:
        raise HTTPException(status_code=400, detail="Выберите хотя бы одну категорию")

    job = ParseJob(
        user_id=current_user.id,
        status="queued",
        selected_categories=payload.selected_categories,
        max_products=payload.max_products_per_cat,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    start_job(job.id, PROJECT_ROOT)

    return ParseJobResponse(
        id=job.id,
        status=job.status,
        output_file=job.output_file,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/jobs/{job_id}", response_model=ParseJobResponse)
def get_job(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    return ParseJobResponse(
        id=job.id,
        status=job.status,
        output_file=job.output_file,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/jobs/{job_id}/download")
def download_job_result(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if job.status != "done" or not job.output_file:
        raise HTTPException(status_code=400, detail="Файл пока не готов")

    path = Path(job.output_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл результата не найден")

    return FileResponse(path=str(path), filename=path.name, media_type="text/csv")
