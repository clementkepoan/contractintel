from backend.pipeline.extractor import extract_contract_data, zh_to_int
from backend.pipeline.ingestion import classify_document, load_document
from backend.pipeline.indexer import reciprocal_rank_fusion
from backend.pipeline.validation import validate_contract_data


def test_zh_to_int_handles_traditional_numbers() -> None:
    assert zh_to_int("參仟貳佰萬貳拾捌萬伍仟伍佰陸拾參") == 32285563


def test_extract_contract_data_returns_milestones_and_validation() -> None:
    document = {
        "source_file": "sample.docx",
        "doc_category": "contract",
        "paragraphs": [
            {"paragraph_index": 0, "page_estimate": 1, "block_id": "b0", "text": "XX專案工程契約"},
            {"paragraph_index": 1, "page_estimate": 1, "block_id": "b1", "text": "契約總價為新臺幣 1,000,000 元"},
            {"paragraph_index": 2, "page_estimate": 1, "block_id": "b2", "text": "第一期：契約簽訂後給付 500,000 元，佔總金額 50%"},
            {"paragraph_index": 3, "page_estimate": 1, "block_id": "b3", "text": "1. 提交施工計畫書"},
            {"paragraph_index": 4, "page_estimate": 1, "block_id": "b4", "text": "第二期：驗收合格後給付 500,000 元，佔總金額 50%"},
        ],
    }
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert extracted["contract_name"] == "XX專案工程契約"
    assert extracted["total_amount"] == 1000000
    assert len(extracted["milestones"]) == 2
    assert extracted["milestones"][0]["amount"] == 500000
    assert extracted["milestones"][0]["citations"]
    assert not any(item["code"] == "missing_total_amount" for item in warnings)


def test_real_sample_01_is_treated_as_reference_document() -> None:
    document = load_document("Database/01XX專案.docx")
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert extracted["doc_category"] == "rfp"
    assert extracted["total_amount"] is None
    assert len(extracted["milestones"]) == 0
    assert any(item["code"] == "missing_total_amount" for item in warnings)


def test_real_sample_02_stays_contract_even_with_construction_wording() -> None:
    document = load_document("Database/02XX專案.docx")
    assert document["doc_category"] == "contract"


def test_real_sample_04_detects_amount_mismatch() -> None:
    document = load_document("Database/04XX專案.docx")
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert extracted["total_amount"] == 32285563
    assert len(extracted["milestones"]) >= 5
    assert any(item["code"] == "installment_count_mismatch" for item in warnings)
    assert any(item["code"] == "percentage_amount_inconsistency" for item in warnings)


def test_real_sample_05_extracts_split_amount_lines() -> None:
    document = load_document("Database/05XX專案.docx")
    extracted = extract_contract_data(document)
    validate_contract_data(extracted)
    assert len(extracted["milestones"]) == 4
    assert extracted["milestones"][0]["amount"] == 3339000
    assert extracted["milestones"][1]["amount"] == 5008500


def test_real_sample_06_links_work_items_and_flags_amount_errors() -> None:
    document = load_document("Database/06XX專案.docx")
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert len(extracted["milestones"]) == 4
    assert extracted["milestones"][0]["work_items"] == ["完成施工計畫書提交", "完成材料送審", "完成工程保險投保"]
    assert any(item["code"] == "amount_sum_mismatch" for item in warnings)
    assert any(item["code"] == "percentage_amount_inconsistency" and item["severity"] == "ERROR" for item in warnings)


def test_real_sample_07_percentage_only_rfp_milestones() -> None:
    document = load_document("Database/07XX專案.docx")
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert extracted["total_amount"] is None
    assert [item["percentage"] for item in extracted["milestones"]] == [25.0, 30.0, 20.0, 25.0]
    assert sum(item["percentage"] for item in extracted["milestones"]) == 100.0
    assert any(item["code"] == "missing_total_amount" and item["severity"] == "WARNING" for item in warnings)


def test_real_sample_08_extracts_multi_currency_and_alias_milestones() -> None:
    document = load_document("Database/08XX專案.docx")
    extracted = extract_contract_data(document)
    validate_contract_data(extracted)
    assert extracted["total_amount"] == 12670000
    assert extracted["currency"] == "MULTI"
    assert extracted["currency_breakdown"] == [
        {"amount": 11550000, "currency": "NTD"},
        {"amount": 35000, "currency": "USD", "rate": 32.0, "ntd_equivalent": 1120000},
    ]
    assert len(extracted["milestones"]) == 4
    assert extracted["milestones"][2]["work_items"][0] == "完成新加坡AWS節點環境建置"


def test_real_sample_09_single_payment_retention_and_checkpoints() -> None:
    document = load_document("Database/09XX專案.docx")
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert extracted["payment_type"] == "single_with_retention"
    assert [item["amount"] for item in extracted["milestones"]] == [17100000, 900000]
    assert extracted["retention"]["release_after_months"] == 24
    assert len(extracted["progress_checkpoints"]) == 4
    assert any(item["code"] == "progress_checkpoints_not_payment_milestones" for item in warnings)


def test_real_sample_10_excludes_deprecated_v1_milestones() -> None:
    document = load_document("Database/10XX專案.docx")
    extracted = extract_contract_data(document)
    warnings = validate_contract_data(extracted)
    assert extracted["total_amount"] == 23800000
    assert len(extracted["milestones"]) == 4
    assert len(extracted["superseded_milestones"]) == 3
    assert extracted["has_version_conflict"] is True
    assert any(item["code"] == "version_conflict_detected" for item in warnings)


def test_construction_instruction_is_not_reclassified_as_rfp() -> None:
    paragraphs = [
        "施工說明書",
        "施工名稱：XX專案",
        "本工程應於完工時依數量及功能完成連動測試。",
        "承包商於施工期間應注意安全防護措施。",
        "本案應依契約用電容量管理自動需量卸載。",
    ]
    assert classify_document(paragraphs) == "construction_instruction"
    document = {
        "source_file": "03XX.doc",
        "doc_category": "construction_instruction",
        "paragraphs": [
            {"paragraph_index": index, "page_estimate": 1, "block_id": f"b{index}", "text": text}
            for index, text in enumerate(paragraphs)
        ],
    }
    extracted = extract_contract_data(document)
    assert extracted["doc_category"] == "construction_instruction"
    assert extracted["total_amount"] is None
    assert extracted["milestones"] == []
    assert extracted["acceptance_requirements"]
    assert extracted["safety_requirements"]


def test_reciprocal_rank_fusion_boosts_consensus_chunks() -> None:
    fused = reciprocal_rank_fusion(
        [
            [("a", 0.9), ("b", 0.8), ("c", 0.7)],
            [("b", 0.95), ("a", 0.85), ("d", 0.6)],
        ]
    )
    assert fused["a"] > fused["c"]
    assert fused["b"] > fused["d"]
