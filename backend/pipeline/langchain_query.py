from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlmodel import select

from backend.config import settings
from backend.db.models import ChatMessage, ChatSession, Contract, FiledQuery, ValidationWarning
from backend.pipeline.embeddings import embedding_model_ready
from backend.pipeline.indexer import hybrid_search_chunks
from backend.pipeline.llm import llm_available, query_local_messages_detailed
from backend.pipeline.qdrant_store import qdrant_ready
from backend.pipeline.reranker import rerank_citations
from backend.wiki.generator import append_query_note, resolve_contract_wiki_paths


def ensure_chat_session(session: Any, chat_session_id: str | None, contract_id: str | None, first_query: str) -> ChatSession:
    if chat_session_id:
        existing = session.get(ChatSession, chat_session_id)
        if existing:
            return existing
    new_session = ChatSession(
        chat_session_id=chat_session_id or f"chat_{uuid4().hex[:12]}",
        title=first_query[:80],
        contract_id=contract_id,
    )
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    return new_session


def load_history(session: Any, chat_session_id: str, limit: int = 10) -> list[BaseMessage]:
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == chat_session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    ).all()
    messages: list[BaseMessage] = []
    for row in reversed(rows):
        if row.role == "human":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "ai":
            messages.append(AIMessage(content=row.content))
    return messages


def append_message(session: Any, chat_session_id: str, role: str, content: str) -> ChatMessage:
    row = ChatMessage(chat_session_id=chat_session_id, role=role, content=content)
    session.add(row)
    chat_session = session.get(ChatSession, chat_session_id)
    if chat_session:
        from backend.db.models import now_utc

        chat_session.updated_at = now_utc()
        session.add(chat_session)
    session.commit()
    session.refresh(row)
    return row


def history_to_messages(history: list[BaseMessage]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in history:
        if isinstance(item, HumanMessage):
            messages.append({"role": "user", "content": str(item.content)})
        elif isinstance(item, AIMessage):
            messages.append({"role": "assistant", "content": str(item.content)})
    return messages


def format_evidence(citations: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {"clause": [], "subclause": [], "section": [], "requirement": [], "structured": [], "wiki": []}
    for citation in citations:
        grouped.setdefault(citation.get("chunk_type") or "clause", []).append(citation)
    sections: list[str] = []
    if grouped["structured"]:
        sections.append("【檢索到的結構化證據】")
        for index, citation in enumerate(grouped["structured"], start=1):
            sections.append(
                f"[S{index}] ({citation.get('structured_kind') or 'structured'}) {citation.get('text_snippet', '')}"
            )
    clause_like = grouped["clause"] + grouped["subclause"] + grouped["section"] + grouped["requirement"]
    if clause_like:
        sections.append("【原始條款證據】")
        for index, citation in enumerate(clause_like, start=1):
            expansion_note = ""
            if citation.get("retrieval_method") == "parent_expansion":
                expansion_note = f", 上下文補足自={citation.get('triggered_by') or '-'}"
            sections.append(
                f"[C{index}] {citation.get('text_snippet', '')} "
                f"(條款={citation.get('clause_label') or '-'}, 合約={citation.get('contract_id')}, 段落={citation.get('para_start')}, 頁~{citation.get('page_estimate')}{expansion_note})"
            )
    return "\n".join(sections)


def retrieval_mode() -> str:
    if embedding_model_ready() and qdrant_ready():
        return "hybrid_qdrant"
    if embedding_model_ready():
        return "hybrid_local"
    return "bm25_only"


QUERY_EXPANSIONS: dict[str, str] = {
    "overview": "摘要 重點 文件目的 範圍 說明 文件主要內容",
    "risk": "風險 違約 違約金 扣罰 賠償 逾期 固定總價 不得追加",
    "payment": "付款 給付 工程款 請款 期款",
    "acceptance": "驗收 核定 確認 完工 測試通過 交付",
    "milestone": "里程碑 期款 工程節點 階段 驗收",
    "penalty": "違約金 扣罰 罰則 逾期",
    "retention": "保留款 保固保證金 履約保證金 保固期",
    "warranty": "保固 保證金 缺失 修繕",
    "delay": "逾期 展延 工程進度落後 扣罰",
    "change": "變更 追加工程款 固定總價 不得追加",
    "price_adjustment": "固定總價 不得追加 不得調整 法令變更 情事變更 單價",
    "force_majeure": "關稅措施 情事變更 免責 不補償 終止 不可抗力",
}

ACTION_QUERY_RE = re.compile(r"(可以採取哪些行動|可以怎麼做|可以如何處理|有哪些權利|得採取|得否|甲方可以|乙方可以)")
PROGRESS_DELAY_RE = re.compile(r"(進度|落後|逾期|延誤)")
PAYMENT_RE = re.compile(r"(付款|請款|工程款|期款|給付)")
ACCEPTANCE_RE = re.compile(r"(驗收|核定|確認|完工|測試通過|交付)")
RISK_RE = re.compile(r"(風險|違約|罰款|扣罰|賠償)")
PRICE_ADJUSTMENT_RE = re.compile(r"(關稅|貿易|法令|政策|調價|固定總價|不得追加|tariff|trade)", re.IGNORECASE)
FORCE_MAJEURE_RE = re.compile(r"(不可抗力|天災|force majeure)", re.IGNORECASE)
OVERVIEW_RE = re.compile(r"(主要是在規範什麼|主要內容|這份文件.*規範|what is this document about|summarize)", re.IGNORECASE)
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
ACTION_FALLBACK_TERMS = "得 暫停付款 違約金 扣罰 終止 解除 另覓廠商 書面通知 不補償 費用由乙方負擔"
PROGRESS_ACTION_TERMS = "進度落後 逾期 履約期限 暫停付款 違約金 終止契約 解除契約 另覓廠商"
PRICE_ADJUSTMENT_TERMS = "固定總價 不得追加 不得調整 法令變更 政策變更 情事變更 單價"
FORCE_MAJEURE_TERMS = "不可抗力 關稅措施 情事變更 免責 不補償 終止"


def classify_query_intents(query: str) -> set[str]:
    intents: set[str] = set()
    text = query or ""
    lowered = text.lower()
    if ACTION_QUERY_RE.search(text):
        intents.add("action")
    if OVERVIEW_RE.search(text):
        intents.add("overview")
    if PROGRESS_DELAY_RE.search(text):
        intents.add("progress_delay")
    if PAYMENT_RE.search(text) or "payment" in lowered:
        intents.add("payment")
    if ACCEPTANCE_RE.search(text):
        intents.add("acceptance")
    if RISK_RE.search(text) or "risk" in lowered or "penalty" in lowered:
        intents.add("risk")
    if PRICE_ADJUSTMENT_RE.search(text):
        intents.add("price_adjustment")
    if FORCE_MAJEURE_RE.search(text):
        intents.add("force_majeure")
    return intents


def expand_query(query: str, intents: set[str]) -> str:
    lowered = (query or "").lower()
    expansions = [terms for keyword, terms in QUERY_EXPANSIONS.items() if keyword in lowered]
    if "action" in intents:
        expansions.append(ACTION_FALLBACK_TERMS)
    if "progress_delay" in intents:
        expansions.append(PROGRESS_ACTION_TERMS)
    if "price_adjustment" in intents:
        expansions.append(PRICE_ADJUSTMENT_TERMS)
    if "force_majeure" in intents:
        expansions.append(FORCE_MAJEURE_TERMS)
    if not expansions:
        return query
    return f"{query}\n" + "\n".join(expansions)


def exact_match_terms(intents: set[str], document_type: str) -> tuple[str, ...]:
    if "payment" in intents:
        return ("付款", "請款", "期款", "工程款", "金額", "總價", "保證金", "費用")
    if "acceptance" in intents:
        return ("驗收", "核定", "確認", "完工", "測試", "交付", "施工計劃書")
    if "price_adjustment" in intents:
        return ("關稅", "法令變更", "政策變更", "調整", "總價", "追加工程款", "固定總價")
    if "force_majeure" in intents:
        return ("不可抗力", "天災", "關稅", "法令變更", "政策變更")
    if "risk" in intents and document_type in {"spec_rfp", "instruction_manual", "mixed"}:
        return ("保固", "責任", "安全", "賠償", "查驗", "瑕疵")
    if "overview" in intents:
        return ("摘要", "目的", "範圍", "內容", "系統", "說明")
    return ()


def detect_output_language(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return "繁體中文"
    chinese_chars = len(CHINESE_CHAR_RE.findall(text))
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    return "繁體中文" if chinese_chars >= ascii_letters else "English"


def load_contract_payload(contract: Contract) -> dict[str, Any]:
    try:
        return json.loads(open(contract.raw_json_path, "r", encoding="utf-8").read())
    except Exception:
        return {}


def build_structured_context(session: Any, contract_ids: list[str], intents: set[str]) -> str:
    sections: list[str] = []
    for contract_id in contract_ids:
        contract = session.get(Contract, contract_id)
        if not contract:
            continue
        payload = load_contract_payload(contract)
        warnings = session.exec(select(ValidationWarning).where(ValidationWarning.contract_id == contract_id)).all()
        milestone_count = len(payload.get("milestones", []))
        lines = [
            f"- 合約：{contract.contract_name}",
            f"- 來源檔案：{contract.source_file}",
            f"- 總金額：{contract.total_amount if contract.total_amount is not None else '未明示'} {contract.currency}",
            f"- 付款類型：{payload.get('payment_type') or contract.contract_type or 'unknown'}",
            f"- 里程碑數：{milestone_count}",
        ]
        if "action" not in intents and "progress_delay" not in intents:
            for warning in warnings:
                if warning.severity not in {"ERROR", "WARNING"}:
                    continue
                lines.append(f"- {warning.severity}: {warning.message}")
        retention = payload.get("retention") or {}
        if retention.get("amount") is not None or retention.get("release_condition"):
            lines.append(
                f"- 保留款：{retention.get('amount') if retention.get('amount') is not None else '未明示'} {contract.currency}；"
                f"釋放條件：{retention.get('release_condition') or '未明示'}；"
                f"釋放期限（月）：{retention.get('release_after_months') if retention.get('release_after_months') is not None else '未明示'}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def build_answer_instructions(intents: set[str], output_language: str) -> str:
    lines = [
        "回答時必須嚴格以證據為準，不可補充未檢索到的條款。",
        "不可自行補入一般法律原則、法院可能見解、情勢變更、誠信原則、協商建議、仲裁或訴訟策略，除非使用者明確要求你回答『一般法律上』或『若依民法/法律原則』如何判斷。",
        "如果不同條款提供不同權利、救濟或後果，應合併整理，但只保留與問題直接相關的重點。",
        "每一個結論後面都要標明對應條款。",
        "先判斷文件屬於正式契約、RFP、修訂版本文件，或僅有百分比排程但沒有總價的文件，再決定回答方式。",
        "如果判斷為 RFP、施工說明書、技術規格書、招標需求文件、建議書或其他非正式契約文件，必須明確指出該性質，且只能回答文件中實際寫出的需求、規格、程序或責任；不得把正式工程承攬契約常見條款（如違約金、不可抗力、轉包限制、調價機制）當成當然存在。",
        "如果文件沒有寫明付款、不可抗力、調價、轉包、終止/解除等條款，就直接回答『文件未明確規定／證據不足』，不要延伸討論一般可能做法。",
        "如果問題涉及合約風險、付款、驗收、保固、違約、終止/解除、不可抗力、關稅、轉包/分包、損害賠償，應主動檢查多個相關條款。",
        "對工程承攬契約，優先留意：工程總價、不得追加工程款、付款辦法、驗收標準、遲延罰款、暫停給付、損害賠償、契約終止與解除、不可抗力、保固、轉包限制。",
        f"最終回答語言必須使用：{output_language}。",
        "回答長度應適中：先給直接答案，再列 3 到 6 個最重要重點；除非使用者要求詳細說明，不要寫成長篇報告。",
        "回答應偏短，不要過度解釋；每個段落以 1 到 3 句為上限。",
        "避免重複同一條款、避免逐字重述長段條文、避免輸出不必要的標題或自我檢查內容。",
        "不要輸出 Markdown 表格，不要使用 |---| 或欄位表；一律改用條列或短段落。",
        "不要輸出 Markdown 水平線（---）、不要輸出『相關註記』、『解析說明』、『文件性質判斷』這類額外前言或後記。",
        "不要輸出 emoji、圖示、流程圖、ASCII 圖、表情符號、區塊引言（>）。",
        "不要輸出 <analysis>、<think>、Thought、Analysis、Reasoning、Draft、內部分析、思考過程、推理過程、草稿、檢查清單或任何自我對話。",
        "格式必須固定且簡潔，只能使用簡單標題與單層條列。",
        "若使用者以中文提問，必須只用繁體中文作答，不可混用簡體中文。",
    ]
    if "action" in intents or "progress_delay" in intents:
        lines.extend(
            [
                "這是一個『可採取哪些行動／救濟』問題。",
                "應列出主要可主張的行動，例如：暫停付款、扣罰違約金、終止或解除契約、另覓廠商、扣抵款項、請求損害賠償。",
                "如果多個條款都成立，請合併整理，但不要把相近效果拆成重複段落。",
                "若某行動有門檻條件，請明確寫出門檻與本題事實是否符合。",
                "固定輸出格式：",
                "## 結論",
                "用 1 到 2 句直接回答。",
                "## 可採取的行動",
                "列 3 到 6 點，每點 1 句，格式為：行動：內容（條款）。",
                "## 限制／條件",
                "列出真正重要的門檻條件，沒有就寫「- 無額外限制」。",
            ]
        )
    if "payment" in intents:
        lines.extend(
            [
                "這是一個付款／請款問題。",
                "必須區分付款觸發條件、驗收條件、請款文件要求、實際金額、百分比、保留款、以及是否存在暫停付款或扣抵權利。",
                "固定輸出格式：",
                "## 結論",
                "先用 1 到 2 句直接回答付款模式與付款期限。",
                "## 各期付款",
                "依期數列點；每一期固定格式為：第X期：金額／比例／請款條件。",
                "## 付款期限",
                "只寫付款期限與請款文件要求。",
                "## 條款依據",
                "列 1 到 3 點最關鍵條款。",
            ]
        )
    if "risk" in intents:
        lines.extend(
            [
                "這是一個風險問題。",
                "必須優先檢查：遲延罰款、暫停付款、終止/解除、另覓廠商、扣抵款項、損害賠償、保固責任、不可抗力排除、關稅不屬不可抗力、客戶責任轉嫁、不得追加工程款。",
                "如果文件屬於 RFP、施工說明書、技術規格書或其他非正式契約文件，風險只能寫：文件中明示的責任、文件缺少的商務保護條款、以及由此造成的不確定性；不得擴寫為正式契約風險備忘錄。",
                "只列最重要的風險類別，不要把相近風險拆成過多小節。",
                "固定輸出格式：",
                "## 結論",
                "先用 1 到 2 句總結風險高低與主要風險方向。",
                "## 主要風險",
                "列 3 到 6 點；每點格式為：風險名稱：簡短說明（條款）。",
                "## 注意事項",
                "只補充 1 到 3 點真正重要的限制或例外。",
            ]
        )
    if "payment" not in intents and "action" not in intents and "progress_delay" not in intents and "risk" not in intents:
        lines.extend(
            [
                "固定輸出格式：",
                "## 結論",
                "先用 1 到 2 句直接回答。",
                "## 主要重點",
                "列 3 到 5 點，每點 1 句。",
                "## 條款依據",
                "列 1 到 3 點最關鍵條款。",
            ]
        )
    return "\n".join(f"- {line}" for line in lines)


def record_query_result(
    *,
    session: Any,
    chat_session_id: str,
    human_message_id: int | None,
    ai_message_id: int | None,
    contract_id: str | None,
    query: str,
    answer: str,
    citations: list[dict[str, Any]],
    wiki_path: str,
    answer_method: str,
    retrieval_mode_value: str,
) -> None:
    session.add(
        FiledQuery(
            query_id=f"query_{uuid4().hex[:12]}",
            chat_session_id=chat_session_id,
            human_message_id=human_message_id,
            ai_message_id=ai_message_id,
            question=query,
            answer=answer,
            contract_scope_json=json.dumps([contract_id] if contract_id else [], ensure_ascii=False),
            citations_json=json.dumps(citations, ensure_ascii=False),
            wiki_path=wiki_path,
            answer_method=answer_method,
            retrieval_mode=retrieval_mode_value,
        )
    )
    session.commit()


def source_weight(item: dict[str, Any], intents: set[str]) -> float:
    chunk_type = item.get("chunk_type")
    structured_kind = item.get("structured_kind")
    text = item.get("text_snippet", "")
    clause_family = set(item.get("clause_family") or [])
    document_type = item.get("document_type") or "formal_contract"
    is_nonformal = document_type in {"spec_rfp", "instruction_manual", "mixed"}
    weight = 0.0
    if chunk_type in {"clause", "section"}:
        weight += 0.2
    elif chunk_type in {"subclause", "requirement"}:
        weight += 0.15
    elif chunk_type == "structured":
        if structured_kind == "clause_action_summary":
            weight += 0.22
        elif structured_kind in {"wiki_llm_summary", "wiki_contract_summary"}:
            label = item.get("clause_label") or ""
            if "overview" in intents or not intents:
                weight += 0.18
                if label in {"契約目的", "At A Glance"}:
                    weight += 0.10
                elif label in {"風險與注意事項", "Risks And Open Issues"}:
                    weight -= 0.03
            if "risk" in intents and clause_family & {"damages", "warranty", "price_adjustment"}:
                weight += 0.16
                if label in {"風險與注意事項", "Risks And Open Issues"}:
                    weight += 0.08
            if "payment" in intents and clause_family & {"payment", "milestone"}:
                weight += 0.16
                if label in {"商務與付款", "Milestone And Payment Structure", "Payment Procedures And Commercial Notes"}:
                    weight += 0.08
            if "acceptance" in intents and "acceptance" in clause_family:
                weight += 0.16
                if label in {"交付與驗收", "Delivery And Acceptance"}:
                    weight += 0.08
            if "price_adjustment" in intents and "price_adjustment" in clause_family:
                weight += 0.18
            if "force_majeure" in intents and "force_majeure" in clause_family:
                weight += 0.18
        elif structured_kind == "contract_summary":
            weight -= 0.05
        elif structured_kind == "milestone_summary":
            weight -= 0.08 if "action" in intents else 0.0
        elif structured_kind == "retention_summary":
            weight -= 0.08 if "action" in intents else 0.0
        elif structured_kind == "validation_risk":
            weight -= 0.15 if "action" in intents else -0.05
    elif chunk_type == "wiki":
        weight -= 0.25
    if "action" in intents:
        if any(term in text for term in ["暫停付款", "違約金", "扣罰", "終止", "解除", "另覓廠商", "書面通知", "費用由乙方負擔"]):
            weight += 0.18
        if structured_kind == "clause_action_summary":
            weight += 0.08
    if "progress_delay" in intents and any(term in text for term in ["進度", "落後", "逾期", "延誤"]):
        weight += 0.08
    if "payment" in intents and clause_family & {"payment", "milestone", "retention"}:
        weight += 0.10
    if "acceptance" in intents and "acceptance" in clause_family:
        weight += 0.14
    risk_families = {"warranty", "price_adjustment", "damages"} if is_nonformal else {"penalty", "termination", "damages", "warranty", "subcontracting", "price_adjustment", "force_majeure"}
    if "risk" in intents and clause_family & risk_families:
        weight += 0.10
    if "price_adjustment" in intents and "price_adjustment" in clause_family:
        weight += 0.16
    if "force_majeure" in intents and "force_majeure" in clause_family and not is_nonformal:
        weight += 0.16
    if is_nonformal and float(item.get("bm25_score", 0.0)) > 0.0:
        weight += 0.10
    if is_nonformal:
        label_text = f"{item.get('clause_label') or ''} {text}"
        terms = exact_match_terms(intents, document_type)
        if terms and any(term in label_text for term in terms):
            weight += 0.18
    return weight


def expand_related_action_candidates(citations: list[dict[str, Any]], intents: set[str]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for item in citations:
        boosted = dict(item)
        boosted["weighted_retrieval_score_raw"] = float(boosted["retrieval_score"]) + source_weight(boosted, intents)
        boosted["retrieval_score"] = float(boosted["weighted_retrieval_score_raw"])
        expanded.append(boosted)
    return expanded


def normalize_candidate_scores(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not citations:
        return citations
    max_score = max(float(item.get("retrieval_score", 0.0)) for item in citations)
    if max_score <= 0.0:
        return citations
    normalized: list[dict[str, Any]] = []
    for item in citations:
        updated = dict(item)
        updated["retrieval_score"] = float(updated.get("retrieval_score", 0.0)) / max_score
        normalized.append(updated)
    return normalized


def select_diverse_citations(citations: list[dict[str, Any]], top_k: int, intents: set[str]) -> list[dict[str, Any]]:
    weighted = expand_related_action_candidates(citations, intents)
    normalized = normalize_candidate_scores(weighted)
    ordered = sorted(normalized, key=lambda item: item["retrieval_score"], reverse=True)
    clause_like = [item for item in ordered if item.get("chunk_type") in {"clause", "subclause", "section", "requirement"}]
    structured = [item for item in ordered if item.get("chunk_type") == "structured"]
    wiki = [item for item in ordered if item.get("chunk_type") == "wiki"]
    document_types = {item.get("document_type") for item in ordered if item.get("document_type")}
    is_nonformal = any(item in {"spec_rfp", "instruction_manual", "mixed"} for item in document_types)
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()

    def push(items: list[dict[str, Any]], limit: int) -> None:
        added = 0
        for item in items:
            key = (item.get("contract_id"), item.get("chunk_id"))
            if key in seen:
                continue
            selected.append(item)
            seen.add(key)
            added += 1
            if added >= limit:
                break

    if structured:
        structured_sorted = sorted(
            structured,
            key=lambda item: (
                not (
                    is_nonformal
                    and item.get("structured_kind") in {"wiki_llm_summary", "wiki_contract_summary"}
                    and ({"overview", "risk", "payment", "acceptance", "price_adjustment", "force_majeure"} & intents or "overview" in intents)
                ),
                item.get("structured_kind") != "clause_action_summary",
                -float(item["retrieval_score"]),
            ),
        )
        if is_nonformal and ({"overview", "risk", "payment", "acceptance", "price_adjustment", "force_majeure"} & intents):
            push(structured_sorted, min(3, len(structured_sorted)))
    if clause_like:
        push(clause_like, min(max(5, top_k - (3 if is_nonformal else 2)), len(clause_like)))
    if structured and not (is_nonformal and ({"overview", "risk", "payment", "acceptance", "price_adjustment", "force_majeure"} & intents)):
        structured_sorted = sorted(
            structured,
            key=lambda item: (item.get("structured_kind") != "clause_action_summary", -float(item["retrieval_score"])),
        )
        push(structured_sorted, min(3 if "action" in intents else 2, len(structured_sorted)))
    if wiki and len(selected) < max(3, top_k // 2) and not clause_like:
        push(wiki, 1)
    for item in ordered:
        key = (item.get("contract_id"), item.get("chunk_id"))
        if key in seen:
            continue
        if item.get("chunk_type") == "wiki" and clause_like:
            continue
        selected.append(item)
        seen.add(key)
        if len(selected) >= top_k:
            break
    if len(selected) < top_k and wiki and not clause_like:
        push(wiki, min(1, top_k - len(selected)))
    nonformal_with_bm25 = [
        item for item in ordered
        if (item.get("document_type") in {"spec_rfp", "instruction_manual", "mixed"})
        and float(item.get("bm25_score", 0.0)) > 0.0
    ]
    if nonformal_with_bm25:
        terms = exact_match_terms(intents, "spec_rfp")
        best_bm25 = max(
            nonformal_with_bm25,
            key=lambda item: (
                item.get("structured_kind") in {"wiki_llm_summary", "wiki_contract_summary"},
                any(term in f"{item.get('clause_label') or ''} {item.get('text_snippet') or ''}" for term in terms),
                float(item.get("bm25_score", 0.0)),
                float(item.get("retrieval_score", 0.0)),
            ),
        )
        key = (best_bm25.get("contract_id"), best_bm25.get("chunk_id"))
        if key not in seen:
            if len(selected) >= top_k:
                selected[-1] = best_bm25
            else:
                selected.append(best_bm25)
    return selected[:top_k]


def retrieve_query_evidence(
    *,
    session: Any,
    query: str,
    contract_ids: list[str],
    top_k: int,
) -> dict[str, Any]:
    intents = classify_query_intents(query)
    expanded_query = expand_query(query, intents)
    citations: list[dict[str, Any]] = []
    mode = retrieval_mode()
    candidate_k = max(top_k * 4, 24)
    for current_contract_id in contract_ids:
        contract = session.get(Contract, current_contract_id)
        for hit in hybrid_search_chunks(current_contract_id, expanded_query, candidate_k, intents=intents):
            hit["contract_id"] = current_contract_id
            hit["source_file"] = contract.source_file if contract else None
            try:
                hit.update(resolve_contract_wiki_paths(session, current_contract_id))
            except FileNotFoundError:
                pass
            citations.append(hit)
    citations = [item for item in citations if item.get("chunk_type") != "wiki"]
    citations = [item for item in citations if item.get("structured_kind") != "validation_risk"]
    reranked = rerank_citations(expanded_query, citations, top_n=min(len(citations), candidate_k), timeout=20.0)
    if reranked:
        citations = reranked
        mode = f"{mode}_reranked"
    citations = select_diverse_citations(citations, top_k, intents)
    return {
        "intents": sorted(intents),
        "expanded_query": expanded_query,
        "citations": citations,
        "retrieval_mode": mode,
        "reranker_model_name": settings.reranker_model_name if reranked else None,
    }


def answer_with_langchain(
    *,
    session: Any,
    query: str,
    contract_ids: list[str],
    contract_id: str | None,
    top_k: int,
    chat_session_id: str | None,
    persist_to_wiki: bool = False,
    persist_chat: bool = True,
) -> dict[str, Any]:
    if not llm_available():
        raise RuntimeError("Local LLM is not ready.")
    chat_session = ensure_chat_session(session, chat_session_id, contract_id, query) if persist_chat else None
    retrieval = retrieve_query_evidence(session=session, query=query, contract_ids=contract_ids, top_k=top_k)
    intents = set(retrieval["intents"])
    citations = list(retrieval["citations"])
    retrieval_mode_value = str(retrieval["retrieval_mode"])
    if not citations:
        answer = "No matching evidence found in the local indexes."
        if persist_chat and chat_session is not None:
            human_row = append_message(session, chat_session.chat_session_id, "human", query)
            ai_row = append_message(session, chat_session.chat_session_id, "ai", answer)
            record_query_result(
                session=session,
                chat_session_id=chat_session.chat_session_id,
                human_message_id=human_row.id,
                ai_message_id=ai_row.id,
                contract_id=contract_id,
                query=query,
                answer=answer,
                citations=[],
                wiki_path="",
                answer_method="no_evidence",
                retrieval_mode_value=retrieval_mode_value,
            )
        return {
            "chat_session_id": chat_session.chat_session_id if chat_session is not None else None,
            "answer": answer,
            "citations": [],
            "answer_method": "no_evidence",
            "retrieval_mode": retrieval_mode_value,
            "model_name": settings.local_query_model_name,
            "reranker_model_name": retrieval.get("reranker_model_name"),
            "wiki_path": None,
        }

    evidence = format_evidence(citations)
    structured_context = build_structured_context(session, contract_ids, intents)
    output_language = detect_output_language(query)
    answer_instructions = build_answer_instructions(intents, output_language)
    system_prompt = (
        "你是一個離線合約分析助理。"
        "只能根據提供的結構化資料與檢索證據回答。"
        "先使用原始條款證據。"
        "對話歷史只能用來理解代稱，不能新增事實。"
        "如果證據不足，必須明確說明證據不足。"
        "你正在處理的文件主要是台灣工程承攬契約、里程碑付款契約、RFP 與修訂版本文件。"
        "回答時要像合約分析師，而不是一般摘要器。"
        "你必須先判斷文件性質：正式契約、RFP、施工說明書、技術規格書、招標需求文件、修訂版本文件。"
        "如果文件屬於 RFP、施工說明書、技術規格書或其他非正式契約文件，就只回答文件中實際存在的需求、規格、程序與責任，不得自行補出正式契約常見但未出現的商務或法律條款。"
        "若文件未明確規定不可抗力、調價、轉包/分包、終止/解除、違約金、付款門檻或驗收標準，就必須直接回答文件未明確規定或證據不足。"
        "除非使用者明確要求一般法律分析，否則不得引入民法、情勢變更、誠信原則、法院可能見解、協商策略、訴訟或仲裁建議。"
        "對於工程承攬契約，應特別檢查：固定總價與不得追加、付款辦法、驗收標準、遲延罰款、暫停給付、損害賠償、契約終止與解除、不可抗力、關稅是否被排除於不可抗力、保固責任、轉包/分包限制。"
        "若問題詢問風險、可採取的行動、可否請款、保固期是否相同、或關稅是否屬不可抗力，通常必須綜合多個條款回答，不可只依賴單一條款。"
        "不要輸出 Markdown 表格；請使用條列或短段落。"
        "不要輸出 Markdown 水平線（---），不要輸出『相關註記』、『解析說明』、『文件性質判斷』這類前言或後記。"
        "不要輸出 emoji、圖示、流程圖、ASCII 圖、區塊引言或裝飾性符號。"
        "不要輸出 <analysis>、<think>、Thought、Analysis、Reasoning、Draft、內部分析、思考過程、推理過程、草稿、檢查清單或任何自我對話。"
        "回答應簡短直接；若證據不足，就明確寫『文件未明確規定』或『證據不足』後停止，不要再延伸一般性說明。"
        "若使用者以中文提問，必須只用繁體中文作答，不可混用簡體中文。"
        "輸出格式必須穩定、簡潔、可解析，只使用簡單標題與單層條列。"
        "最終回答必須跟隨使用者問題的主要語言；中文問題用繁體中文回答，英文問題用英文回答。"
    )
    user_prompt = (
        f"【合約結構化資料】\n{structured_context}\n\n"
        f"【檢索證據】\n{evidence}\n\n"
        f"【回答要求】\n{answer_instructions}\n\n"
        f"【問題】\n{query}\n\n【回答】"
    )
    messages = [{"role": "system", "content": system_prompt}]
    if persist_chat and chat_session is not None:
        messages.extend(history_to_messages(load_history(session, chat_session.chat_session_id)))
    messages.append({"role": "user", "content": user_prompt})
    llm_result = query_local_messages_detailed(
        messages,
        timeout=60.0,
        model_name=settings.local_query_model_name,
    )
    answer = (llm_result.get("response") or "").strip()
    if not answer:
        raise RuntimeError(f"Local model server did not return an answer: {llm_result.get('error') or 'empty_response'}")

    wiki_path = None
    if persist_chat and chat_session is not None:
        human_row = append_message(session, chat_session.chat_session_id, "human", query)
        ai_row = append_message(session, chat_session.chat_session_id, "ai", answer)
        if persist_to_wiki:
            wiki_path = append_query_note(
                session=session,
                chat_session_id=chat_session.chat_session_id,
                human_message_id=human_row.id,
                ai_message_id=ai_row.id,
                contract_id=contract_id,
                query=query,
                answer=answer,
                citations=citations,
                answer_method="openai_compatible_chat",
                retrieval_mode=retrieval_mode_value,
            )
        else:
            record_query_result(
                session=session,
                chat_session_id=chat_session.chat_session_id,
                human_message_id=human_row.id,
                ai_message_id=ai_row.id,
                contract_id=contract_id,
                query=query,
                answer=answer,
                citations=citations,
                wiki_path="",
                answer_method="openai_compatible_chat",
                retrieval_mode_value=retrieval_mode_value,
            )
    return {
        "chat_session_id": chat_session.chat_session_id if chat_session is not None else None,
        "answer": answer,
        "citations": citations,
        "answer_method": "openai_compatible_chat",
        "retrieval_mode": retrieval_mode_value,
        "model_name": settings.local_query_model_name,
        "reranker_model_name": retrieval.get("reranker_model_name"),
        "wiki_path": wiki_path,
    }
