import pytest
import storage
from fastapi.testclient import TestClient
from main import app


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect all storage reads/writes to a temporary directory."""
    monkeypatch.setattr(storage, 'DATA_DIR', str(tmp_path))
    return tmp_path


@pytest.fixture()
def client():
    return TestClient(app)
