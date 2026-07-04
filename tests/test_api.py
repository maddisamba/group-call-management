"""API tests - verify every status code and exact message format
from the OpenAPI spec, plus the 400 edge cases."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client():
    app = create_app()  # fresh app => fresh in-memory state per test
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- POST /groups/{groupId}/floor -----------------------------------------

async def test_obtain_floor_success_200(client):
    r = await client.post(
        "/groups/group-alpha-123/floor", json={"userId": "user-456"}
    )
    assert r.status_code == 200
    assert r.json() == {
        "message": "Floor obtained by user-456 for group group-alpha-123"
    }


async def test_obtain_floor_conflict_409(client):
    await client.post("/groups/group-alpha-123/floor", json={"userId": "user-789"})
    r = await client.post(
        "/groups/group-alpha-123/floor", json={"userId": "user-456"}
    )
    assert r.status_code == 409
    assert r.json() == {
        "message": "Floor is currently held by user-789 for group group-alpha-123"
    }


async def test_reacquire_by_holder_returns_200(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    r = await client.post("/groups/g1/floor", json={"userId": "user-1"})
    assert r.status_code == 200


async def test_missing_user_id_returns_400(client):
    r = await client.post("/groups/g1/floor", json={})
    assert r.status_code == 400
    assert r.json() == {"message": "Invalid request: userId is required"}


async def test_blank_user_id_returns_400(client):
    for bad in ["", "   "]:
        r = await client.post("/groups/g1/floor", json={"userId": bad})
        assert r.status_code == 400
        assert r.json() == {"message": "Invalid request: userId is required"}


async def test_wrong_type_user_id_returns_400(client):
    r = await client.post("/groups/g1/floor", json={"userId": 123})
    assert r.status_code == 400
    assert r.json() == {"message": "Invalid request: userId is required"}


async def test_malformed_json_returns_400(client):
    r = await client.post(
        "/groups/g1/floor",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


async def test_missing_body_returns_400(client):
    r = await client.post("/groups/g1/floor")
    assert r.status_code == 400


# --- DELETE /groups/{groupId}/floor/{userId} -------------------------------

async def test_release_floor_success_200(client):
    await client.post("/groups/group-alpha-123/floor", json={"userId": "user-456"})
    r = await client.delete("/groups/group-alpha-123/floor/user-456")
    assert r.status_code == 200
    assert r.json() == {
        "message": "Floor released by user-456 for group group-alpha-123"
    }


async def test_release_by_non_holder_403(client):
    await client.post("/groups/group-alpha-123/floor", json={"userId": "user-789"})
    r = await client.delete("/groups/group-alpha-123/floor/user-456")
    assert r.status_code == 403
    assert r.json() == {
        "message": "User user-456 does not hold the floor for group group-alpha-123"
    }
    # floor unchanged: holder can still release
    r2 = await client.delete("/groups/group-alpha-123/floor/user-789")
    assert r2.status_code == 200


async def test_release_when_floor_free_403(client):
    r = await client.delete("/groups/g1/floor/user-1")
    assert r.status_code == 403