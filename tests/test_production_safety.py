import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v1.endpoints import auth_controller, wallet_controller
from config import settings
from dependencies import get_current_user, get_db


async def fake_db():
    yield object()


def production_client(router, prefix: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    return TestClient(app)


def test_production_rejects_manual_wallet_topup(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    async def add_balance(*args, **kwargs):
        return SimpleNamespace(balance=999.0)

    monkeypatch.setattr(wallet_controller.crud_wallet.wallet, "add_balance", add_balance)
    client = production_client(wallet_controller.router, "/api/v1/wallet")

    response = client.post("/api/v1/wallet/topup/simulate", json={"amount": 100})

    assert response.status_code == 404


def test_production_rejects_qrcode_simulation_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    async def simulated(*args, **kwargs):
        return True

    monkeypatch.setattr(auth_controller.auth_service, "simulate_qrcode_scan", simulated)
    monkeypatch.setattr(auth_controller.auth_service, "simulate_qrcode_confirm", simulated)
    client = production_client(auth_controller.router, "/api/v1/auth")

    scan = client.post("/api/v1/auth/qrcode/dev/scan", params={"ticket": "qa-ticket"})
    confirm = client.post("/api/v1/auth/qrcode/dev/confirm", params={"ticket": "qa-ticket"})

    assert scan.status_code == 404
    assert confirm.status_code == 404


def test_production_never_returns_sms_debug_code(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_controller.crud_verification_code, "create_code", no_op)
    monkeypatch.setattr(auth_controller.sms_service, "send_verification_code", no_op)
    client = production_client(auth_controller.router, "/api/v1/auth")

    response = client.post(
        "/api/v1/auth/send-sms",
        json={"phone": "13800138000", "type": "login"},
    )

    assert response.status_code == 200
    assert "debug_code" not in response.json()
