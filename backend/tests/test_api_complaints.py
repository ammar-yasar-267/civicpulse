"""API contract tests for the complaint endpoints (§2.2).

Integration level on purpose: real routes, real middleware, real exception handlers, real
Postgres. The only substitutions are Redis (faked) and the triage provider (pinned to rules),
which are exactly the two external systems whose behaviour we do not want to depend on.
"""

import uuid

from fastapi.testclient import TestClient

from app.domain.enums import Status
from tests.conftest import unique_payload, valid_payload


def test_submit_returns_201_with_triage_fields(client: TestClient) -> None:
    response = client.post("/api/complaints", json=valid_payload())

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["category"] == "water"
    assert body["priority"] == "high"
    assert body["status"] == Status.OPEN.value
    assert body["ai_summary"]
    assert body["triaged_by"] == "rules"
    assert body["triage_latency_ms"] >= 0
    assert body["created_at"] and body["updated_at"]


def test_response_echoes_a_request_id(client: TestClient) -> None:
    """Propagated from the caller so a citizen's report is traceable end to end."""
    supplied = "test-request-id-123"
    response = client.post(
        "/api/complaints", json=valid_payload(), headers={"X-Request-ID": supplied}
    )
    assert response.headers["X-Request-ID"] == supplied


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/api/complaints")
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_validation_errors_are_400_with_field_level_detail(client: TestClient) -> None:
    """The contract says 400 and field-level, not FastAPI's default 422: the form needs to
    know which input to highlight."""
    response = client.post("/api/complaints", json={"text": "short", "location": "x"})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "validation_error"
    offenders = {f["field"] for f in body["fields"]}
    assert "text" in offenders and "location" in offenders


def test_text_over_2000_chars_is_rejected(client: TestClient) -> None:
    response = client.post("/api/complaints", json=valid_payload(text="a" * 2001))
    assert response.status_code == 400
    assert any(f["field"] == "text" for f in response.json()["fields"])


def test_contact_is_optional(client: TestClient) -> None:
    response = client.post("/api/complaints", json=valid_payload(reporter_contact=None))
    assert response.status_code == 201
    assert response.json()["reporter_contact"] is None


def test_get_by_id_round_trips(client: TestClient) -> None:
    created = client.post("/api/complaints", json=valid_payload()).json()

    fetched = client.get(f"/api/complaints/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_unknown_id_is_404(client: TestClient) -> None:
    response = client.get(f"/api/complaints/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_malformed_uuid_is_400(client: TestClient) -> None:
    assert client.get("/api/complaints/not-a-uuid").status_code == 400


def test_list_paginates_and_reports_total(unlimited_client: TestClient) -> None:
    for _ in range(5):
        unlimited_client.post("/api/complaints", json=unique_payload())

    first = unlimited_client.get("/api/complaints", params={"page": 1, "page_size": 2}).json()

    assert first["total"] == 5
    assert len(first["items"]) == 2
    assert first["page"] == 1 and first["page_size"] == 2

    second = unlimited_client.get("/api/complaints", params={"page": 2, "page_size": 2}).json()
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})


def test_page_size_is_capped_at_100(client: TestClient) -> None:
    assert client.get("/api/complaints", params={"page_size": 101}).status_code == 400


def test_list_filters_by_category_priority_and_status(unlimited_client: TestClient) -> None:
    unlimited_client.post("/api/complaints", json=valid_payload())  # water / high
    unlimited_client.post(
        "/api/complaints",
        json=valid_payload(text="Street light bulb is fused in our lane, please replace it."),
    )  # streetlights / low

    water = unlimited_client.get("/api/complaints", params={"category": "water"}).json()
    assert water["total"] == 1
    assert water["items"][0]["category"] == "water"

    low = unlimited_client.get("/api/complaints", params={"priority": "low"}).json()
    assert low["total"] == 1
    assert low["items"][0]["category"] == "streetlights"

    open_only = unlimited_client.get("/api/complaints", params={"status": "open"}).json()
    assert open_only["total"] == 2


def test_invalid_filter_value_is_400(client: TestClient) -> None:
    assert client.get("/api/complaints", params={"category": "plumbing"}).status_code == 400


def test_status_advances_through_the_machine(client: TestClient) -> None:
    created = client.post("/api/complaints", json=valid_payload()).json()
    cid = created["id"]

    in_progress = client.patch(f"/api/complaints/{cid}/status", json={"status": "in_progress"})
    assert in_progress.status_code == 200
    assert in_progress.json()["status"] == "in_progress"

    resolved = client.patch(f"/api/complaints/{cid}/status", json={"status": "resolved"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_invalid_transition_is_409_naming_the_transition(client: TestClient) -> None:
    """The 409 body is surfaced verbatim by the operator UI, so it must be readable and must
    name what was attempted."""
    cid = client.post("/api/complaints", json=valid_payload()).json()["id"]

    response = client.patch(f"/api/complaints/{cid}/status", json={"status": "resolved"})

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "invalid_transition"
    assert "open" in body["detail"] and "resolved" in body["detail"]
    assert body["fields"][0]["field"] == "status"


def test_transition_from_terminal_status_is_409(client: TestClient) -> None:
    cid = client.post("/api/complaints", json=valid_payload()).json()["id"]
    client.patch(f"/api/complaints/{cid}/status", json={"status": "rejected"})

    response = client.patch(f"/api/complaints/{cid}/status", json={"status": "in_progress"})

    assert response.status_code == 409
    assert "terminal" in response.json()["detail"]


def test_status_update_on_unknown_id_is_404(client: TestClient) -> None:
    response = client.patch(
        f"/api/complaints/{uuid.uuid4()}/status", json={"status": "in_progress"}
    )
    assert response.status_code == 404


def test_unknown_status_value_is_400(client: TestClient) -> None:
    cid = client.post("/api/complaints", json=valid_payload()).json()["id"]
    response = client.patch(f"/api/complaints/{cid}/status", json={"status": "archived"})
    assert response.status_code == 400


def test_openapi_schema_is_served(client: TestClient) -> None:
    """The frontend's typed client is generated from this document, so its availability is
    part of the contract (§2.1)."""
    schema = client.get("/openapi.json").json()
    for path in (
        "/api/complaints",
        "/api/complaints/{complaint_id}",
        "/api/complaints/{complaint_id}/status",
        "/api/stats",
        "/api/meta/providers",
        "/health",
        "/ready",
    ):
        assert path in schema["paths"], f"{path} missing from the OpenAPI schema"
