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