from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
import requests
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT
from ..database import get_db
from ..deps import get_current_user
from ..models import ParseJob, ParseResult, User
from ..schemas import ParseJobProgressResponse, ParseJobResponse, ParseJobResultsResponse, ParseResultRowResponse, StartParseRequest
from ..services.parser_jobs import get_job_progress, start_job
from ..services.storage import get_download_url, is_object_storage_enabled


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


@router.get("/jobs", response_model=list[ParseJobResponse])
def list_jobs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    jobs = (
        db.query(ParseJob)
        .filter(ParseJob.user_id == current_user.id)
        .order_by(ParseJob.created_at.desc())
        .limit(100)
        .all()
    )

    return [
        ParseJobResponse(
            id=job.id,
            status=job.status,
            output_file=job.output_file,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        for job in jobs
    ]


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


@router.get("/jobs/{job_id}/results", response_model=ParseJobResultsResponse)
def get_job_results(
    job_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    if offset < 0:
        offset = 0

    job = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    base_query = db.query(ParseResult).filter(ParseResult.job_id == job_id)
    total = base_query.count()
    rows = base_query.order_by(ParseResult.id.asc()).offset(offset).limit(limit).all()

    return ParseJobResultsResponse(
        job_id=job_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[
            ParseResultRowResponse(
                id=row.id,
                article=row.article,
                name=row.name,
                unit=row.unit,
                price=row.price,
                brand=row.brand,
                weight=row.weight,
                level1=row.level1,
                level2=row.level2,
                level3=row.level3,
                level4=row.level4,
                image=row.image,
                url=row.url,
                supplier=row.supplier,
            )
            for row in rows
        ],
    )


@router.get("/jobs/{job_id}/progress", response_model=ParseJobProgressResponse)
def get_job_parse_progress(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    progress = get_job_progress(job_id)
    return ParseJobProgressResponse(
        status=progress.get("status", job.status),
        progress_percent=int(progress.get("progress_percent", 0) or 0),
        products_collected=int(progress.get("products_collected", 0) or 0),
        categories_done=int(progress.get("categories_done", 0) or 0),
        categories_total=int(progress.get("categories_total", 0) or 0),
    )


@router.get("/jobs/{job_id}/download")
def download_job_result(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.query(ParseJob).filter(ParseJob.id == job_id, ParseJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if job.status != "done" or not job.output_file:
        raise HTTPException(status_code=400, detail="Файл пока не готов")

    path = Path(job.output_file)
    if path.exists():
        return FileResponse(path=str(path), filename=path.name, media_type="text/csv")

    if is_object_storage_enabled():
        try:
            url = get_download_url(job.output_file)
            response = requests.get(url, stream=True, timeout=120)
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Ошибка скачивания файла из object storage")

            filename = Path(job.output_file).name or f"{job_id}.csv"

            def iter_chunks():
                try:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            yield chunk
                finally:
                    response.close()

            return StreamingResponse(
                iter_chunks(),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Не удалось подготовить ссылку на скачивание")

    raise HTTPException(status_code=404, detail="Файл результата не найден")
