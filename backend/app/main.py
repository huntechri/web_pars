from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import hash_password
from .config import settings
from .database import Base, SessionLocal, engine
from .models import User
from .routers import auth, categories, parser
from .services.db_migrations import run_sql_migrations
from .services.parser_jobs import recover_stale_running_jobs
from .services.storage import is_object_storage_enabled


app = FastAPI(title="Petrovich Parser API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    run_sql_migrations(engine)
    Base.metadata.create_all(bind=engine)
    recover_stale_running_jobs()

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.admin_username).first()
        if not existing:
            user = User(
                username=settings.admin_username,
                hashed_password=hash_password(settings.admin_password),
            )
            db.add(user)
            db.commit()
    finally:
        db.close()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "storage_enabled": is_object_storage_enabled(),
        "storage_bucket": settings.storage_bucket,
    }


app.include_router(auth.router)
app.include_router(categories.router)
app.include_router(parser.router)
