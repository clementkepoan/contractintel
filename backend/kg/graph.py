from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
from sqlmodel import select

from backend.config import settings
from backend.db.models import Contract, Milestone, Payment, PaymentRequest, ValidationWarning


def graph_path() -> Path:
    return settings.indexes_dir / "graph.json"


def build_graph(session: Any) -> dict[str, Any]:
    graph = nx.DiGraph()
    contracts = session.exec(select(Contract).where(Contract.is_superseded == False)).all()  # noqa: E712
    for contract in contracts:
        graph.add_node(contract.contract_id, type="Contract", name=contract.contract_name, status=contract.validation_status)
        milestones = session.exec(select(Milestone).where(Milestone.contract_id == contract.contract_id)).all()
        for milestone in milestones:
            graph.add_node(milestone.milestone_id, type="Milestone", name=milestone.name, status=milestone.status, amount=milestone.amount)
            graph.add_edge(contract.contract_id, milestone.milestone_id, type="HAS_MILESTONE", order=milestone.source_order)
            for work_item in json.loads(milestone.work_items_json):
                work_item_id = f"{milestone.milestone_id}:work:{abs(hash(work_item))}"
                graph.add_node(work_item_id, type="WorkItem", description=work_item)
                graph.add_edge(milestone.milestone_id, work_item_id, type="HAS_WORKITEM")
            payment_requests = session.exec(select(PaymentRequest).where(PaymentRequest.milestone_id == milestone.milestone_id)).all()
            for request in payment_requests:
                request_id = f"pr_{request.id}"
                graph.add_node(request_id, type="Invoice", amount=request.requested_amount, date=str(request.requested_at))
                graph.add_edge(milestone.milestone_id, request_id, type="TRIGGERS_PAYMENT")
                payments = session.exec(select(Payment).where(Payment.payment_request_id == request.id)).all()
                for payment in payments:
                    payment_id = f"pay_{payment.id}"
                    graph.add_node(payment_id, type="Payment", amount=payment.paid_amount, date=str(payment.paid_at))
                    graph.add_edge(request_id, payment_id, type="SETTLED_BY")
        warnings = session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract.contract_id)).all()
        for warning in warnings:
            clause_id = f"warning_{warning.id}"
            graph.add_node(clause_id, type="Clause", text=warning.message, risk_level=warning.severity.lower())
            graph.add_edge(clause_id, contract.contract_id, type="GOVERNS")
    data = {
        "nodes": [{"id": node, **attrs} for node, attrs in graph.nodes(data=True)],
        "edges": [{"source": src, "target": dst, **attrs} for src, dst, attrs in graph.edges(data=True)],
    }
    graph_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_graph() -> dict[str, Any]:
    path = graph_path()
    if not path.exists():
        return {"nodes": [], "edges": []}
    return json.loads(path.read_text(encoding="utf-8"))


def accepted_not_paid(graph_data: dict[str, Any]) -> list[dict[str, Any]]:
    paid_sources = {edge["source"] for edge in graph_data["edges"] if edge["type"] == "TRIGGERS_PAYMENT"}
    return [node for node in graph_data["nodes"] if node.get("type") == "Milestone" and node.get("status") == "accepted" and node["id"] not in paid_sources]


def high_risk_clauses(graph_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in graph_data["nodes"] if node.get("type") == "Clause" and node.get("risk_level") in {"error", "warning"}]


def payment_trail(graph_data: dict[str, Any], milestone_id: str) -> dict[str, Any]:
    edges = [edge for edge in graph_data["edges"] if edge["source"] == milestone_id]
    related = {milestone_id}
    for edge in edges:
        related.add(edge["target"])
        for next_edge in graph_data["edges"]:
            if next_edge["source"] == edge["target"]:
                related.add(next_edge["target"])
    return {"nodes": [node for node in graph_data["nodes"] if node["id"] in related], "edges": [edge for edge in graph_data["edges"] if edge["source"] in related and edge["target"] in related]}


def render_svg(graph_data: dict[str, Any], focus_contract_id: str | None = None) -> str:
    nodes = graph_data["nodes"]
    edges = graph_data["edges"]
    if focus_contract_id:
        visible_nodes = {focus_contract_id}
        for edge in edges:
            if edge["source"] == focus_contract_id or edge["target"] == focus_contract_id:
                visible_nodes.add(edge["source"])
                visible_nodes.add(edge["target"])
        nodes = [node for node in nodes if node["id"] in visible_nodes]
        edges = [edge for edge in edges if edge["source"] in visible_nodes and edge["target"] in visible_nodes]
    y_positions = {"Contract": 60, "Milestone": 150, "WorkItem": 250, "Invoice": 250, "Payment": 340, "Clause": 340}
    x_step = 180
    placed: dict[str, tuple[int, int]] = {}
    for index, node in enumerate(nodes, start=1):
        placed[node["id"]] = (40 + ((index - 1) % 5) * x_step, y_positions.get(node.get("type", ""), 420 + ((index - 1) // 5) * 70))
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="600" viewBox="0 0 1000 600">', '<rect width="100%" height="100%" fill="#f6f1e8"/>']
    for edge in edges:
        if edge["source"] not in placed or edge["target"] not in placed:
            continue
        x1, y1 = placed[edge["source"]]
        x2, y2 = placed[edge["target"]]
        lines.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#4d5b4f" stroke-width="2" />')
    color_map = {"Contract": "#d08c60", "Milestone": "#6d9f71", "WorkItem": "#d7c9a4", "Invoice": "#7f98b2", "Payment": "#4f6d7a", "Clause": "#b55d4c"}
    for node in nodes:
        x, y = placed[node["id"]]
        fill = color_map.get(node.get("type", ""), "#999")
        label = str(node.get("name") or node.get("description") or node["id"])[:26]
        lines.append(f'<circle cx="{x}" cy="{y}" r="24" fill="{fill}" stroke="#1f2a1f" stroke-width="2" />')
        lines.append(f'<text x="{x}" y="{y + 42}" text-anchor="middle" font-size="12" font-family="Georgia">{label}</text>')
    lines.append("</svg>")
    return "".join(lines)
