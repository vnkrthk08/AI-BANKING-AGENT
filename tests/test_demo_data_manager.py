"""Tests for Presentation Demo Data Manager service and endpoints."""

import pytest
from starlette.testclient import TestClient

from app.main import app
from kural.persistence.database import Database
from kural.security.token_service import create_access_token
from kural.services.demo_data_manager import (
    get_demo_fixtures_status,
    reset_presentation_fixtures,
    seed_presentation_fixtures,
)


def test_demo_data_service_lifecycle(tmp_path):
    """Verify seeding and resetting presentation demo fixtures directly via service."""
    db_file = tmp_path / "test_demo.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()

    # Initial status
    status0 = get_demo_fixtures_status(db)
    assert not status0["is_loaded"]

    # Seed
    counts = seed_presentation_fixtures(db)
    assert counts["customers"] == 10
    assert counts["campaigns"] == 3
    assert counts["calls"] == 6
    assert counts["cases"] == 4
    assert counts["callbacks"] == 3

    # Status after seed
    status1 = get_demo_fixtures_status(db)
    assert status1["is_loaded"]
    assert status1["customers_count"] == 10
    assert status1["campaigns_count"] == 3
    assert status1["calls_count"] == 6

    # Reset
    reset_res = reset_presentation_fixtures(db)
    assert reset_res["status"] == "CLEAN"

    # Status after reset
    status2 = get_demo_fixtures_status(db)
    assert not status2["is_loaded"]
    assert status2["customers_count"] == 0
    assert status2["campaigns_count"] == 0


def test_demo_data_api_endpoints():
    """Verify auth endpoints for demo data with super admin permissions."""
    client = TestClient(app)
    admin_token = create_access_token("admin-user-id", "admin", "SUPER_ADMIN", "Executive Platform Office", 1)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Status
    res_status = client.get("/api/v1/auth/demo-data/status", headers=headers)
    assert res_status.status_code == 200
    assert "is_loaded" in res_status.json()

    # 2. Seed
    res_seed = client.post("/api/v1/auth/demo-data/seed", json={}, headers=headers)
    assert res_seed.status_code == 200
    assert res_seed.json()["status"] == "SEEDED"

    # 3. Reset
    res_reset = client.post("/api/v1/auth/demo-data/reset", json={}, headers=headers)
    assert res_reset.status_code == 200
    assert res_reset.json()["status"] == "CLEAN"

    # 4. Seed again so local db has active demo data
    res_seed2 = client.post("/api/v1/auth/demo-data/seed", json={}, headers=headers)
    assert res_seed2.status_code == 200
