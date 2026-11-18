import os
import tempfile
from pathlib import Path
import pytest

# Isolate all pytest runs from the user's live data/job_assistant.db
_tmp_db_dir = Path(tempfile.gettempdir()) / "talentflow_pytest_db"
_tmp_db_dir.mkdir(parents=True, exist_ok=True)
_tmp_db_file = _tmp_db_dir / f"test_suite_{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db_file.as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def _init_isolated_test_db():
    from app.db.database import init_db, engine

    init_db()
    yield
    try:
        engine.dispose()
    except Exception:
        pass
    try:
        if _tmp_db_file.exists():
            _tmp_db_file.unlink()
    except Exception:
        pass
