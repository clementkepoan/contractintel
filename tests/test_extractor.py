from backend.pipeline.extractor import extract_contract_data, zh_to_int
from backend.pipeline.ingestion import load_document
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


def test_reciprocal_rank_fusion_boosts_consensus_chunks() -> None:
    fused = reciprocal_rank_fusion(
        [
            [("a", 0.9), ("b", 0.8), ("c", 0.7)],
            [("b", 0.95), ("a", 0.85), ("d", 0.6)],
        ]
    )
    assert fused["a"] > fused["c"]
    assert fused["b"] > fused["d"]
