from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from sqlmodel import select

from backend.config import settings
from backend.db.models import Contract, FiledQuery, IngestEvent, Milestone, ValidationWarning
from backend.pipeline.llm import llm_available, query_local_llm_detailed


def slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "contract"


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    lines = content.splitlines()
    metadata: dict[str, Any] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line == "---":
            return metadata, "\n".join(lines[index + 1 :]).lstrip("\n")
        if ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            metadata[key] = raw_value
            index += 1
            continue
        index += 1
        items: list[str] = []
        while index < len(lines) and lines[index].startswith("  - "):
            items.append(lines[index][4:].strip())
            index += 1
        metadata[key] = items
    return metadata, content


def build_frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def wiki_relative(path: Path) -> str:
    return path.relative_to(settings.wiki_dir).as_posix()


def markdown_link(from_path: Path, to_path: Path, label: str) -> str:
    return f"[{label}]({Path(os.path.relpath(to_path, from_path.parent)).as_posix()})"


def contract_page_path(contract_key: str) -> Path:
    return settings.wiki_dir / "contracts" / f"{contract_key}.md"


def contract_version_page_path(contract_key: str, version_number: int) -> Path:
    return settings.wiki_dir / "contract_versions" / f"{contract_key}__v{version_number}.md"


def source_page_path(contract: Contract) -> Path:
    return settings.wiki_dir / "sources" / f"{contract.contract_key}__v{contract.version_number}.md"


def milestone_page_path(contract_key: str, milestone_key: str) -> Path:
    return settings.wiki_dir / "milestones" / f"{contract_key}__{milestone_key}.md"


def milestone_version_page_path(contract_key: str, milestone_key: str, version_number: int) -> Path:
    return settings.wiki_dir / "milestone_versions" / f"{contract_key}__{milestone_key}__v{version_number}.md"


def query_page_path(query_id: str) -> Path:
    return settings.wiki_dir / "queries" / f"{query_id}.md"


def now_label() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def ensure_generated_dirs() -> None:
    for name in ["contracts", "contract_versions", "sources", "milestones", "milestone_versions", "queries"]:
        (settings.wiki_dir / name).mkdir(parents=True, exist_ok=True)


def reset_generated_dir(name: str) -> None:
    target = settings.wiki_dir / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def load_raw_payload(contract: Contract) -> dict[str, Any]:
    path = Path(contract.raw_json_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_raw_milestone(contract: Contract, milestone: Milestone) -> dict[str, Any] | None:
    payload = load_raw_payload(contract)
    milestones = payload.get("milestones", [])
    for item in milestones:
        if item.get("milestone_key") == milestone.milestone_key:
            return item
    for item in milestones:
        if item.get("source_order") == milestone.source_order:
            return item
    return None


def load_validation_rows(session: Any, contract_id: str) -> list[ValidationWarning]:
    return session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract_id)).all()


def load_milestone_rows(session: Any, contract_id: str) -> list[Milestone]:
    return session.exec(select(Milestone).where(Milestone.contract_id == contract_id).order_by(Milestone.source_order)).all()


def format_money(value: int | None, currency: str) -> str:
    return f"{value:,} {currency}" if value is not None else f"N/A {currency}"


def unique_lines(items: list[str | None], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item:
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def format_percentage(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value)}%"
    return f"{value}%"


def sentence_trim(value: str | None, limit: int = 160) -> str:
    if not value:
        return ""
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit].rstrip() if len(cleaned) > limit else cleaned


def normalize_warning_message(value: str) -> str:
    return sentence_trim(value.replace("Milestone ", "").replace("contract total", "total"))


def strip_clause_prefix(value: str | None) -> str:
    if not value:
        return ""
    cleaned = " ".join(value.strip().split())
    prefixes = (
        "一、",
        "二、",
        "三、",
        "四、",
        "五、",
        "六、",
        "七、",
        "八、",
        "九、",
        "十、",
        "第十二條",
        "第十一條",
        "第十條",
        "第九條",
        "第八條",
        "第七條",
        "第六條",
        "第五條",
        "第四條",
        "第三條",
        "第二條",
        "第一條",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned


def first_meaningful_sentence(value: str | None, limit: int = 120) -> str:
    cleaned = strip_clause_prefix(value)
    if not cleaned:
        return ""
    for splitter in ("。", "；", "\n"):
        if splitter in cleaned:
            cleaned = cleaned.split(splitter, 1)[0]
            break
    return sentence_trim(cleaned, limit)


def looks_like_summary_noise(value: str) -> bool:
    markers = (
        "營業稅",
        "關稅",
        "貨物稅",
        "規費",
        "甲方應給付",
        "本契約總價",
        "工程總價",
        "懲罰性違約金",
        "本契約係以新臺幣報價",
        "甲方得暫停付款",
    )
    return any(marker in value for marker in markers)


def looks_like_objective_noise(value: str) -> bool:
    markers = (
        "營業稅",
        "關稅",
        "保固保證金",
        "履約保證金",
        "不得要求加價",
        "請求追加工程款",
        "甲方應給付",
        "本契約總價",
        "工程總價",
        "智慧財產權",
        "著作權",
    )
    return any(marker in value for marker in markers)


def looks_like_heading(value: str) -> bool:
    return (value.startswith("第") and len(value) <= 24) or bool(re.match(r"^第.+條$", value))


def looks_like_acceptance_note(value: str) -> bool:
    markers = ("驗收", "複驗", "測試", "核定", "確認", "交付", "完工")
    return any(marker in value for marker in markers)


def looks_like_payment_note(value: str) -> bool:
    markers = ("請款", "發票", "付款", "匯款", "工作天", "收到", "給付")
    return any(marker in value for marker in markers)


def looks_like_warranty_or_security(value: str) -> bool:
    markers = ("保固", "履約保證金", "保固保證金", "瑕疵", "修繕")
    return any(marker in value for marker in markers)


def is_placeholder_clause(value: str | None) -> bool:
    if not value:
        return False
    cleaned = " ".join(value.split())
    return any(
        pattern in cleaned
        for pattern in (
            "契約總額 %",
            "契約總額 ％",
            "PO） 日內",
            "PO) 日內",
        )
    ) or bool(re.search(r"契約總額\s*%之", cleaned)) or bool(re.search(r"PO[）)]\s*日內", cleaned))


def looks_like_ip_clause(value: str | None) -> bool:
    if not value:
        return False
    return any(marker in value for marker in ("智慧財產權", "著作權", "商標權", "軟體", "侵害他人"))


def looks_like_change_order_clause(value: str | None) -> bool:
    if not value:
        return False
    return any(marker in value for marker in ("甲方變更行為", "廢棄已完成工程", "追加工程款", "變更計劃", "增減帳"))


def citation_display_label(field_name: str) -> str:
    return {
        "milestone.name": "Milestone Name Evidence",
        "milestone.amount": "Amount Evidence",
        "milestone.percentage": "Percentage Evidence",
        "milestone.payment_condition": "Payment Condition Evidence",
        "milestone.acceptance_criteria": "Acceptance Criteria Evidence",
        "milestone.work_items": "Work Item Evidence",
    }.get(field_name, field_name)


def normalize_citation_snippet(value: str | None) -> str:
    if not value:
        return ""
    cleaned = " ".join(value.split()).rstrip("。．.;；")
    return cleaned


def collect_filtered_lines(
    items: list[str | None],
    *,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    limit: int = 4,
    sentence_limit: int = 140,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = first_meaningful_sentence(item, sentence_limit)
        if not cleaned or cleaned in seen:
            continue
        if include and not any(marker in cleaned for marker in include):
            continue
        if exclude and any(marker in cleaned for marker in exclude):
            continue
        if is_placeholder_clause(cleaned):
            continue
        if looks_like_ip_clause(cleaned):
            continue
        if cleaned in {"驗收、保固期間及危險負擔", "軟體保固規範"}:
            continue
        if looks_like_heading(cleaned):
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def summarize_intro_preview(raw_text_preview: str | None, contract_name: str) -> list[str]:
    preview = " ".join((raw_text_preview or "").split())
    if not preview:
        return []
    candidates: list[str] = []
    if "茲因" in preview:
        cleaned = preview.split("茲因", 1)[1]
        for stopper in ("約定條款如下", "第一條", "第二條", "第三條"):
            if stopper in cleaned:
                cleaned = cleaned.split(stopper, 1)[0]
                break
        cleaned = sentence_trim("茲因" + cleaned, 140)
        if cleaned:
            candidates.append(cleaned)
    range_match = re.search(r"工程範圍[：: ]?(.*?)(?:第五條|第四條|第三條|付款|驗收|保固|$)", preview)
    if range_match:
        cleaned = sentence_trim(range_match.group(1), 140)
        if cleaned:
            candidates.append(cleaned)
    for sentence in preview.split("。"):
        cleaned = sentence_trim(sentence, 140)
        if not cleaned:
            continue
        if contract_name and contract_name in cleaned and ("委託" in cleaned or "承攬" in cleaned or "工程" in cleaned):
            candidates.append(cleaned)
        elif "工程範圍" in cleaned or "系統整合" in cleaned or "業務需要" in cleaned:
            candidates.append(cleaned)
        if len(candidates) >= 3:
            break
    return unique_lines(candidates, limit=2)


def build_milestone_progress_sentence(milestones: list[dict[str, Any]]) -> str:
    names = [normalize_summary_fragment(item.get("name", ""), 36) for item in milestones[:4] if item.get("name")]
    names = [name for name in names if name]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return " → ".join(names)


def normalize_summary_fragment(value: str | None, limit: int = 100) -> str:
    cleaned = first_meaningful_sentence(value, limit)
    if not cleaned:
        return ""
    if "：" in cleaned:
        head, tail = cleaned.split("：", 1)
        if len(head) <= 30 and tail.strip():
            cleaned = tail.strip()
    cleaned = cleaned.lstrip("於")
    return sentence_trim(cleaned, limit)


def humanize_contract_purpose(facts: dict[str, Any], intro_notes: list[str]) -> str:
    source_file = facts.get("source_file", "source")
    contract_name = facts.get("contract_name", "this contract")
    intro = intro_notes[0] if intro_notes else ""
    if "機電工程" in intro and "系統整合" in intro:
        return f"`{source_file}` is an engineering contract for `{contract_name}` covering system integration / access-control work within the project MEP scope."
    if "機電工程" in intro:
        return f"`{source_file}` is an engineering contract for `{contract_name}` within the project MEP scope."
    if "委託" in intro and "承攬" in intro:
        return f"`{source_file}` records that the project owner side commissions the contractor to undertake `{contract_name}`."
    if facts.get("doc_category") == "rfp":
        return f"`{source_file}` is an RFP / pre-award source describing `{contract_name}`."
    return f"`{source_file}` is the active `{facts.get('doc_category', 'contract')}` source for `{contract_name}`."


def derive_scope_context(facts: dict[str, Any], filtered_scope: list[str], intro_notes: list[str]) -> str:
    for item in filtered_scope:
        normalized = normalize_summary_fragment(item, 120)
        if not normalized:
            continue
        if looks_like_objective_noise(normalized):
            continue
        if any(marker in normalized for marker in ("驗收", "複驗", "逾期", "保固", "給付", "付款")):
            continue
        if looks_like_ip_clause(normalized) or looks_like_change_order_clause(normalized):
            continue
        return normalized
    return ""


def build_contract_summary_facts(
    contract: Contract,
    milestones: list[Milestone],
    raw_payload: dict[str, Any],
    warnings: list[ValidationWarning],
    conflicts: list[str],
) -> dict[str, Any]:
    milestone_facts: list[dict[str, Any]] = []
    for milestone in milestones[:6]:
        raw_milestone = resolve_raw_milestone(contract, milestone) or {}
        milestone_facts.append(
            {
                "order": milestone.source_order,
                "name": milestone.name,
                "amount": raw_milestone.get("amount", milestone.amount),
                "percentage": raw_milestone.get("percentage", milestone.percentage),
                "status": milestone.status,
                "payment_condition": sentence_trim(raw_milestone.get("payment_condition", milestone.payment_condition or ""), 140),
                "acceptance_criteria": sentence_trim(raw_milestone.get("acceptance_criteria", milestone.acceptance_criteria or ""), 140),
                "work_items": unique_lines(raw_milestone.get("work_items") or json.loads(milestone.work_items_json), limit=3),
            }
        )
    return {
        "contract_name": contract.contract_name,
        "source_file": contract.source_file,
        "doc_category": contract.doc_category,
        "contract_type": contract.contract_type,
        "currency": contract.currency,
        "total_amount": contract.total_amount,
        "payment_type": raw_payload.get("payment_type") or ("installment" if len(milestones) >= 2 else None),
        "retention": raw_payload.get("retention"),
        "raw_text_preview": raw_payload.get("raw_text_preview", ""),
        "milestones": milestone_facts,
        "scope_items": unique_lines(raw_payload.get("scope_items", []), limit=4),
        "acceptance_requirements": unique_lines(raw_payload.get("acceptance_requirements", []), limit=4),
        "safety_requirements": unique_lines(raw_payload.get("safety_requirements", []), limit=3),
        "warranty_requirements": unique_lines(raw_payload.get("warranty_requirements", []), limit=3),
        "progress_checkpoints": unique_lines([item.get("name", "") for item in raw_payload.get("progress_checkpoints", [])], limit=4),
        "warnings": unique_lines([normalize_warning_message(item.message) for item in warnings], limit=5),
        "conflicts": unique_lines(conflicts, limit=5),
    }


def render_contract_summary(facts: dict[str, Any]) -> list[str]:
    milestone_lines = []
    for item in facts["milestones"]:
        line = f"- {item['order']}. {item['name']} | {format_money(item['amount'], facts['currency'])} | {format_percentage(item['percentage'])} | `{item['status']}`"
        milestone_lines.append(line)
    if not milestone_lines:
        milestone_lines = ["- No milestone schedule was extracted."]

    intro_notes = summarize_intro_preview(facts.get("raw_text_preview"), facts["contract_name"])
    filtered_scope = collect_filtered_lines(
        facts["scope_items"],
        exclude=("甲方應給付", "本契約總價", "工程總價", "營業稅", "保證金", "智慧財產權", "著作權"),
        limit=3,
        sentence_limit=150,
    )
    objective_lines: list[str] = []
    for item in [*intro_notes, *filtered_scope]:
        if looks_like_objective_noise(item):
            continue
        cleaned = sentence_trim(item, 150)
        if cleaned and cleaned not in objective_lines:
            objective_lines.append(cleaned)
        if len(objective_lines) >= 2:
            break

    overview_lines = []
    overview_lines = [f"- Contract purpose: {humanize_contract_purpose(facts, intro_notes)}"]
    scope_context = derive_scope_context(facts, filtered_scope, intro_notes)
    if scope_context:
        overview_lines.append(f"- Scope context: {scope_context}")
    overview_lines.extend(
        [
            f"- Commercial structure: `{facts['contract_type']}` / payment mode `{facts['payment_type'] or 'unknown'}` / current value {format_money(facts['total_amount'], facts['currency'])}.",
            f"- Active milestone count: {len(facts['milestones'])}.",
        ]
    )
    progress_sentence = build_milestone_progress_sentence(facts["milestones"])
    if progress_sentence:
        overview_lines.append(f"- Milestone progression: {progress_sentence}.")
    if facts["progress_checkpoints"]:
        overview_lines.append(f"- Progress checkpoints mentioned: {', '.join(facts['progress_checkpoints'])}.")

    delivery_notes: list[str] = []
    for milestone in facts["milestones"][:4]:
        work_items = [normalize_summary_fragment(item, 80) for item in milestone["work_items"][:2]]
        work_items = [item for item in work_items if item]
        acceptance = normalize_summary_fragment(milestone["acceptance_criteria"], 100)
        if work_items:
            line = f"- {milestone['name']}: 主要交付為 {'；'.join(work_items)}"
            if acceptance:
                line += f"；驗收重點為 {acceptance}"
            delivery_notes.append(line)
        elif acceptance:
            delivery_notes.append(f"- {milestone['name']}: 驗收重點為 {acceptance}")

    acceptance_notes = collect_filtered_lines(
        facts["acceptance_requirements"],
        include=("驗收", "複驗", "測試", "交付", "核定", "確認"),
        exclude=("營業稅", "關稅", "貨物稅", "規費", "本契約總價", "契約總價", "工程總價", "智慧財產權", "著作權"),
        limit=3,
        sentence_limit=130,
    )
    for item in acceptance_notes:
        if len(delivery_notes) >= 5:
            break
        if looks_like_change_order_clause(item):
            continue
        delivery_notes.append(f"- Contract-level acceptance note: {normalize_summary_fragment(item, 130)}")
    if not delivery_notes:
        delivery_notes = ["- No structured delivery or acceptance notes were extracted."]

    payment_notes: list[str] = []
    for milestone in facts["milestones"][:4]:
        payment = first_meaningful_sentence(milestone["payment_condition"], 140)
        if payment:
            payment_notes.append(f"- {milestone['name']}: {payment}")

    global_payment_candidates = [
        *facts["acceptance_requirements"],
        *facts["scope_items"],
        *facts["safety_requirements"],
        *facts["warranty_requirements"],
    ]
    global_payment_notes = collect_filtered_lines(
        global_payment_candidates,
        include=("請款", "發票", "付款", "匯款", "工作天", "收到"),
        exclude=("甲方應給付本契約總價", "甲方應給付工程總價", "即 ", "20%", "30%", "40%", "50%", "智慧財產權", "著作權"),
        limit=2,
        sentence_limit=140,
    )
    for item in global_payment_notes:
        if item not in payment_notes and not is_placeholder_clause(item):
            payment_notes.append(f"- Global procedure: {normalize_summary_fragment(item, 140)}")
    if facts["retention"]:
        payment_notes.append(
            f"- Retention: {format_money(facts['retention'].get('amount'), facts['currency'])} / {format_percentage(facts['retention'].get('percentage'))}."
        )
    if not payment_notes:
        payment_notes = ["- No structured payment conditions were extracted."]

    risk_notes: list[str] = []
    for item in facts["warnings"][:4]:
        risk_notes.append(f"- {item}")
    for item in facts["conflicts"][:2]:
        risk_notes.append(f"- Version note: {sentence_trim(item)}")
    warranty_notes = collect_filtered_lines(
        facts["warranty_requirements"],
        include=("保固", "履約保證金", "保固保證金", "瑕疵", "修繕"),
        exclude=("營業稅", "關稅", "貨物稅", "規費", "智慧財產權", "著作權"),
        limit=2,
        sentence_limit=140,
    )
    for item in warranty_notes:
        if is_placeholder_clause(item):
            continue
        risk_notes.append(f"- Warranty / security: {item}")
    if not risk_notes:
        safety_notes = collect_filtered_lines(
            facts["safety_requirements"],
            include=("安全", "危及", "改善", "重做", "賠償"),
            exclude=("營業稅", "關稅", "貨物稅", "規費"),
            limit=2,
            sentence_limit=140,
        )
        for item in safety_notes:
            risk_notes.append(f"- Execution risk: {item}")
    if not risk_notes:
        risk_notes = ["- No active validation warnings or version conflicts are open."]

    return [
        "## Contract Summary",
        "### At A Glance",
        *overview_lines,
        "",
        "### Milestone And Payment Structure",
        *milestone_lines,
        "",
        "### Delivery And Acceptance",
        *delivery_notes,
        "",
        "### Payment Procedures And Commercial Notes",
        *payment_notes,
        "",
        "### Risks And Open Issues",
        *risk_notes,
    ]


def build_llm_summary_prompt(facts: dict[str, Any]) -> str:
    milestone_lines = [
        f"{item['order']}. {item['name']} | 金額={item['amount']} | 比例={item['percentage']} | 付款={item['payment_condition'] or 'N/A'} | 驗收={item['acceptance_criteria'] or 'N/A'} | 工作={'; '.join(item['work_items']) or 'N/A'}"
        for item in facts["milestones"][:6]
    ]
    note_lines = []
    for label, key in (
        ("範圍", "scope_items"),
        ("驗收", "acceptance_requirements"),
        ("安全", "safety_requirements"),
        ("保固", "warranty_requirements"),
    ):
        for item in facts[key][:3]:
            cleaned = sentence_trim(item, 120)
            if not cleaned or is_placeholder_clause(cleaned) or looks_like_ip_clause(cleaned):
                continue
            if label == "驗收" and looks_like_change_order_clause(cleaned):
                continue
            note_lines.append(f"{label}: {cleaned}")
    warning_lines = [sentence_trim(item, 120) for item in facts["warnings"][:4]]
    prompt = "\n".join(
        [
            "你是離線契約摘要器。只根據提供事實，用繁體中文輸出 Markdown。不要捏造。",
            "目標：讓讀者快速理解這份契約在做什麼、怎麼付款、怎麼驗收、有哪些風險。",
            "格式固定：",
            "### 契約目的",
            "- 2點內",
            "### 商務與付款",
            "- 4點內",
            "### 交付與驗收",
            "- 4點內",
            "### 風險與注意事項",
            "- 4點內",
            "整體保持精簡，避免重複，不要輸出程式碼區塊。",
            "",
            f"契約名稱: {facts['contract_name']}",
            f"來源檔案: {facts['source_file']}",
            f"文件類型: {facts['doc_category']}",
            f"契約型態: {facts['contract_type']}",
            f"總金額: {facts['total_amount']} {facts['currency']}",
            f"付款模式: {facts['payment_type'] or 'unknown'}",
            "里程碑:",
            *milestone_lines,
            "補充事實:",
            *(note_lines or ["無"]),
            "警示:",
            *(warning_lines or ["無"]),
        ]
    )
    return prompt[:6000]


def render_llm_contract_summary(facts: dict[str, Any]) -> list[str]:
    if not llm_available():
        return ["## LLM Summary", "- Local LLM unavailable; no comparative LLM summary was generated."]
    prompt = build_llm_summary_prompt(facts)
    response = query_local_llm_detailed(prompt, timeout=180.0)
    content = (response.get("response") or "").strip()
    if not content:
        return [f"## LLM Summary", f"- LLM summary generation failed: `{response.get('error') or 'empty_response'}`."]
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if not lines:
        return ["## LLM Summary", "- LLM returned an empty summary."]
    if lines[0] != "## LLM Summary":
        lines = ["## LLM Summary", *lines]
    return lines


def summarize_page(content: str) -> str:
    _, body = parse_frontmatter(content)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(">") or stripped.startswith("|"):
            continue
        return stripped[2:162] if stripped.startswith("- ") else stripped[:160]
    return ""


def related_source_paths(contracts: list[Contract]) -> list[str]:
    return [wiki_relative(source_page_path(contract)) for contract in contracts]


def maintain_with_local_llm(path: Path, generated: str, label: str) -> str:
    if not path.exists() or not llm_available():
        return generated
    existing = path.read_text(encoding="utf-8")
    if existing.strip() == generated.strip():
        return generated
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You maintain an offline contract wiki. Revise the existing markdown page using the new generated facts. "
                "Preserve YAML frontmatter, markdown links, citations, and tables. Do not invent facts. "
                "Flag contradictions explicitly instead of deleting them.",
            ),
            ("human", "Page: {label}\n\nExisting page:\n{existing}\n\nNew generated page:\n{generated}"),
        ]
    )
    chain = prompt | ChatOllama(model=settings.local_model_name, base_url=settings.local_model_base_url, temperature=0, num_ctx=settings.local_model_num_ctx) | StrOutputParser()
    try:
        revised = chain.invoke({"label": label, "existing": existing[:12000], "generated": generated[:12000]})
    except Exception:
        return generated
    return revised if revised.strip().startswith("---") else generated


def generate_contract_page(contract_key: str, contracts: list[Contract], session: Any, *, snapshot: bool = False) -> str:
    active_contract = next((item for item in contracts if not item.is_superseded), contracts[0])
    target_path = contract_version_page_path(contract_key, active_contract.version_number) if snapshot else contract_page_path(contract_key)
    active_milestones = load_milestone_rows(session, active_contract.contract_id)
    related = related_source_paths(contracts)
    related.append(wiki_relative(contract_version_page_path(contract_key, active_contract.version_number)))
    source_rows = []
    conflict_lines: list[str] = []
    warning_lines: list[str] = []
    active_warnings = load_validation_rows(session, active_contract.contract_id)
    active_raw_payload = load_raw_payload(active_contract)

    for contract in sorted(contracts, key=lambda item: item.version_number, reverse=True):
        source_path = source_page_path(contract)
        source_rows.append(
            f"| {contract.source_file} | v{contract.version_number} | {contract.doc_category} | {'active' if not contract.is_superseded else 'superseded'} | "
            f"{markdown_link(target_path, source_path, contract.contract_id)} |"
        )
        raw_payload = load_raw_payload(contract)
        for conflict in raw_payload.get("version_conflicts", []):
            conflict_lines.append(f"- v{contract.version_number} `{conflict['field']}` changed from `{conflict['old']}` to `{conflict['new']}`.")
        for warning in load_validation_rows(session, contract.contract_id):
            warning_lines.append(f"- v{contract.version_number} [{warning.severity}] {warning.message}")

    milestone_rows = []
    for milestone in active_milestones:
        raw_milestone = resolve_raw_milestone(active_contract, milestone) or {}
        milestone_path = milestone_page_path(contract_key, milestone.milestone_key)
        related.append(wiki_relative(milestone_path))
        milestone_rows.append(
            f"| {milestone.source_order} | {markdown_link(target_path, milestone_path, milestone.name)} | "
            f"{format_money(raw_milestone.get('amount', milestone.amount), active_contract.currency)} | "
            f"{raw_milestone.get('percentage', milestone.percentage) or 'N/A'} | {milestone.status} |"
        )

    metadata = build_frontmatter(
        {
            "kind": "contract_version" if snapshot else "contract",
            "title": active_contract.contract_name,
            "contract_key": contract_key,
            "contract_id": active_contract.contract_id,
            "version_number": active_contract.version_number,
            "updated_at": now_label(),
            "related": sorted(set(related)),
            "tags": ["contract", active_contract.doc_category, f"v{active_contract.version_number}"],
        }
    )
    summary_facts = build_contract_summary_facts(
        active_contract,
        active_milestones,
        active_raw_payload,
        active_warnings,
        unique_lines(conflict_lines),
    )
    deterministic_summary = render_contract_summary(summary_facts)
    llm_summary = render_llm_contract_summary(summary_facts)
    return "\n".join(
        [
            metadata,
            "",
            f"# {active_contract.contract_name}",
            "",
            "## Snapshot",
            f"- Contract key: `{contract_key}`",
            f"- Current version: `v{active_contract.version_number}`",
            f"- Source documents tracked: {len(contracts)}",
            f"- Active source: `{active_contract.source_file}`",
            f"- Current total amount: {format_money(active_contract.total_amount, active_contract.currency)}",
            f"- Active milestone count: {len(active_milestones)}",
            "",
            "## Source Timeline",
            "| Source | Version | Type | State | Page |",
            "|---|---|---|---|---|",
            *(source_rows or ["| - | - | - | - | - |"]),
            "",
            "## Current Milestones",
            "| # | Milestone | Amount | % | Status |",
            "|---|---|---|---|---|",
            *(milestone_rows or ["| - | No milestone schedule extracted from the active source. | - | - | - |"]),
            "",
            "## Contradictions And Version Changes",
            *(unique_lines(conflict_lines) or ["- No version conflicts have been recorded yet."]),
            "",
            *deterministic_summary,
            "",
            *llm_summary,
            "",
            "## Open Questions",
            *(unique_lines(warning_lines) or ["- No validation warnings are currently open."]),
        ]
    )


def generate_source_page(contract: Contract, milestones: list[Milestone], warnings: list[ValidationWarning]) -> str:
    target_path = source_page_path(contract)
    contract_path = contract_page_path(contract.contract_key)
    version_path = contract_version_page_path(contract.contract_key, contract.version_number)
    related = [wiki_relative(contract_path), wiki_relative(version_path)]
    related.extend(wiki_relative(milestone_page_path(contract.contract_key, item.milestone_key)) for item in milestones)
    raw_payload = load_raw_payload(contract)
    notes = []
    for section_name, label in (
        ("scope_items", "Scope"),
        ("acceptance_requirements", "Acceptance"),
        ("safety_requirements", "Safety"),
        ("warranty_requirements", "Warranty"),
    ):
        notes.extend(f"- **{label}:** {item}" for item in unique_lines(raw_payload.get(section_name, []), limit=4))
    validation_lines = [f"- [{warning.severity}] {warning.message}" for warning in warnings]
    conflict_lines = [f"- `{item['field']}` changed from `{item['old']}` to `{item['new']}`" for item in raw_payload.get("version_conflicts", [])]
    milestone_lines = [f"- {markdown_link(target_path, milestone_page_path(contract.contract_key, item.milestone_key), item.name)}" for item in milestones]
    metadata = build_frontmatter(
        {
            "kind": "source",
            "title": contract.source_file,
            "contract_key": contract.contract_key,
            "contract_id": contract.contract_id,
            "version_number": contract.version_number,
            "source_file": contract.source_file,
            "source_hash": contract.source_hash[:12],
            "updated_at": now_label(),
            "related": sorted(set(related)),
            "tags": ["source", contract.doc_category, f"v{contract.version_number}"],
        }
    )
    return "\n".join(
        [
            metadata,
            "",
            f"# Source: {contract.source_file}",
            "",
            "## Metadata",
            f"- Contract: {markdown_link(target_path, contract_path, contract.contract_name)}",
            f"- Version snapshot: {markdown_link(target_path, version_path, f'v{contract.version_number}')}",
            f"- Contract ID: `{contract.contract_id}`",
            f"- Source hash: `{contract.source_hash}`",
            f"- Document type: `{contract.doc_category}`",
            f"- Total amount: {format_money(contract.total_amount, contract.currency)}",
            "",
            "## Extracted Milestones",
            *(milestone_lines or ["- No milestone schedule was extracted from this source."]),
            "",
            "## Version Notes",
            *(conflict_lines or ["- This source did not introduce a tracked contradiction."]),
            "",
            "## Validation",
            *(validation_lines or ["- Validation passed without warnings."]),
            "",
            "## Notes",
            *(notes or ["- No structured technical notes were extracted from this source."]),
        ]
    )


def generate_milestone_page(contract: Contract, milestone: Milestone, *, snapshot: bool = False) -> str:
    target_path = (
        milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)
        if snapshot
        else milestone_page_path(contract.contract_key, milestone.milestone_key)
    )
    contract_path = contract_page_path(contract.contract_key)
    source_path = source_page_path(contract)
    raw_milestone = resolve_raw_milestone(contract, milestone) or {}
    citations = raw_milestone.get("citations") or json.loads(milestone.citations_json)
    grouped_citations: dict[str, list[dict[str, Any]]] = {}
    seen_citations: set[tuple[str, str]] = set()
    citation_priority = {
        "milestone.name": 0,
        "milestone.amount": 1,
        "milestone.percentage": 2,
        "milestone.payment_condition": 3,
        "milestone.acceptance_criteria": 4,
        "milestone.work_items": 5,
    }
    for citation in sorted(citations, key=lambda item: (citation_priority.get(item.get("field_name", ""), 9), item.get("para_start", 0))):
        normalized_snippet = normalize_citation_snippet(citation.get("text_snippet"))
        key = (str(citation.get("field_name", "")), normalized_snippet)
        if key in seen_citations:
            continue
        seen_citations.add(key)
        grouped_citations.setdefault(str(citation.get("field_name", "other")), []).append(citation)
    citation_lines: list[str] = []
    for field_name in sorted(grouped_citations, key=lambda key: citation_priority.get(key, 9)):
        citation_lines.append(f"### {citation_display_label(field_name)}")
        for citation in grouped_citations[field_name]:
            snippet = normalize_citation_snippet(citation.get("text_snippet")) or citation.get("text_snippet", "")
            citation_lines.append(f"- {snippet}")
            citation_lines.append(f"  *{citation['source_file']}, paragraph {citation['para_start']}, page ~{citation['page_estimate']}*")
        citation_lines.append("")
    work_items = raw_milestone.get("work_items") or json.loads(milestone.work_items_json)
    amount = raw_milestone.get("amount", milestone.amount)
    percentage = raw_milestone.get("percentage", milestone.percentage)
    payment_condition = raw_milestone.get("payment_condition", milestone.payment_condition)
    acceptance_criteria = raw_milestone.get("acceptance_criteria", milestone.acceptance_criteria)
    if not acceptance_criteria and work_items:
        acceptance_criteria = normalize_summary_fragment(work_items[0], 120)
    metadata = build_frontmatter(
        {
            "kind": "milestone_version" if snapshot else "milestone",
            "title": milestone.name,
            "contract_key": contract.contract_key,
            "contract_id": contract.contract_id,
            "milestone_key": milestone.milestone_key,
            "milestone_id": milestone.milestone_id,
            "version_number": contract.version_number,
            "updated_at": now_label(),
            "related": [wiki_relative(contract_path), wiki_relative(source_path)],
            "tags": ["milestone", contract.doc_category, milestone.status, f"v{contract.version_number}"],
        }
    )
    return "\n".join(
        [
            metadata,
            "",
            f"# {milestone.name}",
            "",
            "## Context",
            f"- Contract: {markdown_link(target_path, contract_path, contract.contract_name)}",
            f"- Source: {markdown_link(target_path, source_path, contract.source_file)}",
            f"- Milestone key: `{milestone.milestone_key}`",
            f"- Version: `v{contract.version_number}`",
            f"- Amount: {format_money(amount, contract.currency)}",
            f"- Percentage: {percentage or 'N/A'}",
            f"- Status: `{milestone.status}`",
            "",
            "## Terms",
            f"- Payment condition: {payment_condition or 'N/A'}",
            f"- Acceptance criteria: {acceptance_criteria or 'N/A'}",
            "",
            "## Work Items",
            *([f"- {item}" for item in work_items] or ["- No work items were extracted for this milestone."]),
            "",
            "## Citations",
            *(citation_lines or ["- No citations were stored for this milestone."]),
        ]
    )


def regenerate_log(session: Any) -> None:
    ingest_events = session.exec(select(IngestEvent).order_by(IngestEvent.created_at)).all()
    filed_queries = session.exec(select(FiledQuery).order_by(FiledQuery.created_at)).all()
    lines = [
        build_frontmatter({"kind": "log", "title": "Wiki Log", "updated_at": now_label(), "tags": ["log", "wiki"]}),
        "",
        "# Wiki Log",
        "",
    ]
    for event in ingest_events:
        diffs = json.loads(event.diff_json)
        pages = json.loads(event.created_pages_json)
        lines.extend(
            [
                f"## [{event.created_at.strftime('%Y-%m-%d %H:%M UTC')}] ingest | {event.source_file}",
                f"- Action: `{event.action}`",
                f"- Contract key: `{event.contract_key}`",
                f"- Contract ID: `{event.contract_id or '-'}`",
                f"- Version: `v{event.version_number}`",
                f"- Source hash: `{event.source_hash[:12]}`",
                *(f"- Page: `{page}`" for page in pages[:8]),
                *(f"- CONTRADICTION: `{item['field']}` {item['old']} -> {item['new']}" for item in diffs),
                "",
            ]
        )
    for filed in filed_queries:
        lines.extend(
            [
                f"## [{filed.created_at.strftime('%Y-%m-%d %H:%M UTC')}] query | {filed.query_id}",
                f"- Chat session: `{filed.chat_session_id}`",
                f"- Question: {filed.question}",
                f"- Wiki page: `{filed.wiki_path}`",
                "",
            ]
        )
    write_markdown(settings.wiki_dir / "log.md", "\n".join(lines))


def regenerate_index(session: Any) -> None:
    contracts = session.exec(select(Contract).order_by(Contract.contract_key, Contract.version_number.desc())).all()
    grouped: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.contract_key].append(contract)
    filed_queries = session.exec(select(FiledQuery).order_by(FiledQuery.created_at.desc())).all()
    lines = [
        build_frontmatter({"kind": "index", "title": "Repository Index", "updated_at": now_label(), "tags": ["index", "wiki"]}),
        "",
        "# Repository Index",
        "",
        "## Contracts",
    ]
    for contract_key, items in grouped.items():
        active = next((item for item in items if not item.is_superseded), items[0])
        lines.append(f"- [{active.contract_name}](contracts/{contract_key}.md) · `{contract_key}` · {len(items)} versions")
    lines.extend(["", "## Sources"])
    for contract in contracts:
        lines.append(f"- [{contract.source_file}](sources/{contract.contract_key}__v{contract.version_number}.md) · `{contract.contract_key}` · v{contract.version_number} · {contract.doc_category}")
    lines.extend(["", "## Query Notes"])
    if filed_queries:
        lines.extend(f"- [{item.question[:80]}]({item.wiki_path})" for item in filed_queries)
    else:
        lines.append("- No query notes have been filed yet.")
    lines.extend(["", "## Operations", "- [Wiki Log](log.md)"])
    write_markdown(settings.wiki_dir / "index.md", "\n".join(lines))


def pages_for_contract(contract: Contract, milestones: list[Milestone]) -> list[str]:
    pages = [
        wiki_relative(contract_page_path(contract.contract_key)),
        wiki_relative(contract_version_page_path(contract.contract_key, contract.version_number)),
        wiki_relative(source_page_path(contract)),
    ]
    for milestone in milestones:
        pages.append(wiki_relative(milestone_page_path(contract.contract_key, milestone.milestone_key)))
        pages.append(wiki_relative(milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)))
    return pages


def rebuild_contract_artifacts(session: Any, latest_contract_id: str, source_file: str, version_conflicts: list[dict[str, Any]], action: str = "updated") -> list[str]:
    ensure_generated_dirs()
    for directory in ["contracts", "contract_versions", "sources", "milestones", "milestone_versions"]:
        reset_generated_dir(directory)

    contracts = session.exec(select(Contract).order_by(Contract.contract_key, Contract.version_number.desc())).all()
    grouped: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.contract_key].append(contract)

    written_pages: list[str] = []
    for contract_key, items in grouped.items():
        canonical_path = contract_page_path(contract_key)
        generated = generate_contract_page(contract_key, items, session)
        write_markdown(canonical_path, maintain_with_local_llm(canonical_path, generated, contract_key))
        written_pages.append(wiki_relative(canonical_path))
        for contract in items:
            version_path = contract_version_page_path(contract.contract_key, contract.version_number)
            write_markdown(version_path, generate_contract_page(contract.contract_key, [contract], session, snapshot=True))
            written_pages.append(wiki_relative(version_path))
            milestones = load_milestone_rows(session, contract.contract_id)
            source_path = source_page_path(contract)
            write_markdown(source_path, generate_source_page(contract, milestones, load_validation_rows(session, contract.contract_id)))
            written_pages.append(wiki_relative(source_path))
            for milestone in milestones:
                canonical_milestone = milestone_page_path(contract.contract_key, milestone.milestone_key)
                version_milestone = milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)
                if not contract.is_superseded:
                    write_markdown(canonical_milestone, generate_milestone_page(contract, milestone))
                    written_pages.append(wiki_relative(canonical_milestone))
                write_markdown(version_milestone, generate_milestone_page(contract, milestone, snapshot=True))
                written_pages.append(wiki_relative(version_milestone))

    regenerate_index(session)
    regenerate_log(session)
    return sorted(set(written_pages))


def append_query_note(
    *,
    session: Any,
    chat_session_id: str,
    human_message_id: int | None,
    ai_message_id: int | None,
    contract_id: str | None,
    query: str,
    answer: str,
    citations: list[dict[str, Any]],
    answer_method: str,
    retrieval_mode: str,
) -> str:
    ensure_generated_dirs()
    query_id = f"query_{uuid4().hex[:12]}"
    path = query_page_path(query_id)
    related: list[str] = []
    if contract_id:
        contract = session.get(Contract, contract_id)
        if contract:
            related.extend([wiki_relative(contract_page_path(contract.contract_key)), wiki_relative(source_page_path(contract))])
    for citation in citations:
        for key in ("project_path", "source_path", "milestone_path"):
            if citation.get(key):
                related.append(citation[key])
    metadata = build_frontmatter(
        {
            "kind": "query",
            "title": query[:80],
            "query_id": query_id,
            "chat_session_id": chat_session_id,
            "contract_id": contract_id or "",
            "updated_at": now_label(),
            "related": sorted(set(related)),
            "tags": ["query", retrieval_mode],
        }
    )
    citation_lines = [
        f"- `{item.get('source_file')}` · block `{item.get('chunk_id') or item.get('block_id')}` · page ~{item.get('page_estimate')} · {item.get('text_snippet', '')[:180]}"
        for item in citations[:8]
    ]
    content = "\n".join(
        [
            metadata,
            "",
            f"# {query}",
            "",
            f"- Chat session: `{chat_session_id}`",
            f"- Answer method: `{answer_method}`",
            f"- Retrieval mode: `{retrieval_mode}`",
            "",
            "## Answer",
            answer,
            "",
            "## Evidence",
            *(citation_lines or ["- No evidence was attached."]),
        ]
    )
    write_markdown(path, content)
    session.add(
        FiledQuery(
            query_id=query_id,
            chat_session_id=chat_session_id,
            human_message_id=human_message_id,
            ai_message_id=ai_message_id,
            question=query,
            answer=answer,
            contract_scope_json=json.dumps([contract_id] if contract_id else [], ensure_ascii=False),
            citations_json=json.dumps(citations, ensure_ascii=False),
            wiki_path=wiki_relative(path),
            answer_method=answer_method,
            retrieval_mode=retrieval_mode,
        )
    )
    session.commit()
    regenerate_index(session)
    regenerate_log(session)
    return wiki_relative(path)


def build_wiki_manifest() -> dict[str, Any]:
    ensure_generated_dirs()
    pages: list[dict[str, Any]] = []
    for path in sorted(settings.wiki_dir.rglob("*.md")):
        relative = wiki_relative(path)
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        pages.append(
            {
                "path": relative,
                "kind": metadata.get("kind", "page"),
                "title": metadata.get("title") or path.stem,
                "summary": summarize_page(body),
                "updated_at": metadata.get("updated_at") or datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%d %H:%M UTC"),
                "tags": metadata.get("tags", []),
                "related": metadata.get("related", []),
            }
        )
    return {
        "pages": pages,
        "counts": {
            "total": len(pages),
            "contracts": sum(1 for item in pages if item["path"].startswith("contracts/")),
            "contract_versions": sum(1 for item in pages if item["path"].startswith("contract_versions/")),
            "sources": sum(1 for item in pages if item["path"].startswith("sources/")),
            "milestones": sum(1 for item in pages if item["path"].startswith("milestones/")),
            "milestone_versions": sum(1 for item in pages if item["path"].startswith("milestone_versions/")),
            "queries": sum(1 for item in pages if item["path"].startswith("queries/")),
        },
    }


def read_wiki_page(relative_path: str) -> dict[str, Any]:
    target = settings.wiki_dir / relative_path
    resolved = target.resolve()
    wiki_root = settings.wiki_dir.resolve()
    if not resolved.is_file() or wiki_root not in resolved.parents:
        raise FileNotFoundError(relative_path)
    content = resolved.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(content)
    manifest = build_wiki_manifest()["pages"]
    backlinks = [item for item in manifest if relative_path in item.get("related", [])]
    return {"path": relative_path, "content": body, "metadata": metadata, "backlinks": backlinks}


def resolve_contract_wiki_paths(session: Any, contract_id: str) -> dict[str, str]:
    contract = session.get(Contract, contract_id)
    if not contract:
        raise FileNotFoundError(contract_id)
    return {
        "contract_path": wiki_relative(contract_page_path(contract.contract_key)),
        "project_path": wiki_relative(contract_page_path(contract.contract_key)),
        "source_path": wiki_relative(source_page_path(contract)),
        "version_path": wiki_relative(contract_version_page_path(contract.contract_key, contract.version_number)),
    }


def resolve_milestone_wiki_path(session: Any, milestone_id: str) -> dict[str, str]:
    milestone = session.get(Milestone, milestone_id)
    if not milestone:
        raise FileNotFoundError(milestone_id)
    contract = session.get(Contract, milestone.contract_id)
    if not contract:
        raise FileNotFoundError(milestone_id)
    return {
        "milestone_path": wiki_relative(milestone_page_path(contract.contract_key, milestone.milestone_key)),
        "milestone_version_path": wiki_relative(milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number)),
    }


def run_wiki_lint(session: Any) -> dict[str, Any]:
    manifest = build_wiki_manifest()["pages"]
    page_paths = {item["path"] for item in manifest}
    findings: list[dict[str, str]] = []
    for page in manifest:
        for related in page.get("related", []):
            if related not in page_paths:
                findings.append({"severity": "warning", "page": page["path"], "message": f"Missing related page: {related}"})
        if page["kind"] in {"contract", "source", "milestone", "query"} and not page.get("related"):
            findings.append({"severity": "warning", "page": page["path"], "message": "Page has no related links in metadata."})
    for contract in session.exec(select(Contract)).all():
        expected = wiki_relative(source_page_path(contract))
        if expected not in page_paths:
            findings.append({"severity": "error", "page": expected, "message": "Missing source page for ingested contract."})
    for milestone in session.exec(select(Milestone)).all():
        contract = session.get(Contract, milestone.contract_id)
        if not contract:
            continue
        expected = wiki_relative(milestone_version_page_path(contract.contract_key, milestone.milestone_key, contract.version_number))
        if expected not in page_paths:
            findings.append({"severity": "error", "page": expected, "message": "Missing milestone version page."})
        if not json.loads(milestone.citations_json):
            findings.append({"severity": "warning", "page": expected, "message": "Milestone has no citations attached."})
    return {
        "status": "ok" if not any(item["severity"] == "error" for item in findings) else "warning",
        "findings": findings,
        "counts": build_wiki_manifest()["counts"],
    }
