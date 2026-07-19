# Metronome Support Intelligence

## LLMs.txt Parser

Parses the local `llms.txt` documentation index into structured JSON and CSV.

## Documentation Synchronizer

Downloads all articles discovered by the parser, stores raw Markdown content and metadata in a local SQLite database, versions every change, and tracks sync runs.

### Project structure

```
metronome-support-intelligence/
├── data/
│   ├── llms.txt                              # Source documentation index (224 lines)
│   ├── metronome_docs.db                     # SQLite database (gitignored)
│   └── parsed/
│       ├── documentation_index.json          # Structured JSON output (parser → synchronizer input)
│       └── documentation_index.csv           # Flat CSV for inspection
│
├── src/
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py                     # SQLite connection factory (WAL, FK, row_factory)
│   │   ├── schema.py                         # CREATE TABLE statements for pages, versions, sync_runs
│   │   └── repository.py                     # Data access: upsert pages, create versions, track runs
│   │
│   └── documentation/
│       ├── __init__.py
│       ├── models.py                         # Dataclasses: DocumentationEntry, ParseError, ParseResult,
│       │                                        DocumentationIndex, DownloadResult, SyncSummary
│       ├── metadata.py                       # URL validation, document-type mapping, slug/category derivation
│       ├── llms_parser.py                   # Core parser: regex line matching, deduplication, error collection
│       ├── index_loader.py                   # Loads & validates data/parsed/documentation_index.json
│       ├── downloader.py                     # Async HTTP downloader with retry (3×, exponential backoff)
│       ├── hashing.py                        # SHA-256 content hashing
│       └── synchronizer.py                   # Orchestrates: load → download → hash → store → mark missing
│
├── scripts/
│   ├── parse_llms.py                         # CLI: parse llms.txt → JSON + CSV
│   └── sync_documentation.py                 # CLI: sync articles into SQLite
│
├── tests/
│   ├── __init__.py
│   ├── test_llms_parser.py                   # 33 parser tests
│   └── test_documentation_sync.py            # 33 sync tests
│
└── README.md                                 # This file
```

### What each module does

#### Phase 1 — Parser

| Module | Responsibility |
|--------|---------------|
| `models.py` | Defines `DocumentationEntry` (all 10 fields), `ParseError` (line, raw, reason), and `ParseResult` (entries list, errors list, duplicate/ignored counts). |
| `metadata.py` | Validates URLs (`https` + `docs.metronome.com` + `.md` path), maps URL first-segments to document types (`api-reference` → `api_reference`, `guides` → `guide`, `integrations` → `guide`), derives `category`, `subcategory`, `slug`, and `file_name` from URL path segments. |
| `llms_parser.py` | Reads the file line-by-line, matches `- [Title](URL): Description` via regex, delegates to `metadata.py` for validation and derivation, deduplicates by normalized URL, records malformed or non-valid entries as parse errors, and silently skips headings/blank lines/prose. |
| `parse_llms.py` | Accepts `--input`, `--output`, `--csv`, `--no-csv` arguments. Resolves paths relative to the project root. Calls `parse_llms_file()`, serialises results to JSON and CSV, prints a summary, and exits non-zero only on fatal errors (missing input, unwritable output). |

#### Phase 2 — Synchronizer

| Module | Responsibility |
|--------|---------------|
| `models.py` (extended) | Adds `DocumentationIndex`, `DownloadResult`, and `SyncSummary` dataclasses. |
| `connection.py` | Creates a `sqlite3.Connection` with foreign-key enforcement, WAL journal mode, and `Row` factory. |
| `schema.py` | Defines three tables: `documentation_pages` (one row per URL), `documentation_versions` (immutable content snapshots), `documentation_sync_runs` (sync-run audit trail). |
| `repository.py` | All database operations — schema init, sync-run lifecycle, atomic page+version creation, unchanged/changed/failed handling, missing-page marking, and reactivation. |
| `index_loader.py` | Loads `data/parsed/documentation_index.json`, validates the `entries` list structure, converts each entry to a `DocumentationEntry`, and skips invalid records individually. |
| `downloader.py` | Async download via `httpx.AsyncClient` with `asyncio.Semaphore` concurrency control. Retries HTTP 429 and 5xx (3× with exponential backoff). Does not retry 4xx. User-agent: `MetronomeSupportIntelligence/0.1`. |
| `hashing.py` | `calculate_content_hash(content: str) → str` — SHA-256 hex digest of the full Markdown body. |
| `synchronizer.py` | Orchestrates: loads index → inits schema → starts sync run → downloads all → hashes → creates or updates pages/versions → marks missing → completes sync run → returns `SyncSummary`. |
| `sync_documentation.py` | CLI with `--index`, `--database`, `--concurrency`. Prints a summary and exits non-zero only on fatal errors (missing index, inaccessible DB). |

### Where to place `llms.txt`

Place the `llms.txt` file at `data/llms.txt` (the default location). The project ships with the real Metronome documentation index already at this path.

### How to run the parser

```bash
python scripts/parse_llms.py
```

With custom paths:

```bash
python scripts/parse_llms.py \
  --input data/llms.txt \
  --output data/parsed/documentation_index.json
```

Skip CSV generation:

```bash
python scripts/parse_llms.py --no-csv
```

### How to run the synchronizer

```bash
python scripts/sync_documentation.py
```

With custom paths:

```bash
python scripts/sync_documentation.py \
  --index data/parsed/documentation_index.json \
  --database data/metronome_docs.db \
  --concurrency 5
```

### Example parser output

```
Metronome documentation index parsed

Source: data\llms.txt
Valid articles: 208
Duplicate URLs: 0
Ignored lines: 4
Parse errors: 6

JSON output:
  D:\Projects\metronome-support-intelligence\data\parsed\documentation_index.json
CSV output:
  D:\Projects\metronome-support-intelligence\data\parsed\documentation_index.csv
```

### Example synchronizer output (first run)

```
Metronome documentation synchronization completed

Index:
  D:\Projects\metronome-support-intelligence\data\parsed\documentation_index.json

Database:
  D:\Projects\metronome-support-intelligence\data\metronome_docs.db

Discovered articles: 208
Fetched successfully: 208
New articles: 208
Changed articles: 0
Unchanged articles: 0
Missing from index: 0
Failed downloads: 0
```

### Example synchronizer output (second run, no changes)

```
Metronome documentation synchronization completed

Discovered articles: 208
Fetched successfully: 208
New articles: 0
Changed articles: 0
Unchanged articles: 208
Missing from index: 0
Failed downloads: 0
```

### Parse results from the supplied `llms.txt`

| Metric | Count | Notes |
|--------|-------|-------|
| **Valid articles** | **208** | All valid `docs.metronome.com/*.md` entries |
| Duplicate URLs | 0 | No repeated article URLs in the index |
| Ignored lines | 4 | Headings: `# Metronome`, `## Docs`, `## OpenAPI Specs`, `## Optional` |
| Parse errors | 6 | `openapi.json`, `openapi.plans.json` (not `.md`), `status.metronome.com` ×2, `metronome.com/blog` ×2 (not `docs.metronome.com`) |

### Synchronization results

| Metric | Count |
|--------|-------|
| Pages stored | 208 (all version 1, all status `active`) |
| Versions created | 208 (one per page) |
| Articles with code fences | 175 |
| Articles with tables | 27 |
| Articles referencing OpenAPI | 5 |
| Content size range | ~2 KB – ~25 KB |
| Second identical run | 208 unchanged, 0 new versions |

### Extracted fields

| Field | Description |
|-------|-------------|
| `title` | Article title from the Markdown link |
| `url` | Full URL to the `.md` article on `docs.metronome.com` |
| `description` | Optional description after the colon separator (empty string if none) |
| `document_type` | Derived from the first URL path segment (`api_reference`, `guide`, or original value for unknown types) |
| `category` | Second path segment (e.g., `alerts`, `contracts`); `null` for top-level entries |
| `subcategory` | Third path segment when the URL is nested (e.g., `get-contracts`); `null` otherwise |
| `slug` | Article slug from the filename without `.md` extension |
| `file_name` | Original filename with `.md` extension |
| `source_line_number` | 1-based line number in the source `llms.txt` file |
| `raw_line` | The original unprocessed line (preserved verbatim) |

### Database schema

Three tables in `data/metronome_docs.db`:

**`documentation_pages`** — one row per article URL:
- `id`, `source_url` (unique), `title`, `index_description`, `document_type`, `category`, `subcategory`, `slug`, `file_name`
- `current_content_hash`, `current_version`, `status` (`active`, `fetch_failed`, `missing_from_index`)
- `first_seen_at`, `last_seen_at`, `last_checked_at`, `last_changed_at`

**`documentation_versions`** — immutable content snapshots:
- `id`, `page_id` (FK → documentation_pages CASCADE), `version_number`, `content_hash`, `raw_markdown`, `http_status`, `final_url`, `fetched_at`
- Unique constraint on `(page_id, version_number)`

**`documentation_sync_runs`** — audit trail:
- `id`, `started_at`, `completed_at`, `source_index_path`, `source_index_hash`
- `discovered_count`, `fetched_count`, `new_count`, `changed_count`, `unchanged_count`, `failed_count`, `missing_count`
- `status` (`running`, `completed`, `completed_with_errors`, `failed`), `errors_json`

### Important notes

- The parser only parses the `llms.txt` index file. It does **not** fetch or download the linked Markdown articles.
- The synchronizer reads the parser's JSON output, downloads every article, and stores raw Markdown in SQLite.
- Article versions are **immutable**. New versions are created only when content changes (hash differs).
- Previous versions are preserved and never deleted.
- The database is local and excluded from Git (`.gitignore`).
- Content parsing, embeddings, AI, and frontend work remain intentionally excluded from these phases.

### How to run parser tests

```bash
python -m pytest tests/test_llms_parser.py -v
```

### How to run synchronizer tests

```bash
python -m pytest tests/test_documentation_sync.py -v
```

### Run all tests

```bash
python -m pytest tests/ -v
```

## Adaptive Investigation Checklists

Phase 4.4 adds deterministic, evidence-aware investigation checklists for support tickets. The analyzer selects concepts based on missing or unverified evidence, marks already-satisfied concepts as complete, suppresses irrelevant work, and merges overlapping concepts into concise checklist steps that retain all underlying concept codes.

Current registered concept count is reported programmatically:

```text
Total concepts: 45
generic: 11
contracts: 14
usage: 15
customers: 5
```

Concept selection states are:

```text
selected
already_complete
suppressed
not_applicable
```

Suppression prevents the checklist from asking for evidence already present in the ticket, such as a structured request body, response status/body, expected behavior, actual behavior, valid `starting_at`, or authentication checks after an application-level response. Scenario gates keep contract uniqueness, contract validation, usage accepted-but-not-billed, duplicate transaction, customer, authentication, unknown-endpoint, and vague-ticket workflows focused.

Overlapping concepts merge by groups such as `request_capture`, `endpoint_verification`, `minimal_reproduction`, `final_state`, `engineering_escalation`, `customer_reference`, and `pricing_reference`. Each merged checklist step stores `concept_codes`, so evaluation no longer infers coverage from action prose.

Documentation retrieval is evaluated by investigation purpose:

```text
operation
error_behavior
validation
verification
configuration
final_state
```

The evaluator reports primary-source Top-1 accuracy, purpose-source recall, observation-code coverage, concept coverage, checklist precision, ordering accuracy, blocking-step coverage, escalation placement, already-complete-step rate, redundant-step rate, secret redaction, and unsupported-case abstention.

Current ticket evaluation data:

```text
Tuning cases: 22
Holdout cases: 4
Total cases: 26
```

Quality thresholds remain deterministic gates before any LLM functionality is enabled:

```text
Signal extraction >= 95%
Primary-source accuracy >= 95%
Purpose-source recall >= 95%
Observation coverage >= 90%
Concept coverage >= 85%
Checklist precision >= 85%
Checklist ordering >= 90%
Incidental-source exclusion >= 90%
Already-complete-step rate <= 5%
Redundant-step rate = 0%
Secret redaction = 100%
Unsupported-case abstention = 100%
```

Useful commands:

```bash
python scripts/validate_concept_registry.py
```

```bash
python scripts/analyze_ticket.py \
  --input data/examples/contract_409.json \
  --explain-concepts
```

```bash
python scripts/evaluate_tickets.py --split all
```

```bash
python -m pytest tests/ -v
```

## Confirmed Resolutions and Feedback Loop

Phase 5 adds a human-controlled resolution workflow. Ticket investigations still produce observations, checklists, and hypotheses, but hypotheses are not root causes. A root cause becomes confirmed only when an engineer submits a resolution with verification evidence and a stable `root_cause_code`.

Confirmed resolutions are linked back to the original ticket analysis. The system compares the confirmed root cause with earlier hypotheses and stores outcomes such as `confirmed`, `partially_confirmed`, `rejected`, or `not_evaluated` without rewriting the historical hypotheses.

Each confirmed outcome can generate a reusable regression-case candidate. The candidate preserves structured scenario inputs and expected behavior while keeping secrets out of persisted artifacts. Documentation, product, API, validation, observability, and support-process gaps are classified with stable gap codes and turned into draft feedback proposals.

Feedback proposals require human review. Reviewers can approve, reject, request changes, mark work planned, mark work implemented, verify it, and close it. The workflow tracks implementation and verification status but does not publish documentation, create product tickets, or modify code automatically.

Example commands:

```bash
python scripts/resolve_ticket.py \
  --input data/examples/resolutions/usage_property_mismatch.json \
  --show-comparison \
  --show-feedback
```

```bash
python scripts/inspect_resolution.py --ticket-id 4
```

```bash
python scripts/list_feedback.py --status needs_review
```

```bash
python scripts/review_feedback.py \
  --feedback-id 3 \
  --decision approve \
  --reviewer "Andrian"
```

```bash
python scripts/evaluate_resolutions.py
```

Resolution evaluation data:

```text
Tuning cases: 11
Holdout cases: 3
Total cases: 14
```

Resolution quality gates:

```text
Resolution validation >= 95%
Root-cause accuracy >= 95%
Hypothesis outcomes >= 90%
Verification completeness >= 90%
Regression-case accuracy >= 95%
Gap classification >= 85%
Secret redaction = 100%
Invalid-resolution rejection = 100%
Feedback transitions = 100%
```

Current complete suite:

```text
262 tests passing
```

## Grounded Gemini Drafting

Phase 6 adds a grounded communication layer that converts already-verified structured evidence into polished drafts.

**Architecture:**
- **DeepSeek/Cline** was used as the coding agent
- **Gemini** is the application drafting provider
- Gemini receives only **sanitized grounding packages**
- The **deterministic pipeline remains the source of truth**

**Key guarantees:**
- Every claim references stable fact codes
- Every source reference is validated
- Hypotheses cannot be silently converted into causes
- Customer resolutions require confirmed resolutions
- Drafts require human review
- Automated tests use the mock provider (no live API calls)
- The live Gemini provider is intended for the short interview demonstration

### Setup

```bash
copy .env.example .env
```

Then edit `.env`:

```env
DRAFTING_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.0-flash
```

For development without live API calls, set `DRAFTING_PROVIDER=mock`.

### Supported draft types

| Code | Audience | Description |
|------|----------|-------------|
| `customer_update` | customer | Status update during investigation |
| `customer_resolution` | customer | Final resolution with confirmed root cause |
| `engineering_escalation` | engineering | Detailed technical escalation |
| `internal_case_summary` | internal | Internal case documentation |
| `documentation_proposal` | internal | Proposed documentation improvement |
| `product_feedback` | product | Product or observability feedback |
| `executive_summary` | executive | Leadership briefing summary |

### Commands

Generate a grounded draft:

```bash
python scripts/generate_draft.py \
  --ticket-id 4 \
  --type engineering_escalation \
  --show-grounding \
  --show-validation
```

Generate a customer resolution:

```bash
python scripts/generate_draft.py \
  --ticket-id 4 \
  --resolution-id 2 \
  --type customer_resolution
```

List all drafts:

```bash
python scripts/list_drafts.py --status needs_review
```

Inspect a specific draft:

```bash
python scripts/inspect_draft.py --draft-id 6
```

Approve or reject a draft:

```bash
python scripts/review_draft.py \
  --draft-id 6 \
  --decision approve \
  --reviewer "Andrian"
```

Run the drafting evaluation:

```bash
python scripts/evaluate_drafting.py --split all
```

Seed demo scenarios:

```bash
python scripts/seed_demo.py
```

Reset demo data (preserves documentation):

```bash
python scripts/reset_demo.py
```

### Drafting evaluation

```text
Tuning cases: 12
Holdout cases: 6
Total cases: 18
```

Quality thresholds:

```text
Structured-output validity = 100%
Fact-reference validity = 100%
Claim-map validity = 100%
Source-reference validity = 100%
Unsupported-claim rejection = 100%
Resolution-status compliance = 100%
Secret redaction = 100%
Customer-safety accuracy = 100%
Hypothesis labelling >= 95%
Required-section coverage >= 95%
Human-review transitions = 100%
```

### Gemini SDK dependency

```text
google-genai
```

The project uses the current `google-genai` SDK (not the legacy `google-generativeai`).
The provider abstraction allows swapping to Vertex AI or another provider without changing the support workflow.

### Automated tests

All automated tests use the deterministic mock provider and mocked Gemini client.
No test calls the live Gemini API.

### Manual smoke test

```bash
python scripts/smoke_test_gemini.py
```

This requires `GEMINI_API_KEY` and `GEMINI_MODEL`. It is a pre-interview check, not part of the test suite.

### Interactive demo

```bash
python scripts/seed_demo.py
python scripts/run_demo.py
```

Opens a local web interface at `http://127.0.0.1:8501` with overview, investigation, and drafting panels.

### CLI generation

```bash
python scripts/generate_draft.py \
  --ticket-id 1 \
  --type customer_update
```

CLI generation and the interactive demo are different features.

### Safety model

```
Deterministic pipeline decides facts.
Gemini drafts language.
Validator checks claims.
Human approves use.
```


