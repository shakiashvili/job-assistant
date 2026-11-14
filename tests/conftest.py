import os
import sys
import tempfile
from pathlib import Path
import pytest

_project_root = Path(__file__).resolve().parent.parent
_backend_dir = _project_root / "backend"
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# Isolate pytest runs (including non-functional suites) from the live database
if not os.environ.get("DATABASE_URL") or "job_assistant.db" in os.environ.get("DATABASE_URL", ""):
    _tmp_db_dir = Path(tempfile.gettempdir()) / "talentflow_pytest_db"
    _tmp_db_dir.mkdir(parents=True, exist_ok=True)
    _tmp_db_file = _tmp_db_dir / f"test_nf_{os.getpid()}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db_file.as_posix()}"
else:
    _tmp_db_file = None


@pytest.fixture(scope="session", autouse=True)
def _init_isolated_nf_db():
    from app.db.database import init_db, engine

    init_db()
    yield
    try:
        engine.dispose()
    except Exception:
        pass
    try:
        if _tmp_db_file and _tmp_db_file.exists():
            _tmp_db_file.unlink()
    except Exception:
        pass
