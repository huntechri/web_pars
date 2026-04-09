from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def run_sql_migrations(engine: Engine) -> None:
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        applied_versions = {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_migrations"))
        }

        for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration_file.name
            if version in applied_versions:
                continue

            sql = migration_file.read_text(encoding="utf-8").strip()
            if sql:
                conn.execute(text(sql))

            conn.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": version},
            )
