# Agent Task: Fix Extraction Pipeline + Add Upload Loading UI

## Context
Read these files before making any changes:
- `backend/pipeline/extractor.py`
- `backend/pipeline/extractor_llm.py`
- `backend/pipeline/service.py`
- `backend/pipeline/validation.py`
- `backend/wiki/generator.py`
- The upload/ingest frontend component (find it by searching for the file upload handler)

Do not change `validation.py` logic. Do not change the database schema. Do not change the wiki markdown format.

---

## Task 1 — Extraction Path Telemetry

### What to do
Add a single structured log line at the end of every extraction attempt in `extractor.py` and `extractor_llm.py`.

### Exact log format required
```python
logger.info(
    f"[EXTRACTION] file={doc_name} | "
    f"path={'llm' if llm_succeeded else 'regex_fallback'} | "
    f"prompt_tokens={prompt_token_estimate} | "
    f"llm_ms={llm_duration_ms} | "
    f"fallback_reason={fallback_reason}"  # 'none' | 'ollama_unavailable' | 'timeout' | 'invalid_json' | 'empty_response'
)
```

### Where to add it
- In `extract_contract_data()` in `extractor.py`, after the merge step, before returning
- In `extract_contract_with_llm()` in `extractor_llm.py`, at every exit point (success, timeout, invalid JSON, unavailable)

### Fallback reason values
Use exactly these strings, no others:
- `none` — LLM ran and succeeded
- `ollama_unavailable` — could not connect to Ollama
- `timeout` — request exceeded timeout threshold
- `invalid_json` — LLM responded but JSON was unparseable or failed schema check
- `empty_response` — LLM responded but returned no usable milestone content

### Also add to the returned extraction dict
```python
result["_meta"] = {
    "extraction_path": "llm" | "regex_fallback",
    "fallback_reason": fallback_reason,
    "prompt_tokens": n,
    "llm_ms": t,
    "pipeline_revision": PIPELINE_REVISION
}
```

This must be stored in the raw JSON by `service.py` so it is inspectable later.

---

## Task 2 — Hard Line Between Regex Locator and Semantic Assembly

### What to do
In `extractor.py`, split `regex_fallback_extraction()` into two clearly named functions:

```python
def build_segment_map(paragraphs: list[dict]) -> dict:
    """
    Regex only. No semantic decisions.
    Returns: segment_map with located evidence blocks and flags only.
    Never assembles milestones. Never infers payment type.
    """

def assemble_from_segment_map(segment_map: dict, paragraphs: list[dict]) -> dict:
    """
    Deterministic assembly only.
    Reads segment_map evidence and builds the milestone structure.
    This is the only place allowed to make semantic decisions in the regex path.
    """
```

### Rules for `build_segment_map()`
It may only:
- find clause boundaries by pattern
- tag paragraph blocks with labels
- collect raw amount and percentage strings with their block_ids
- set boolean flags
- record offsets and block_ids

It may NOT:
- decide what payment type the contract is
- group milestones
- infer acceptance criteria
- construct retention objects
- interpret what a percentage means

### Rules for `assemble_from_segment_map()`
- Takes the segment map as its only semantic input
- Applies the payment type decision tree here, once, explicitly
- Constructs milestone objects here
- This function is allowed to have conditional branches for payment types

### Why
Every time a new document has a new wording variant, the fix goes into `build_segment_map()` as a new pattern — not scattered across the whole extractor. Semantic logic stays in one place and is easier to audit.

---

## Task 3 — LLM Output Schema Validation

### What to do
In `extractor_llm.py`, add a schema validation step between receiving the LLM response and passing it to `merge_llm_extraction()`.

### Required schema check function
```python
def validate_llm_response_schema(parsed: dict) -> tuple[bool, str]:
    """
    Returns (is_valid, reason).
    Checks structure only, not semantic correctness.
    """
    required_top_level = ["milestones"]
    for field in required_top_level:
        if field not in parsed:
            return False, f"missing_field:{field}"

    if not isinstance(parsed["milestones"], list):
        return False, "milestones_not_array"

    for i, m in enumerate(parsed["milestones"]):
        if not isinstance(m, dict):
            return False, f"milestone_{i}_not_object"
        if "name" not in m:
            return False, f"milestone_{i}_missing_name"
        if "amount" in m and m["amount"] is not None:
            if not isinstance(m["amount"], (int, float)):
                return False, f"milestone_{i}_amount_wrong_type"
        if "percentage" in m and m["percentage"] is not None:
            if not isinstance(m["percentage"], (int, float)):
                return False, f"milestone_{i}_percentage_wrong_type"

    return True, "ok"
```

### Where to use it
```python
parsed = parse_llm_json(raw_response)
is_valid, reason = validate_llm_response_schema(parsed)
if not is_valid:
    log_fallback(reason="invalid_json", detail=reason)
    return None  # triggers regex fallback
```

### Do not
- Accept partial LLM output and silently merge it with broken fields
- Try to repair malformed LLM JSON beyond stripping markdown fences
- Let type mismatches pass through to the merge step

---

## Task 4 — Separate `acceptance_criteria` from `payment_condition`

### What to do
In `assemble_from_segment_map()` (from Task 2), when building each milestone, extract these two fields separately.

### Extraction rules

**`payment_condition`** — the financial trigger. Look for:
```python
PAYMENT_CONDITION_SIGNALS = [
    r"給付", r"付款", r"支付", r"撥付", r"請款"
]
```
Take the sentence containing any of these signals within the milestone block.

**`acceptance_criteria`** — the work completion standard. Look for:
```python
ACCEPTANCE_SIGNALS = [
    r"驗收合格", r"驗收通過", r"經.*驗收", r"測試通過", r"完成.*測試",
    r"功能.*檢測", r"檢驗合格"
]
```
Take the sentence containing any of these signals within the milestone block.

### Rules
- If both signals appear in the same sentence, assign that sentence to `payment_condition` and set `acceptance_criteria` to the nearest preceding sentence containing a completion description
- If only payment signal found: set `acceptance_criteria = null`
- If only acceptance signal found: set `payment_condition = null`
- Never copy one field's value into the other

### Output shape
```python
{
    "payment_condition": "甲方應給付工程總價20%予乙方",
    "acceptance_criteria": "乙方完成報價單項目一至項目六之硬體設備安裝，經甲方及客戶驗收合格後"
}
```

---

## Task 5 — Bulk Reprocess Command

### What to do
Add a CLI command and an API endpoint that re-runs extraction on all already-ingested source documents.

### CLI command
```bash
python -m backend.pipeline.reprocess --all
python -m backend.pipeline.reprocess --file "06XX專案.docx"
python -m backend.pipeline.reprocess --since-revision 3
```

### API endpoint
```
POST /api/admin/reprocess
Body: {"target": "all"} | {"target": "file", "filename": "06XX專案.docx"} | {"target": "since_revision", "revision": 3}
```

### Behavior
- Re-reads the original source file from the stored upload path
- Runs the full current extraction pipeline on it
- Overwrites the stored raw JSON and milestone rows
- Triggers wiki regeneration for affected contracts
- Logs each file: `[REPROCESS] file=X | old_revision=N | new_revision=M | path=llm|regex`
- Does NOT delete the source file or contract record
- Returns a summary: `{"processed": N, "failed": [], "skipped": []}`

### Skip condition
Skip a file if source hash + current pipeline revision already match stored values (already up to date).

---

## Task 6 — Upload Progress Bar and Skeleton Loading (Frontend)

### Find the upload component first
Search the frontend codebase for the file upload handler. It will contain either a `FormData` POST or a fetch/axios call to the ingest endpoint. Work from that file.

### What to add

#### 6A — Upload progress bar
Replace the current upload fetch call with one that tracks `XMLHttpRequest` upload progress:

```javascript
function uploadWithProgress(file, onProgress) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append("file", file);

        xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                onProgress({ stage: "uploading", percent: pct });
            }
        });

        xhr.addEventListener("load", () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                onProgress({ stage: "processing", percent: 100 });
                resolve(JSON.parse(xhr.responseText));
            } else {
                reject(new Error(`Upload failed: ${xhr.status}`));
            }
        });

        xhr.addEventListener("error", () => reject(new Error("Network error")));
        xhr.open("POST", "/api/ingest");
        xhr.send(formData);
    });
}
```

#### 6B — Three-stage UI state machine
The upload UI must show three distinct stages:

```
Stage 1: uploading   → show progress bar with percentage
Stage 2: processing  → show skeleton cards (server is extracting)
Stage 3: done        → show result or error
```

Manage this with a state object:
```javascript
const [uploadState, setUploadState] = useState({
    stage: "idle",        // "idle" | "uploading" | "processing" | "done" | "error"
    percent: 0,
    filename: null,
    error: null
});
```

#### 6C — Progress bar component
If using React:
```jsx
function UploadProgressBar({ percent, stage }) {
    if (stage === "idle") return null;

    return (
        <div className="upload-progress">
            <div className="upload-progress__label">
                {stage === "uploading" && `上傳中... ${percent}%`}
                {stage === "processing" && "解析文件中..."}
                {stage === "done" && "完成"}
            </div>
            <div className="upload-progress__track">
                <div
                    className="upload-progress__fill"
                    style={{ width: stage === "processing" ? "100%" : `${percent}%` }}
                />
            </div>
        </div>
    );
}
```

CSS for the processing indeterminate state:
```css
.upload-progress__track {
    height: 6px;
    background: #e5e7eb;
    border-radius: 3px;
    overflow: hidden;
}
.upload-progress__fill {
    height: 100%;
    background: #3b82f6;
    border-radius: 3px;
    transition: width 0.3s ease;
}
/* indeterminate animation when processing */
.upload-progress--processing .upload-progress__fill {
    width: 100% !important;
    animation: indeterminate 1.5s ease-in-out infinite;
    background: linear-gradient(90deg, #3b82f6 0%, #93c5fd 50%, #3b82f6 100%);
    background-size: 200% 100%;
}
@keyframes indeterminate {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
```

#### 6D — Skeleton loading cards
Show skeleton cards while `stage === "processing"`:

```jsx
function SkeletonCard() {
    return (
        <div className="skeleton-card">
            <div className="skeleton-line skeleton-line--title" />
            <div className="skeleton-line skeleton-line--short" />
            <div className="skeleton-line" />
            <div className="skeleton-line skeleton-line--short" />
        </div>
    );
}

function SkeletonMilestoneList() {
    return (
        <div className="skeleton-list">
            {[1, 2, 3].map(i => <SkeletonCard key={i} />)}
        </div>
    );
}
```

CSS:
```css
.skeleton-card {
    padding: 16px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-bottom: 12px;
}
.skeleton-line {
    height: 14px;
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    border-radius: 4px;
    margin-bottom: 10px;
    animation: shimmer 1.5s infinite;
}
.skeleton-line--title  { width: 60%; height: 18px; }
.skeleton-line--short  { width: 35%; }
@keyframes shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
```

#### 6E — Wire it all together
```jsx
async function handleFileUpload(file) {
    setUploadState({ stage: "uploading", percent: 0, filename: file.name, error: null });

    try {
        const result = await uploadWithProgress(file, ({ stage, percent }) => {
            setUploadState(prev => ({ ...prev, stage, percent }));
        });

        // After upload completes, server is now processing
        setUploadState(prev => ({ ...prev, stage: "processing" }));

        // Poll or await the ingest completion response
        // If your ingest endpoint is synchronous (blocks until done), result is ready here
        // If async, poll GET /api/ingest/status/{job_id} until done

        setUploadState(prev => ({ ...prev, stage: "done" }));
        onUploadComplete(result);

    } catch (err) {
        setUploadState(prev => ({ ...prev, stage: "error", error: err.message }));
    }
}
```

---

## Acceptance Criteria

### Backend
- [ ] Every extraction logs `[EXTRACTION]` line with path, tokens, ms, fallback_reason
- [ ] `_meta` block present in all stored raw JSON after re-ingest
- [ ] `build_segment_map()` contains zero semantic decisions — only patterns and flags
- [ ] `assemble_from_segment_map()` is the single location for payment type and milestone grouping logic
- [ ] `validate_llm_response_schema()` exists and is called before merge
- [ ] Invalid LLM JSON logs `invalid_json` reason and falls back cleanly
- [ ] `payment_condition` and `acceptance_criteria` are never identical strings in the same milestone unless the source clause genuinely contains both in one sentence
- [ ] `python -m backend.pipeline.reprocess --all` runs without error and logs per-file results
- [ ] `POST /api/admin/reprocess` returns `{"processed": N, "failed": [], "skipped": []}`

### Frontend
- [ ] File upload shows numeric percentage progress bar during upload
- [ ] After upload completes, UI switches to animated indeterminate bar + skeleton cards
- [ ] Skeleton cards disappear when extraction result is ready
- [ ] Error state is shown clearly if upload or extraction fails
- [ ] No full page reload at any stage

### Do Not
- Change `validation.py` logic
- Change the database schema
- Change the wiki markdown format
- Add any cloud API calls
- Remove the regex fallback path