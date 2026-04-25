from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["infrastructure"]["local_model_name"]
        assert payload["infrastructure"]["embedding_model_name"]


def test_payment_request_requires_acceptance() -> None:
    with TestClient(app) as client:
        response = client.post("/api/payment-request", json={"milestone_id": "missing", "requested_amount": 100})
        assert response.status_code == 404


def test_ingest_and_full_payment_flow() -> None:
    with TestClient(app) as client:
        sample = Path("Database/02XX專案.docx")
        with sample.open("rb") as handle:
            ingest = client.post("/api/ingest", files={"file": (sample.name, handle, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert ingest.status_code == 200
        contract_id = ingest.json()["contract_id"]

        contract = client.get(f"/api/contracts/{contract_id}")
        assert contract.status_code == 200
        milestone_id = contract.json()["milestones"][0]["milestone_id"]

        blocked = client.post("/api/payment-request", json={"milestone_id": milestone_id, "requested_amount": 1000})
        assert blocked.status_code == 400

        acceptance = client.post("/api/acceptance", json={"milestone_id": milestone_id, "passed": True, "inspector_name": "QA"})
        assert acceptance.status_code == 200
        assert acceptance.json()["status"] == "accepted"

        payment_request = client.post("/api/payment-request", json={"milestone_id": milestone_id, "requested_amount": 1000, "remarks": "milestone request"})
        assert payment_request.status_code == 200
        payment_request_id = payment_request.json()["id"]

        payment = client.post("/api/payment", json={"payment_request_id": payment_request_id, "paid_amount": 1000, "remarks": "paid"})
        assert payment.status_code == 200

        history = client.get(f"/api/workflow/{milestone_id}")
        assert history.status_code == 200
        workflow = history.json()
        assert workflow["acceptance_records"]
        assert any(item["id"] == payment_request_id for item in workflow["payment_requests"])
        assert workflow["payments"]

        financials = client.get(f"/api/contracts/{contract_id}/financials")
        assert financials.status_code == 200
        data = financials.json()
        assert data["payment_requested"] >= 1000
        assert data["paid"] >= 1000


def test_query_endpoint_returns_citations() -> None:
    with TestClient(app) as client:
        sample = Path("Database/02XX專案.docx")
        with sample.open("rb") as handle:
            ingest = client.post("/api/ingest", files={"file": (sample.name, handle, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert ingest.status_code == 200
        contract_id = ingest.json()["contract_id"]

        response = client.post("/api/query", json={"query": "第一期付款條件", "top_k": 3, "contract_id": contract_id})
        assert response.status_code == 200
        payload = response.json()
        assert payload["citations"]
        assert payload["retrieval_mode"] in {"bm25_only", "hybrid_local", "hybrid_qdrant"}
        assert payload["chat_session_id"]


def test_query_endpoint_persists_chat_memory() -> None:
    with TestClient(app) as client:
        sample = Path("Database/02XX專案.docx")
        with sample.open("rb") as handle:
            ingest = client.post("/api/ingest", files={"file": (sample.name, handle, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert ingest.status_code == 200
        contract_id = ingest.json()["contract_id"]

        first = client.post("/api/query", json={"query": "第一期付款條件", "top_k": 2, "contract_id": contract_id})
        assert first.status_code == 200
        chat_session_id = first.json()["chat_session_id"]

        second = client.post(
            "/api/query",
            json={"query": "那第二期呢？", "top_k": 2, "contract_id": contract_id, "chat_session_id": chat_session_id},
        )
        assert second.status_code == 200
        assert second.json()["chat_session_id"] == chat_session_id

        messages = client.get(f"/api/chat/sessions/{chat_session_id}/messages")
        assert messages.status_code == 200
        payload = messages.json()
        assert len(payload) == 4
        assert [item["role"] for item in payload] == ["human", "ai", "human", "ai"]


def test_batch_ingest_endpoint() -> None:
    with TestClient(app) as client:
        sample_one = Path("Database/01XX專案.docx")
        sample_two = Path("Database/02XX專案.docx")
        with sample_one.open("rb") as handle_one, sample_two.open("rb") as handle_two:
            response = client.post(
                "/api/ingest/batch",
                files=[
                    ("files", (sample_one.name, handle_one, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                    ("files", (sample_two.name, handle_two, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                ],
            )
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) == 2
