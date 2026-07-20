# Metronome Support Intelligence

## Overview

Metronome Support Intelligence is a controlled technical-investigation system that combines deterministic evidence extraction, versioned documentation retrieval, adaptive investigation planning, grounded language-model drafting, claim-level validation, and human review.

It is a multi-phase engineering project that was built deliberately — documentation ingestion, parsing and search first, then deterministic ticket analysis, then resolution and feedback loops, then grounded drafting, and finally a server-rendered Flask interface deployed on Vercel using SQLite.

[A conventional RAG chatbot searches documents and asks an LLM to write an answer. This project first constructs a full support investigation.]

The system separates what is **observed**, what is **missing**, what is only **suspected**, and what is **human-confirmed**. Gemini drafts communication only after the deterministic pipeline has built a closed grounding package. Every generated claim is traceable to fact codes and validated sources. Answers require human approval before use.

**Repository:** https://github.com/AndrianBarbulat/metronome-support-intelligence

**Live deployment:** Vercel (auto-deploys from `master`)

**Key metrics (live from database):**

- 208 indexed documentation articles
- 1,461 searchable chunks (1,268 sections, 327 code blocks, 120 tables, 104 OpenAPI blocks)
- 45 stable investigation concepts
- 341 passing tests (0 failures, 0 skipped)
- 26 ticket investigation cases (22 tuning, 4 holdout)
- 14 confirmed resolution cases (11 tuning, 3 holdout)
- 18 drafting cases (12 tuning, 6 holdout)

---

## Project Architecture

```
app.py                          # Flask application — 12 routes, server-rendered HTML, SQLite-backed
src/
  assistant/                    # End-to-end orchestration (answer_metronome_question)
  database/                     # SQLite connection, schema (19 DB objects), repository (41 methods), adapter
  documentation/                # llms.txt parsing, downloader, content hashing, synchronizer, parser, chunker, search, reranker
  drafting/                     # Grounding-package factory, Gemini/mock providers, claim checker, validator, section validator
  support/                      # Concept registry, signal extraction, observation builder, checklist builder, resolution models, sanitizer
  feedback/                     # Feedback models (documentation-gap, product, observability)
  presentation/                 # /how-it-works engineering case-study page
scripts/                        # 20 operational CLI tools
tests/                          # 30+ test files
data/                           # llms.txt, prebuilt SQLite database, evaluation cases, examples
```

### Web routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Assistant workspace (dashboard, ask form, recent cases) |
| `/ask` | POST | Analyse a question and generate grounded answer |
| `/cases` | GET | Saved case history with search |
| `/cases/<id>` | GET | Single case view (investigation, sources, answer, review) |
| `/drafts/<id>/review` | POST | Review a generated draft (approve/reject/use) |
| `/documentation` | GET | Documentation explorer (search, articles, chunks, OpenAPI) |
| `/documentation/articles/<id>` | GET | Article detail with parsed hierarchy and chunks |
| `/how-it-works` | GET | Engineering case-study page |
| `/testing` | GET | Testing evidence and evaluation metrics |

### Operational scripts (20 tools)

**Documentation ingestion:** `parse_llms.py`, `sync_documentation.py`, `process_documentation.py`

**Ticket investigation:** `analyze_ticket.py`, `evaluate_tickets.py`

**Drafting & communication:** `generate_draft.py`, `evaluate_drafting.py`, `review_draft.py`, `inspect_draft.py`, `list_drafts.py`, `ask_metronome.py`

**Resolution & feedback:** `resolve_ticket.py`, `evaluate_resolutions.py`, `list_feedback.py`, `review_feedback.py`

**Search & retrieval:** `search_documentation.py`, `evaluate_search.py`

**Development & deployment:** `seed_demo.py`, `reset_demo.py`, `run_demo.py`, `smoke_test_gemini.py`

---

## How to run locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the Flask server (default port 8501)
python scripts/run_demo.py

# Or run app.py directly
python app.py --port 8501
```

Visit `http://127.0.0.1:8501`.

To run the full test suite:

```bash
python -m pytest tests/ -v
```

---

## Setup

```bash
copy .env.example .env
```

Edit `.env`:

```env
DRAFTING_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.0-flash
```

For development without live API calls, set `DRAFTING_PROVIDER=mock`.

---

## Documentation pipeline

```
data/llms.txt
  → scripts/parse_llms.py
  → structured documentation index (JSON + CSV)
  → scripts/sync_documentation.py
  → downloaded Markdown + SHA-256 change detection
  → immutable document versions
  → scripts/process_documentation.py
  → parsed sections and chunks
  → FTS5 searchable SQLite corpus
```

### Parse results

| Metric | Count |
|--------|-------|
| Valid articles | 208 |
| Duplicate URLs | 0 |
| Ignored lines | 4 (headings) |
| Parse errors | 6 (non-Markdown URLs) |

---

## Investigation pipeline

```
Raw support issue
  → secret sanitisation
  → technical signal extraction
  → concept mapping (45 stable codes)
  → evidence classification (observed / unconfirmed / missing)
  → documentation retrieval (hybrid FTS + token matching + reranking)
  → hypothesis construction
  → missing-evidence detection
  → adaptive checklist generation
  → closed grounding package
  → Gemini drafting (structured JSON + answer + claim map)
  → deterministic validation (fact-ref, source-ref, secret-leakage)
  → human review (needs_review → approved → used)
  → optional confirmed resolution → regression cases + feedback
```

---

## Supported draft types

| Code | Audience | Description |
|------|----------|-------------|
| `customer_update` | customer | Status update during investigation |
| `customer_resolution` | customer | Final resolution with confirmed root cause |
| `engineering_escalation` | engineering | Detailed technical escalation |
| `internal_case_summary` | internal | Internal case documentation |
| `documentation_proposal` | internal | Proposed documentation improvement |
| `product_feedback` | product | Product or observability feedback |
| `executive_summary` | executive | Leadership briefing summary |

---

## Database schema

**19 database objects** including:

- `documentation_pages` — one row per article URL (versioned, hashed)
- `documentation_versions` — immutable content snapshots
- `documentation_parsed_versions` — parsed sections and counts
- `documentation_chunks` — searchable chunks with FTS5 index
- `documentation_chunks_fts` — FTS5 virtual table
- `documentation_sync_runs` — sync audit trail
- `support_tickets` — question and case identity
- `support_ticket_evidence` — sanitized ticket evidence
- `support_ticket_analyses` — investigation results
- `support_ticket_document_links` — retrieved sources with metadata
- `support_generated_drafts` — generated answers with grounding and validation
- `support_ticket_resolutions` — human-confirmed resolutions
- `support_hypothesis_outcomes` — hypothesis vs confirmed outcome
- `support_regression_cases` — reusable regression candidates
- `support_feedback_items` — documentation/product/observability feedback

---

## Vercel deployment

The application deploys as a Flask WSGI application on Vercel with `VERCEL=1`.

On Vercel:
- The prebuilt SQLite database (`data/metronome_docs.db`, ~15 MB) is included in the deployment
- On cold start, `resolve_db_path()` copies it atomically from `/var/task/data/` to `/tmp/metronome_docs.db`
- All SQLite operations use `/tmp` — the read-only filesystem is avoided
- No PostgreSQL, Supabase, Redis, or external database is required

---

## Safety model

```
Deterministic pipeline decides facts.
Gemini drafts language.
Validator checks claims.
Human approves use.
```

- Secret sanitisation: Bearer tokens, webhook URLs, and sensitive fields are redacted
- Fact-state separation: Observed / Doc-supported / Hypothesis / Missing / Human-confirmed
- Source allow-listing: used source URLs must belong to the retrieved documentation package
- Claim mapping: generated claims identify supporting fact codes
- Human review gates: needs_review → approved → used
- Confirmed resolution boundary: only human-confirmed resolutions become reusable knowledge

---

## Quality thresholds

| Metric | Threshold | Achieved |
|--------|-----------|----------|
| Signal extraction | ≥ 95% | 100% |
| Primary-source Top-1 accuracy | ≥ 95% | 100% |
| Purpose-source recall | ≥ 95% | 100% |
| Observation-code coverage | ≥ 90% | 100% |
| Checklist precision | ≥ 85% | 100% |
| Secret redaction | 100% | 100% |
| Claim-map validity | 100% | 100% |
| Human-review transitions | 100% | 100% |

---

## CLI examples

### Documentation

```bash
python scripts/parse_llms.py
python scripts/sync_documentation.py
python scripts/process_documentation.py
python scripts/search_documentation.py "usage event not billed"
python scripts/evaluate_search.py
```

### Ticket analysis

```bash
python scripts/analyze_ticket.py --input data/examples/usage_accepted_not_billed.json --explain-concepts
python scripts/evaluate_tickets.py --split all
python scripts/ask_metronome.py "Our ai_usage event was accepted but no charge appeared. We sent token_cost_usd while the billable metric expects cost_usd."
```

### Drafting

```bash
python scripts/generate_draft.py --ticket-id 4 --type engineering_escalation --show-grounding --show-validation
python scripts/list_drafts.py --status needs_review
python scripts/inspect_draft.py --draft-id 6
python scripts/review_draft.py --draft-id 6 --decision approve --reviewer "Andrian"
python scripts/evaluate_drafting.py --split all
```

### Resolution & feedback

```bash
python scripts/resolve_ticket.py --input data/examples/resolutions/usage_property_mismatch.json --show-comparison --show-feedback
python scripts/list_feedback.py --status needs_review
python scripts/review_feedback.py --feedback-id 3 --decision approve --reviewer "Andrian"
python scripts/evaluate_resolutions.py
```

### Development

```bash
python scripts/seed_demo.py
python scripts/reset_demo.py
python scripts/smoke_test_gemini.py
python -m pytest tests/ -v
```

---

## Dependencies

```text
Flask==3.1.0
google-genai
python-dotenv
requests
psycopg2-binary
```

`google-genai` is the current Gemini SDK. The provider abstraction allows swapping to Vertex AI or another provider without changing the support workflow.

---

## Gemini provider abstraction

- `DraftingProvider` (base) — defines the provider contract
- `GeminiDraftingProvider` — live Gemini API
- `MockDraftingProvider` — deterministic structured output for testing

All automated tests use the mock provider. No test calls the live Gemini API.