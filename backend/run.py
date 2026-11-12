import asyncio
import logging
import sys
from pathlib import Path
import uvicorn
from app.config import PORT, HOST

logger = logging.getLogger(__name__)


def run_alembic_migrations() -> None:
    """Runs `alembic upgrade head` automatically before Uvicorn boots to prevent schema drift."""
    try:
        from alembic import command
        from alembic.config import Config

        alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
        if alembic_ini.exists():
            cfg = Config(str(alembic_ini))
            command.upgrade(cfg, "head")
    except Exception as e:
        logger.warning(f"Alembic auto-upgrade note: {e}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    run_alembic_migrations()
    print(f"Starting AI Job Application Assistant Backend on http://{HOST}:{PORT}")
    print(f"API Documentation (Swagger): http://localhost:{PORT}/docs")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
