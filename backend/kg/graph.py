from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import networkx as nx
from sqlmodel import select

from backend.config import settings
from backend.db.models import Citation, Contract, Milestone, Payment, PaymentRequest, ValidationWarning
from backend.pipeline.indexer import load_chunk_index


def graph_path() -> Path:
    return settings.indexes_dir / "graph.json"


def stable_work_item_id(milestone_id: str, work_item: str) -> str:
    digest = hashlib.sha256(f"{milestone_id}:{work_item}".encode("utf-8")).hexdigest()[:16]
    return f"work_{digest}"


def citation_signature(citation: Citation | dict[str, Any]) -> tuple[str, str, str, int, int, int]:
    getter = citation.get if isinstance(citation, dict) else lambda key, default=None: getattr(citation, key, default)
    return (
        str(getter("source_file", "") or ""),
        str(getter("field_name", "") or ""),
        str(getter("block_id", "") or ""),
        int(getter("para_start", 0) or 0),
        int(getter("para_end", 0) or 0),
        int(getter("page_estimate", 0) or 0),
    )


def clause_id_for(contract_id: str, signature: tuple[str, str, str, int, int, int], text_snippet: str) -> str:
    raw = json.dumps([contract_id, *signature, text_snippet], ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"clause_{digest}"


def clause_type_from_field_name(field_name: str) -> str:
    if not field_name:
        return "general"
    if "." in field_name:
        return field_name.split(".", 1)[1]
    return field_name


def clause_location(citation: Citation) -> str:
    return f"段落 {citation.para_start}-{citation.para_end}，頁面約 {citation.page_estimate}"


def excerpt_text(value: str | None, limit: int = 280) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def contract_overview_for(contract_id: str) -> tuple[str | None, str | None]:
    payload = load_chunk_index(contract_id)
    if not payload:
        return None, None
    preferred = []
    fallback = []
    for chunk in payload.get("chunks", []):
        if chunk.get("chunk_type") != "structured":
            continue
        kind = chunk.get("structured_kind")
        label = str(chunk.get("clause_label") or "")
        text = str(chunk.get("text") or "")
        body = text.split("\n", 1)[1].strip() if "\n" in text else text.strip()
        body = excerpt_text(body, 360)
        if not body:
            continue
        if kind == "wiki_llm_summary" and label in {"At A Glance", "快速總覽", "契約目的"}:
            preferred.append((body, label))
        elif kind == "wiki_contract_summary" and label in {"At A Glance", "快速總覽", "契約目的"}:
            fallback.append((body, label))
        elif kind in {"wiki_llm_summary", "wiki_contract_summary"}:
            fallback.append((body, label))
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None, None


def annotate_payment_states(graph_data: dict[str, Any]) -> dict[str, Any]:
    nodes_by_id = {node["id"]: node for node in graph_data["nodes"]}
    milestone_to_invoices: dict[str, list[str]] = defaultdict(list)
    invoice_to_payments: dict[str, list[str]] = defaultdict(list)

    for edge in graph_data["edges"]:
        if edge["type"] == "TRIGGERS_PAYMENT":
            milestone_to_invoices[edge["source"]].append(edge["target"])
        elif edge["type"] == "SETTLED_BY":
            invoice_to_payments[edge["source"]].append(edge["target"])

    for node in graph_data["nodes"]:
        if node.get("type") != "Milestone":
            continue

        invoices = milestone_to_invoices.get(node["id"], [])
        payments = [payment_id for invoice_id in invoices for payment_id in invoice_to_payments.get(invoice_id, [])]
        paid_amount = sum(int(nodes_by_id[payment_id].get("amount") or 0) for payment_id in payments if payment_id in nodes_by_id)
        milestone_amount = node.get("amount")

        if not invoices:
            payment_state = "no_invoice"
        elif not payments:
            payment_state = "invoiced_unpaid"
        elif milestone_amount is not None and paid_amount >= int(milestone_amount):
            payment_state = "fully_paid"
        else:
            payment_state = "partially_paid"

        node["payment_state"] = payment_state
        node["invoice_count"] = len(invoices)
        node["payment_count"] = len(payments)
        node["paid_amount"] = paid_amount

    return graph_data


def build_graph(session: Any) -> dict[str, Any]:
    graph = nx.DiGraph()
    contracts = session.exec(select(Contract).where(Contract.is_superseded == False)).all()  # noqa: E712

    for contract in contracts:
        overview, overview_label = contract_overview_for(contract.contract_id)
        graph.add_node(
            contract.contract_id,
            type="Contract",
            name=contract.contract_name,
            status=contract.validation_status,
            contract_id=contract.contract_id,
            source_file=contract.source_file,
            doc_category=contract.doc_category,
            total_amount=contract.total_amount,
            currency=contract.currency,
            overview=overview,
            overview_label=overview_label,
        )

        milestones = session.exec(select(Milestone).where(Milestone.contract_id == contract.contract_id)).all()
        for milestone in milestones:
            graph.add_node(
                milestone.milestone_id,
                type="Milestone",
                name=milestone.name,
                status=milestone.status,
                amount=milestone.amount,
                contract_id=contract.contract_id,
                source_order=milestone.source_order,
            )
            graph.add_edge(contract.contract_id, milestone.milestone_id, type="HAS_MILESTONE", order=milestone.source_order)
            for work_item in json.loads(milestone.work_items_json):
                work_item_id = stable_work_item_id(milestone.milestone_id, work_item)
                graph.add_node(work_item_id, type="WorkItem", description=work_item, contract_id=contract.contract_id, milestone_id=milestone.milestone_id)
                graph.add_edge(milestone.milestone_id, work_item_id, type="HAS_WORKITEM")

            payment_requests = session.exec(select(PaymentRequest).where(PaymentRequest.milestone_id == milestone.milestone_id)).all()
            for request in payment_requests:
                request_id = f"pr_{request.id}"
                graph.add_node(
                    request_id,
                    type="Invoice",
                    amount=request.requested_amount,
                    date=str(request.requested_at),
                    contract_id=contract.contract_id,
                    milestone_id=milestone.milestone_id,
                )
                graph.add_edge(milestone.milestone_id, request_id, type="TRIGGERS_PAYMENT")
                payments = session.exec(select(Payment).where(Payment.payment_request_id == request.id)).all()
                for payment in payments:
                    payment_id = f"pay_{payment.id}"
                    graph.add_node(
                        payment_id,
                        type="Payment",
                        amount=payment.paid_amount,
                        date=str(payment.paid_at),
                        contract_id=contract.contract_id,
                        milestone_id=milestone.milestone_id,
                    )
                    graph.add_edge(request_id, payment_id, type="SETTLED_BY")

        citations = session.exec(select(Citation).where(Citation.contract_id == contract.contract_id)).all()
        citation_groups: dict[tuple[str, str, str, int, int, int], list[Citation]] = defaultdict(list)
        for citation in citations:
            citation_groups[citation_signature(citation)].append(citation)

        clause_ids_by_signature: dict[tuple[str, str, str, int, int, int], str] = {}
        for signature, group in citation_groups.items():
            primary = group[0]
            clause_id = clause_id_for(contract.contract_id, signature, primary.text_snippet)
            clause_ids_by_signature[signature] = clause_id
            graph.add_node(
                clause_id,
                type="Clause",
                text=primary.text_snippet,
                source_file=primary.source_file,
                location=clause_location(primary),
                clause_type=clause_type_from_field_name(primary.field_name),
                field_name=primary.field_name,
                block_id=primary.block_id,
                contract_id=contract.contract_id,
                risk_tags=[],
            )

            milestone_ids = sorted({citation.milestone_id for citation in group if citation.milestone_id})
            if milestone_ids:
                for milestone_id in milestone_ids:
                    graph.add_edge(clause_id, milestone_id, type="SUPPORTS")
            else:
                graph.add_edge(clause_id, contract.contract_id, type="GOVERNS")

        warnings = session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract.contract_id)).all()
        for warning in warnings:
            warning_id = f"warning_{warning.id}"
            graph.add_node(
                warning_id,
                type="ValidationWarning",
                message=warning.message,
                severity=warning.severity.lower(),
                contract_id=contract.contract_id,
            )
            graph.add_edge(warning_id, contract.contract_id, type="ATTACHED_TO")

    data = {
        "nodes": [{"id": node, **attrs} for node, attrs in graph.nodes(data=True)],
        "edges": [{"source": src, "target": dst, **attrs} for src, dst, attrs in graph.edges(data=True)],
    }
    annotate_payment_states(data)
    graph_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_graph() -> dict[str, Any]:
    path = graph_path()
    if not path.exists():
        return {"nodes": [], "edges": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return annotate_payment_states(data)


def accepted_not_paid(graph_data: dict[str, Any]) -> list[dict[str, Any]]:
    annotated = annotate_payment_states(graph_data)
    return [
        node
        for node in annotated["nodes"]
        if node.get("type") == "Milestone"
        and node.get("status") == "accepted"
        and node.get("payment_state") != "fully_paid"
    ]


def high_risk_warnings(graph_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in graph_data["nodes"] if node.get("type") == "ValidationWarning" and node.get("severity") in {"error", "warning"}]


def payment_trail(graph_data: dict[str, Any], milestone_id: str) -> dict[str, Any]:
    edges = [edge for edge in graph_data["edges"] if edge["source"] == milestone_id]
    related = {milestone_id}
    for edge in edges:
        related.add(edge["target"])
        for next_edge in graph_data["edges"]:
            if next_edge["source"] == edge["target"]:
                related.add(next_edge["target"])
    result = {
        "nodes": [node for node in graph_data["nodes"] if node["id"] in related],
        "edges": [edge for edge in graph_data["edges"] if edge["source"] in related and edge["target"] in related],
    }
    return annotate_payment_states(result)


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
    y_positions = {
        "Contract": 60,
        "Milestone": 150,
        "WorkItem": 250,
        "Invoice": 250,
        "Payment": 340,
        "Clause": 340,
        "ValidationWarning": 430,
    }
    x_step = 180
    placed: dict[str, tuple[int, int]] = {}
    for index, node in enumerate(nodes, start=1):
        placed[node["id"]] = (40 + ((index - 1) % 5) * x_step, y_positions.get(node.get("type", ""), 500 + ((index - 1) // 5) * 70))
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="640" viewBox="0 0 1000 640">', '<rect width="100%" height="100%" fill="#f6f1e8"/>']
    for edge in edges:
        if edge["source"] not in placed or edge["target"] not in placed:
            continue
        x1, y1 = placed[edge["source"]]
        x2, y2 = placed[edge["target"]]
        dash = ' stroke-dasharray="6 6"' if edge["type"] in {"GOVERNS", "ATTACHED_TO", "CONFLICTS_WITH"} else ""
        color = "#b91c1c" if edge["type"] == "CONFLICTS_WITH" else "#4d5b4f"
        lines.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2"{dash} />')
    color_map = {
        "Contract": "#d08c60",
        "Milestone": "#6d9f71",
        "WorkItem": "#d7c9a4",
        "Invoice": "#7f98b2",
        "Payment": "#4f6d7a",
        "Clause": "#b55d4c",
        "ValidationWarning": "#dc2626",
    }
    for node in nodes:
        x, y = placed[node["id"]]
        fill = color_map.get(node.get("type", ""), "#999")
        label = str(node.get("name") or node.get("description") or node.get("message") or node["id"])[:26]
        lines.append(f'<circle cx="{x}" cy="{y}" r="24" fill="{fill}" stroke="#1f2a1f" stroke-width="2" />')
        lines.append(f'<text x="{x}" y="{y + 42}" text-anchor="middle" font-size="12" font-family="Georgia">{label}</text>')
    lines.append("</svg>")
    return "".join(lines)
