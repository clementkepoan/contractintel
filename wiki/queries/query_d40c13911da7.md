---
kind: query
title: summarize all of the contracts
query_id: query_d40c13911da7
chat_session_id: chat_de469cdb25ae
updated_at: 2026-05-04 08:03 UTC
related:
  - contracts/01xx專案.md
  - contracts/03xx專案.md
  - sources/01xx專案__v1.md
  - sources/03xx專案__v1.md
tags:
  - query
  - hybrid_qdrant
---

# summarize all of the contracts

- 聊天工作階段：`chat_de469cdb25ae`
- 回答方式：`openai_compatible_chat`
- 檢索模式：`hybrid_qdrant`

## 回答
## Conclusion  
The contracts cover multiple projects with varying payment structures and scopes, including a fixed lump sum for some, and milestone-based payments for others. The file labeled "施工說明書" is not a binding contract but a technical specification document.

## 主要重點  
- Project 05XX has 4 payment milestones under a fixed total price of 16,695,000 TWD (evidence from contract file 05XX專案.docx).  
- Project 04XX has 5 payment milestones for a total of 32,285,563 TWD, with a warning indicating 6 proposed payment periods but only 5 extracted (evidence from contract file 04XX專案.docx).  
- Project 02XX includes 3 payment milestones for a total of 23,830,643 TWD (evidence from contract file 02XX專案.docx).  
- Project 01XX and 03XX lack specified total amounts and milestone details; both are identified as pre-bidding or technical specification documents (evidence[S2] for 03XX專案.doc, evidence[S1] for 01XX專案.docx).  
- All projects require construction to follow the bidding schedule, technical drawings, and coordination with civil and MEP contractors (delivery and acceptance, evidence[C9] and [S3]).  

## 條款依據  
- 里程碑與付款結構（證據[S1]）  
- 合約目的：03XX專案為施工說明書，屬技術文件（證據[S2]）  
- 施工內容：須依投標標價清單、說明書及機電圖說施工（證據[C5][C4]）  
- 預定竣工日期與開工日未明示，僅提及施工前需擬定施工計劃書（證據[C3][C1][S3]）

## 證據
- `03XX專案.doc` · 區塊 `structured::wiki_contract_summary::002` · 頁面約 0 · 里程碑與付款結構 - 未抽取到里程碑付款表。
- `03XX專案.doc` · 區塊 `structured::wiki_contract_summary::001` · 頁面約 0 · 快速總覽 - 合約目的：`03XX專案.doc` 是 `施工說明書` 目前採用的 `施工說明書` 來源。 - 範圍脈絡：依投標標價清單之內容、說明書及機電圖說施工 - 商務結構：`lump sum` / 付款模式 `分期付款` / 目前金額 N/A TWD。 - 目前里程碑數量：0。
- `03XX專案.doc` · 區塊 `structured::wiki_contract_summary::003` · 頁面約 0 · 交付與驗收 - 合約層級驗收注意事項：上述家庭能源管理系統功能，廠商應負責整合至中央監控系統並完成測試 - 合約層級驗收注意事項：設備安裝與測試應遵從本工程委託之監造單位指示，並配合土建及機電工程承攬廠商之工程進度，並於完工時依數量及功能完成連動測試 - 合約層級驗收注意事項：承商應於施工前擬定施工計劃書圖，供業主及監造單位審核確認後，方可進行施工
- `03XX專案.doc` · 區塊 `requirement::007:0038` · 頁面約 3 · 以上未盡事宜，以發包圖說、標單、規範內容及業主或監造單位說明為準。
- `03XX專案.doc` · 區塊 `requirement::003:0006` · 頁面約 1 · 施工內容：依投標標價清單之內容、說明書及機電圖說施工。
- `01XX專案.docx` · 區塊 `requirement::010:0050` · 頁面約 4 · 資源預約系統須整合AD帳號權限管理
- `01XX專案.docx` · 區塊 `requirement::011:0052` · 頁面約 4 · 資源管理系統提供Restful Api，可透過api進行資源預約功能
- `03XX專案.doc` · 區塊 `section::002` · 頁面約 1 · 預定開工日：
