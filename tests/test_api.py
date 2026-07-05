"""API tests - verify every status code and exact message format
from the OpenAPI spec, plus the 400 edge cases."""

import asyncio
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

import app.service
from app.main import create_app


def parse_ts(value: str) -> datetime:
    # Pydantic serializes UTC datetimes in ISO 8601; accept both the
    # "+00:00" and "Z" suffix forms.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
async def client():
    app = create_app()  # fresh app => fresh in-memory state per test
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    # ASGITransport does not run the lifespan, so cancel pending
    # floor-timeout timers explicitly.
    await app.state.floor_service.aclose()


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


async def test_invalid_priority_type_returns_400(client):
    r = await client.post(
        "/groups/g1/floor", json={"userId": "user-1", "priority": "maybe"}
    )
    assert r.status_code == 400


async def test_groups_are_independent(client):
    # A hold on one group must not block other groups, and one user may
    # hold several groups at the same time.
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    r = await client.post("/groups/g2/floor", json={"userId": "user-2"})
    assert r.status_code == 200
    r = await client.post("/groups/g3/floor", json={"userId": "user-1"})
    assert r.status_code == 200
    r = await client.get("/floor/holder/g1")
    assert r.json() == {"message": "Floor Holded by user-1 for group g1"}


# --- Priority requests ------------------------------------------------------

async def test_priority_request_on_free_floor_200(client):
    r = await client.post(
        "/groups/g1/floor", json={"userId": "user-1", "priority": True}
    )
    assert r.status_code == 200
    assert r.json() == {"message": "Floor obtained by user-1 for group g1"}


async def test_priority_preempts_current_holder_200(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    r = await client.post(
        "/groups/g1/floor", json={"userId": "user-2", "priority": True}
    )
    assert r.status_code == 200
    assert r.json() == {"message": "Floor obtained by user-2 for group g1"}


async def test_state_after_preemption(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.post(
        "/groups/g1/floor", json={"userId": "user-2", "priority": True}
    )
    # The preempted user no longer holds the floor...
    r = await client.delete("/groups/g1/floor/user-1")
    assert r.status_code == 403
    # ...their plain re-request conflicts with the new holder...
    r = await client.post("/groups/g1/floor", json={"userId": "user-1"})
    assert r.status_code == 409
    assert r.json() == {
        "message": "Floor is currently held by user-2 for group g1"
    }
    # ...and the holder endpoint reports the preemptor.
    r = await client.get("/floor/holder/g1")
    assert r.json() == {"message": "Floor Holded by user-2 for group g1"}


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


async def test_floor_reusable_after_manual_release(client):
    # Spec: "after release the floor can be taken again by another user."
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.delete("/groups/g1/floor/user-1")
    r = await client.post("/groups/g1/floor", json={"userId": "user-2"})
    assert r.status_code == 200


async def test_double_release_second_returns_403(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    r = await client.delete("/groups/g1/floor/user-1")
    assert r.status_code == 200
    r = await client.delete("/groups/g1/floor/user-1")
    assert r.status_code == 403


# --- GET /floor/holder/{groupId} --------------------------------------------

async def test_holder_endpoint_shows_current_holder(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    r = await client.get("/floor/holder/g1")
    assert r.status_code == 200
    assert r.json() == {"message": "Floor Holded by user-1 for group g1"}


async def test_holder_endpoint_unknown_group_reports_free(client):
    r = await client.get("/floor/holder/never-used")
    assert r.status_code == 200
    assert r.json() == {"message": "No User hold the floor for group never-used"}


async def test_holder_endpoint_free_after_manual_release(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.delete("/groups/g1/floor/user-1")
    r = await client.get("/floor/holder/g1")
    assert r.status_code == 200
    assert r.json() == {"message": "No User hold the floor for group g1"}


# --- Floor timeout ----------------------------------------------------------
# The real timeout is 10s; shrink it so these tests run in milliseconds.

@pytest.fixture
def fast_timeout(monkeypatch):
    monkeypatch.setattr(app.service, "FLOOR_TIMEOUT_SECONDS", 0.15)


async def test_floor_free_for_others_after_timeout(client, fast_timeout):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.3)
    r = await client.post("/groups/g1/floor", json={"userId": "user-2"})
    assert r.status_code == 200
    assert r.json() == {"message": "Floor obtained by user-2 for group g1"}


async def test_release_after_timeout_returns_403(client, fast_timeout):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.3)
    r = await client.delete("/groups/g1/floor/user-1")
    assert r.status_code == 403


async def test_holder_endpoint_shows_free_after_timeout(client, fast_timeout):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.3)
    r = await client.get("/floor/holder/g1")
    assert r.status_code == 200
    assert r.json() == {"message": "No User hold the floor for group g1"}


async def test_auto_release_task_clears_state_without_new_requests(fast_timeout):
    # Verifies the ACTIVE part of the design: the scheduled task physically
    # removes the entry at the deadline, without any API call touching the
    # group afterwards.
    app_instance = create_app()
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/groups/g1/floor", json={"userId": "user-1"})
        assert "g1" in app_instance.state.floor_service.floor_holders
        await asyncio.sleep(0.3)
        assert "g1" not in app_instance.state.floor_service.floor_holders
    await app_instance.state.floor_service.aclose()


# --- GET /audit -------------------------------------------------------------

async def test_audit_empty_returns_empty_list(client):
    r = await client.get("/audit")
    assert r.status_code == 200
    assert r.json() == []


async def test_audit_records_manual_release_and_preemption(client):
    # user-1 obtains and releases g1; user-2 obtains g1 and is then
    # preempted by user-3 with priority.
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.delete("/groups/g1/floor/user-1")
    await client.post("/groups/g1/floor", json={"userId": "user-2"})
    await client.post(
        "/groups/g1/floor", json={"userId": "user-3", "priority": True}
    )

    records = (await client.get("/audit")).json()
    assert len(records) == 3
    first, second, third = records

    assert first["groupId"] == "g1"
    assert first["userId"] == "user-1"
    assert first["priority"] is False
    assert first["obtainedAt"] is not None
    assert first["releasedAt"] is not None  # closed by manual release

    assert second["userId"] == "user-2"
    assert second["releasedAt"] is not None  # closed by preemption

    assert third["userId"] == "user-3"
    assert third["priority"] is True
    assert third["releasedAt"] is None  # still holding


async def test_audit_timeout_closes_record(client, fast_timeout):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.3)

    records = (await client.get("/audit")).json()
    assert len(records) == 1
    assert records[0]["releasedAt"] is not None  # closed by auto-release


async def test_audit_reacquire_does_not_add_record(client):
    # A re-request by the current holder is not a new hold, so it must not
    # append a second audit record.
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    records = (await client.get("/audit")).json()
    assert len(records) == 1


async def test_audit_timestamps_are_consistent(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.post(
        "/groups/g1/floor", json={"userId": "user-2", "priority": True}
    )
    victim, preemptor = (await client.get("/audit")).json()
    # Every record's hold interval is well-ordered, and the preempted
    # holder's record closes no later than the preemptor's opens.
    assert parse_ts(victim["obtainedAt"]) <= parse_ts(victim["releasedAt"])
    assert parse_ts(victim["releasedAt"]) <= parse_ts(preemptor["obtainedAt"])


async def test_audit_timeout_released_at_matches_deadline(client, fast_timeout):
    # A timed-out hold must be closed at its wall-clock deadline
    # (obtainedAt + timeout), not at whatever moment the closer ran.
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.3)
    record = (await client.get("/audit")).json()[0]
    held_for = (
        parse_ts(record["releasedAt"]) - parse_ts(record["obtainedAt"])
    ).total_seconds()
    assert abs(held_for - 0.15) < 0.01


async def test_audit_covers_all_groups_in_obtain_order(client):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await client.post("/groups/g2/floor", json={"userId": "user-2"})
    records = (await client.get("/audit")).json()
    assert [(r["groupId"], r["userId"]) for r in records] == [
        ("g1", "user-1"),
        ("g2", "user-2"),
    ]


# --- Concurrency ------------------------------------------------------------

async def test_concurrent_acquires_grant_exactly_one(client):
    # Fire 10 simultaneous requests for the same group: the per-group lock
    # must serialize them so exactly one wins and the rest get 409.
    responses = await asyncio.gather(
        *(
            client.post("/groups/g1/floor", json={"userId": f"user-{i}"})
            for i in range(10)
        )
    )
    codes = [r.status_code for r in responses]
    assert codes.count(200) == 1
    assert codes.count(409) == 9


# --- OpenAPI spec -----------------------------------------------------------

async def test_openapi_spec_documents_all_endpoints(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for path in [
        "/groups/{groupId}/floor",
        "/groups/{groupId}/floor/{userId}",
        "/floor/holder/{groupId}",
        "/audit",
    ]:
        assert path in paths


async def test_reacquire_does_not_reset_timeout(client, fast_timeout):
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.05)
    # Re-acquire by the holder succeeds but the ORIGINAL 0.15s timer
    # keeps counting down - it is not reset.
    r = await client.post("/groups/g1/floor", json={"userId": "user-1"})
    assert r.status_code == 200
    # 0.2s after the first grant the floor is free, even though the
    # re-acquire happened only 0.15s ago.
    await asyncio.sleep(0.15)
    r = await client.post("/groups/g1/floor", json={"userId": "user-2"})
    assert r.status_code == 200


async def test_priority_rerequest_by_holder_does_not_reset_timeout(
    client, fast_timeout
):
    # The ALREADY_HELD_BY_SELF branch wins over the priority branch: even a
    # priority=true re-request from the current holder keeps the original
    # expiry.
    await client.post("/groups/g1/floor", json={"userId": "user-1"})
    await asyncio.sleep(0.05)
    r = await client.post(
        "/groups/g1/floor", json={"userId": "user-1", "priority": True}
    )
    assert r.status_code == 200
    await asyncio.sleep(0.15)
    r = await client.post("/groups/g1/floor", json={"userId": "user-2"})
    assert r.status_code == 200