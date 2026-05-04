from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from backend.db.database import get_session
from backend.kg.graph import accepted_not_paid, build_graph, high_risk_warnings, load_graph, payment_trail, render_svg

router = APIRouter(prefix="/api/kg", tags=["kg"])


@router.get("/graph")
def graph_data() -> dict:
    with get_session() as session:
        return build_graph(session)


@router.get("/query/accepted-not-paid")
def graph_accepted_not_paid() -> dict:
    return {"items": accepted_not_paid(load_graph())}


@router.get("/query/high-risk-warnings")
def graph_high_risk_warnings() -> dict:
    return {"items": high_risk_warnings(load_graph())}


@router.get("/query/high-risk-clauses")
def graph_high_risk_clauses_compat() -> dict:
    return {"items": high_risk_warnings(load_graph())}


@router.get("/query/payment-trail/{milestone_id}")
def graph_payment_trail(milestone_id: str) -> dict:
    return payment_trail(load_graph(), milestone_id)


@router.get("/svg")
def graph_svg() -> Response:
    return Response(content=render_svg(load_graph()), media_type="image/svg+xml")


@router.get("/svg/{contract_id}")
def graph_contract_svg(contract_id: str) -> Response:
    return Response(content=render_svg(load_graph(), focus_contract_id=contract_id), media_type="image/svg+xml")
