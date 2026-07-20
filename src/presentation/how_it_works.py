"""Build the /how-it-works engineering case-study page.

Reads documentation metrics and concept counts from the database but
does NOT import test modules, execute scripts, or run pytest.
"""
from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]


def build_page(db_metrics: dict, concept_metrics: dict, verified_evidence: dict) -> str:
    """Return the complete /how-it-works body HTML."""
    parts: list[str] = []
    parts.append(_hero(db_metrics, verified_evidence))
    parts.append(_what_makes_special())
    parts.append(_pipeline())
    parts.append(_not_just_rag())
    parts.append(_documentation_intelligence(db_metrics))
    parts.append(_scripts_section())
    parts.append(_codebase_map())
    parts.append(_testing_section(verified_evidence))
    parts.append(_trust_model())
    parts.append(_case_lifecycle())
    parts.append(_storage_section())
    parts.append(_tradeoffs())
    parts.append(_limitations())
    parts.append(_summary())
    return "".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt(n: object) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _card(title: str, body: str, *, css_class: str = "") -> str:
    return f"<section class='card card-pad {css_class}'><div class='section-title'><h2>{title}</h2></div>{body}</section>"


def _badge(text: str, kind: str = "accent") -> str:
    return f"<span class='badge {kind}'>{text}</span>"


def _metric_val(label: str, value: str) -> str:
    return f"<div class='metric-card' style='padding:16px 18px'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div></div>"


def _phase_card(title: str, body: str) -> str:
    return f"<div class='card card-pad'><h3 style='margin:0 0 8px'>{title}</h3><div class='muted' style='font-size:13px;line-height:1.65'>{body}</div></div>"


# ---------------------------------------------------------------------------
# 1. Hero
# ---------------------------------------------------------------------------
def _hero(metrics: dict, evidence: dict) -> str:
    tests_count = _fmt(evidence.get("tests", {}).get("passed", 0))
    return f"""
<div class='page-head'><div>
<h1>Engineering support as a controlled reasoning system</h1>
<p style='font-size:15px;max-width:820px'><strong>Not a documentation chatbot.</strong> Metronome Support Intelligence is a controlled technical-investigation system that combines deterministic evidence extraction, versioned documentation retrieval, adaptive investigation planning, grounded language-model drafting, claim-level validation, and human review.</p>
<p class='muted' style='margin-top:10px'>A conventional RAG chatbot searches documents and asks a language model to write an answer. This project first constructs a support investigation: what was observed, what is missing, what is only suspected, which documentation applies, what must be checked next, and what evidence would justify escalation.</p></div>
</div>

<div class='metric-grid' style='margin-bottom:18px'>
  {_metric_val("Documentation articles", _fmt(metrics.get("articles", 0)))}
  {_metric_val("Searchable chunks", _fmt(metrics.get("chunks", 0)))}
  {_metric_val("Investigation concepts", _fmt(metrics.get("concepts", 0)))}
  {_metric_val("Passing tests", tests_count)}
</div>

<div class='chip-list' style='margin-bottom:20px'>
  {_badge("Versioned documentation", "ok")}
  {_badge("Deterministic retrieval", "accent")}
  {_badge("Closed grounding", "accent")}
  {_badge("Claim validation", "ok")}
  {_badge("Secret redaction", "ok")}
  {_badge("Human approval", "warn")}
</div>
"""


# ---------------------------------------------------------------------------
# 2. What makes this special
# ---------------------------------------------------------------------------
def _what_makes_special() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'>
  <div class='section-title'><h2>What makes this different</h2></div>

  <h3 style='margin-top:18px'>A. It models an investigation, not merely a question</h3>
  <p class='muted'>A submitted support issue is transformed into structured elements: sanitised ticket input, detected technical signals, product area and operation, observations, validation findings, hypotheses, missing evidence, mapped support concepts, ordered investigation steps, escalation requirements, and relevant documentation.</p>
  <div class='chip-list' style='margin:12px 0'>
    {_badge("Observed", "ok")}
    {_badge("Unconfirmed", "warn")}
    {_badge("Missing", "bad")}
    {_badge("Doc-supported", "accent")}
    {_badge("Human-confirmed", "ok")}
  </div>

  <h3 style='margin-top:24px'>B. Deterministic reasoning happens before generative drafting</h3>
  <div class='excerpt' style='margin:8px 0;font-size:13px'>
    Raw support issue → secret sanitisation → technical signal extraction → concept mapping → evidence classification → documentation retrieval → hypothesis construction → missing-evidence detection → checklist generation → closed grounding package → Gemini drafting → deterministic validation → human review
  </div>
  <p class='muted'>Gemini does not independently choose the workflow or declare a root cause.</p>

  <h3 style='margin-top:24px'>C. The grounding package is closed</h3>
  <p class='muted'>Gemini receives only an explicitly constructed package containing allowed facts, allowed sources, observations, labelled hypotheses, missing evidence, and investigation steps. The model cannot silently rely on unrelated repository content, unapproved URLs, raw credentials, or unsupported assumptions.</p>

  <h3 style='margin-top:24px'>D. Every important generated claim is traceable</h3>
  <p class='muted'>Fact codes, source URLs, used-fact lists, used-source lists, claim maps, required-section validation, unsupported-claim rejection, source validation, and secret-leakage validation create an auditable trace from generated text back to evidence.</p>
  <div class='excerpt' style='margin:12px 0;font-size:12px'>
    <strong>Generated claim:</strong> "The event-property mismatch is a suspected cause."<br>
    <strong>Supported by:</strong> question.input · usage.compare_property_filters · documentation.<fact-code><br>
    <strong>Status:</strong> Hypothesis — not confirmed root cause
  </div>

  <h3 style='margin-top:24px'>E. Investigation steps adapt to available evidence</h3>
  <p class='muted'>The checklist is not static. The system suppresses steps that are already complete and adds steps required by missing evidence. When transaction_id is missing, the checklist asks the engineer to capture it. When it is already present, collection is skipped and the checklist moves directly to Event Search. When billable-metric configuration is available, the system compares it instead of requesting it again.</p>

  <h3 style='margin-top:24px'>F. Resolutions create reusable engineering knowledge</h3>
  <p class='muted'>Generated investigation → human investigation → confirmed root cause → hypothesis outcomes → verification evidence → reusable regression case → documentation/product/observability feedback. Unreviewed Gemini answers do not automatically become trusted knowledge.</p>
</section>"""


# ---------------------------------------------------------------------------
# 3. Pipeline (15 stages)
# ---------------------------------------------------------------------------
def _pipeline() -> str:
    stages = [
        ("Documentation discovery", "src/documentation/downloader.py", "llms.txt index", "URL-validated page list", "Handles retry, malformed entries, duplicates.", "tests/test_llms_parser.py"),
        ("Documentation sync", "src/documentation/synchronizer.py", "Discovered URLs", "Downloaded Markdown + immutable versions", "SHA-256 change detection; only stores new/changed content.", "tests/test_documentation_sync.py"),
        ("Markdown & OpenAPI parsing", "src/documentation/markdown_parser.py", "Raw Markdown", "Sections, code blocks, tables, OpenAPI blocks", "Preserves heading hierarchy; extracts API metadata.", "tests/test_markdown_parser.py, tests/test_chunker.py"),
        ("Chunk generation", "src/documentation/chunker.py", "Parsed sections", "Searchable chunks with metadata", "Token-estimate, type labelling, heading-path tracking.", "tests/test_chunker.py"),
        ("Ticket sanitisation", "src/support/sanitizer.py", "Raw user question", "Credentials-redacted input", "Removes Bearer tokens, webhook URLs, sensitive fields.", "tests/test_ticket_sanitizer.py"),
        ("Signal extraction", "src/support/signal_extractor.py", "Sanitised ticket", "Product area, operation, technical identifiers", "Only explicit evidence marked observed.", "tests/test_signal_extractor.py"),
        ("Concept mapping", "src/support/analyzer.py", "Signals + evidence", "Activated concept codes", "92 stable concept codes across contracts, usage, customers.", "tests/test_concept_registry.py, tests/test_ticket_analyzer.py"),
        ("Evidence classification", "src/support/observation_builder.py", "Mapped concepts", "Observations, hypotheses, missing evidence", "Separates confirmed from suspected.", "tests/test_observation_builder.py"),
        ("Documentation retrieval", "src/documentation/search.py", "Retrieval query", "Ranked documentation chunks", "Hybrid FTS + technical-token + endpoint matching.", "tests/test_search_quality.py"),
        ("Investigation planning", "src/support/checklist_builder.py", "Evidence state", "Ordered, adaptive checklist", "Suppresses completed steps; adds missing-evidence steps.", "tests/test_checklist_builder.py"),
        ("Grounding package", "src/assistant/service.py", "Investigation report + doc chunks", "Closed DraftGroundingPackage", "Fact codes, allowed sources, confirmed/missing statuses.", "tests/test_drafting_grounding.py"),
        ("Gemini drafting", "src/drafting/providers/gemini.py", "Grounding package + prompt", "Structured JSON + answer text + claim map", "Provider abstraction; mock provider for deterministic tests.", "tests/test_drafting_provider.py"),
        ("Claim & source validation", "src/drafting/validator.py", "Draft output", "Validation errors/warnings", "Fact-ref, source-ref, claim-support, hypothesis-wording checks.", "tests/test_drafting_validator.py"),
        ("Persistence & review", "src/database/repository.py", "Validated draft + investigation", "Persisted case + review state", "needs_review → approved → used lifecycle.", "tests/test_ticket_persistence.py"),
        ("Resolution & regression", "src/support/resolution_*.py", "Confirmed resolution", "Regression cases + feedback items", "Gap classification, hypothesis outcomes.", "tests/test_resolution_*.py"),
    ]
    cards = "".join(
        f"""<details class='card card-pad' style='margin:6px 0'><summary style='cursor:pointer;font-weight:720'>{i}. {name}</summary>
<div style='margin-top:8px' class='muted'><strong>Implementation:</strong> <code>{impl}</code></div>
<div class='metric-row'><span>Input</span><span>{inp}</span></div>
<div class='metric-row'><span>Output</span><span>{out}</span></div>
<div class='metric-row'><span>Guarantee</span><span>{guarantee}</span></div>
<div class='metric-row'><span>Tests</span><span><code>{tests}</code></span></div>
</details>"""
        for i, (name, impl, inp, out, guarantee, tests) in enumerate(stages, 1)
    )
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>End-to-end system pipeline</h2><span class='badge accent'>15 STAGES</span></div>
{cards}
</section>"""


# ---------------------------------------------------------------------------
# 4. Not just RAG comparison
# ---------------------------------------------------------------------------
def _not_just_rag() -> str:
    rows = [
        ("Retrieves similar text", "Retrieves and reranks technical evidence"),
        ("Sends broad context to an LLM", "Builds a closed grounding package"),
        ("Produces one fluent answer", "Produces investigation, checklist and communication"),
        ("May mix facts and guesses", "Separates observations, hypotheses and missing evidence"),
        ("Citations may be decorative", "Sources are validated against retrieved records"),
        ("No claim-level traceability", "Generated claims map back to fact codes"),
        ("Answer becomes final output", "Answer requires deterministic validation and human review"),
        ("No learning after resolution", "Confirmed outcomes generate regression and feedback artefacts"),
    ]
    table = "".join(f"<tr><td style='padding:8px 12px;border-bottom:1px solid var(--border-soft)'>{a}</td><td style='padding:8px 12px;border-bottom:1px solid var(--border-soft)'><strong>{b}</strong></td></tr>" for a, b in rows)
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Not just RAG</h2></div>
<div class='table-wrap'><table class='table'><thead><tr><th>Conventional documentation chatbot</th><th>Metronome Support Intelligence</th></tr></thead><tbody>{table}</tbody></table></div>
</section>"""


# ---------------------------------------------------------------------------
# 5. Documentation intelligence
# ---------------------------------------------------------------------------
def _documentation_intelligence(metrics: dict) -> str:
    pipeline_desc = (
        "<code>data/llms.txt</code> → <code>scripts/parse_llms.py</code> → structured documentation index → "
        "<code>scripts/sync_documentation.py</code> → downloaded Markdown → SHA-256 change detection → "
        "immutable document versions → parsed sections and chunks → searchable SQLite corpus"
    )
    m = metrics
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Documentation intelligence</h2></div>
<div class='excerpt' style='margin-bottom:14px'>{pipeline_desc}</div>
<div class='metric-grid'>
  {_metric_val("Articles", _fmt(m.get("articles", 0)))}
  {_metric_val("Sections", _fmt(m.get("sections", 0)))}
  {_metric_val("Chunks", _fmt(m.get("chunks", 0)))}
  {_metric_val("Code blocks", _fmt(m.get("code_blocks", 0)))}
  {_metric_val("Tables", _fmt(m.get("tables", 0)))}
  {_metric_val("OpenAPI blocks", _fmt(m.get("openapi_blocks", 0)))}
</div>
<div style='margin-top:12px'><h4>Why immutable versions matter</h4>
<ul class='muted' style='font-size:13px'><li>Investigation reproducibility</li><li>Auditing which documentation supported an answer</li><li>Detecting documentation changes between syncs</li><li>Preserving historical source content</li><li>Avoiding silent overwrites</li></ul></div>
</section>"""


# ---------------------------------------------------------------------------
# 6. Scripts section
# ---------------------------------------------------------------------------
def _scripts_section() -> str:
    # Scripts verified from actual repository inspection
    scripts = [
        ("Documentation ingestion", [
            ("scripts/parse_llms.py", "Transform Metronome llms.txt into validated structured records.", "data/llms.txt", "data/parsed/documentation_index.{json,csv}", "Yes — output is deterministic for the same input.", True, False, None),
            ("scripts/sync_documentation.py", "Download, hash, and version all documentation pages.", "data/parsed/documentation_index.json", "SQLite (documentation_pages, _versions, _parsed_versions, _chunks)", "Yes — only downloads changed content.", True, True, None),
            ("scripts/process_documentation.py", "Parse raw Markdown versions into sections, chunks and search index.", "documentation_versions.raw_markdown", "documentation_parsed_versions, documentation_chunks, FTS index", "Yes — rebuilds parsed state from versions.", True, True, None),
        ]),
        ("Ticket investigation", [
            ("scripts/analyze_ticket.py", "Run the deterministic ticket analyser on a single ticket JSON.", "JSON ticket file (data/examples/*.json)", "stdout — printed investigation report", "Yes — read-only analysis.", False, False, None),
            ("scripts/evaluate_tickets.py", "Batch-evaluate ticket analysis against labelled cases.", "data/evaluation/ticket_cases.json", "stdout — evaluation metrics", "Yes — pure evaluation.", False, False, "GEMINI_API_KEY (optional)"),
        ]),
        ("Drafting & communication", [
            ("scripts/generate_draft.py", "Generate a grounded draft from a persisted investigation.", "SQLite (ticket + analysis)", "SQLite (support_generated_drafts)", "Yes — creates a new draft version.", True, True, "GEMINI_API_KEY"),
            ("scripts/evaluate_drafting.py", "Batch-evaluate drafting quality against labelled cases.", "data/evaluation/drafting_cases.json", "stdout — drafting metrics", "Yes — pure evaluation.", False, False, "GEMINI_API_KEY (optional)"),
            ("scripts/review_draft.py", "Review a generated draft (approve, reject, mark used).", "Command-line args", "SQLite (updates draft status)", "Yes — only changes review state.", True, True, None),
            ("scripts/inspect_draft.py", "Inspect a generated draft, its grounding package and claim map.", "SQLite (draft ID)", "stdout — pretty-printed draft detail", "Yes — read-only inspection.", False, False, None),
            ("scripts/list_drafts.py", "List all generated drafts with status and validation filters.", "SQLite", "stdout — filtered draft list", "Yes — read-only listing.", False, False, None),
            ("scripts/ask_metronome.py", "CLI entrypoint: ask a question and get a grounded answer.", "stdin / CLI args", "stdout — printed answer", "Yes — creates persisted case and draft.", True, True, "GEMINI_API_KEY"),
        ]),
        ("Resolution & feedback", [
            ("scripts/resolve_ticket.py", "Record a confirmed resolution for a support case.", "CLI args + SQLite", "SQLite (support_ticket_resolutions + outcomes + regression + feedback)", "Conditional — once per case resolution.", False, True, None),
            ("scripts/evaluate_resolutions.py", "Batch-evaluate resolution quality against labelled cases.", "data/evaluation/ (resolution cases)", "stdout — resolution metrics", "Yes — pure evaluation.", False, False, None),
            ("scripts/list_feedback.py", "List feedback items with filtering by type, status, priority.", "SQLite", "stdout — filtered feedback list", "Yes — read-only listing.", False, False, None),
            ("scripts/review_feedback.py", "Review and update feedback item status.", "CLI args + SQLite", "SQLite (updates feedback status)", "Yes — only changes review state.", True, True, None),
        ]),
        ("Search & retrieval", [
            ("scripts/search_documentation.py", "CLI search of the indexed documentation corpus.", "CLI args + SQLite", "stdout — ranked search results", "Yes — read-only search.", False, False, None),
            ("scripts/evaluate_search.py", "Batch-evaluate search quality against labelled cases.", "data/evaluation/search_cases.json", "stdout — search evaluation metrics", "Yes — pure evaluation.", False, False, None),
        ]),
        ("Development & deployment", [
            ("scripts/seed_demo.py", "Seed the database with demonstration tickets and answers.", "None (generates synthetic data)", "SQLite (support tables)", "Yes — inserts demo data.", True, True, None),
            ("scripts/reset_demo.py", "Remove all demo/support data while preserving documentation.", "SQLite", "SQLite (clears support tables)", "Yes — only removes demo data.", True, True, None),
            ("scripts/run_demo.py", "Local development server launcher.", "None", "Process (Flask dev server)", "Yes.", False, False, "GEMINI_API_KEY (optional)"),
            ("scripts/smoke_test_gemini.py", "Verify Gemini API connectivity and structured output format.", "None", "stdout — pass/fail", "Yes.", False, False, "GEMINI_API_KEY"),
        ]),
    ]

    sections = []
    for category, items in scripts:
        cards = "".join(
            f"""<details class='card card-pad' style='margin:4px 0'><summary style='cursor:pointer;font-weight:720'><code>{path}</code></summary>
<div style='margin-top:8px'><strong>Purpose:</strong> {purpose}</div>
<div class='metric-row'><span>Reads</span><span><code>{reads}</code></span></div>
<div class='metric-row'><span>Writes</span><span><code>{writes}</code></span></div>
<div class='metric-row'><span>Safe to rerun</span><span>{rerun}</span></div>
<div class='metric-row'><span>Modifies data</span><span>{'Yes' if mutates else 'No'}</span></div>
{"".join(f"<div class='metric-row'><span>Env vars</span><span><code>{env}</code></span></div>" if env else "")}
</details>"""
            for path, purpose, reads, writes, rerun, _, mutates, env in items
        )
        sections.append(f"<h3 style='margin:16px 0 8px'>{category}</h3>{cards}")

    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Operational scripts</h2><span class='badge accent'>{sum(len(items) for _, items in scripts)} SCRIPTS</span></div>
{''.join(sections)}
</section>"""


# ---------------------------------------------------------------------------
# 7. Codebase map
# ---------------------------------------------------------------------------
def _codebase_map() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Repository architecture</h2></div>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>app.py — Flask application</summary>
<div class='muted' style='margin-top:6px'>12 routes, server-rendered HTML, SQLite-backed. <code>_layout()</code> wraps every page with sidebar navigation, breadcrumbs and dark theme.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>src/assistant/ — End-to-end orchestration</summary>
<div class='muted' style='margin-top:6px'>Connects sanitiser, analyser, grounding-package builder and drafting provider. Single entrypoint: <code>answer_metronome_question()</code>.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>src/support/ — Deterministic investigation (22 modules)</summary>
<div class='muted' style='margin-top:6px'>Concept registry, signal extraction, observation building, hypothesis generation, missing-evidence detection, checklist construction, concept suppression/merging, source selection, evidence validation, ticket parsing, sanitisation, retrieval-query building.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>src/documentation/ — Documentation pipeline (13 modules)</summary>
<div class='muted' style='margin-top:6px'>llms.txt downloader and parser, Markdown parser, OpenAPI extractor, chunker, content processor, search engine (FTS + hybrid), query analyser, reranker, search evaluator, metadata index loader, content hashing, synchronizer.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>src/drafting/ — Grounded drafting (8 modules + 2 providers)</summary>
<div class='muted' style='margin-top:6px'>Drafting service, grounding-package factory, Gemini provider, mock provider, claim checker, section validator, source validator, secret/prompt sanitisation, structured-output validator, evaluator.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>src/database/ — Persistence (4 modules)</summary>
<div class='muted' style='margin-top:6px'>SQLite connection with Vercel /tmp path resolution, schema (19 DB objects including FTS5), repository (41 methods), adapter (SQLite/PostgreSQL backend selection).</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>src/feedback/ — Feedback models</summary>
<div class='muted' style='margin-top:6px'>Documentation-gap, product, and observability feedback item types with priority, status and owner tracking.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>scripts/ — 20 operational tools</summary>
<div class='muted' style='margin-top:6px'>CLI-entrypoints for ingestion, sync, search, ticket analysis, draft generation, review, resolution, evaluation and demo management.</div>
</details>

<details style='margin:8px 0'><summary style='font-weight:720;cursor:pointer'>tests/ — 30+ test files</summary>
<div class='muted' style='margin-top:6px'>Cover documentation ingestion, search, investigation, drafting, resolution, feedback, deployment and database-path resolution.</div>
</details>

<div style='margin-top:16px'><h4>Separation of responsibilities</h4>
<ul class='muted' style='font-size:13px'>
<li>Documentation modules do not generate customer answers.</li>
<li>Search modules do not decide root causes.</li>
<li>Gemini providers do not access the database directly.</li>
<li>Validation modules do not call Gemini.</li>
<li>Repository modules do not contain presentation logic.</li>
<li>Flask routes orchestrate services but do not reproduce support logic.</li>
</ul></div>
</section>"""


# ---------------------------------------------------------------------------
# 8. Testing section
# ---------------------------------------------------------------------------
def _testing_section(evidence: dict) -> str:
    tests = evidence.get("tests", {})
    datasets = evidence.get("datasets", {})
    dataset_cards = "".join(
        f"<div class='card card-pad' style='text-align:center'><div class='metric-value'>{_fmt(v.get('total', 0))}</div><div class='metric-label'>{k}</div><div class='metric-foot' style='font-size:11px'>Tuning: {_fmt(v.get('Tuning', 0))} · Holdout: {_fmt(v.get('Holdout', 0))}</div></div>"
        for k, v in datasets.items()
    )

    test_files = [
        ("Documentation ingestion", "test_llms_parser.py, test_documentation_sync.py, test_markdown_parser.py, test_chunker.py", "Index parsing, URL validation, malformed entries, duplicate detection, immutable versioning, change detection, OpenAPI extraction."),
        ("Search & retrieval", "test_search_quality.py, test_retrieval_query.py", "Technical-token matching, title/heading/endpoint/operation-ID matching, category weighting, deterministic ranking, Top-K recall."),
        ("Investigation", "test_ticket_analyzer.py, test_ticket_parser.py, test_ticket_sanitizer.py, test_signal_extractor.py, test_observation_builder.py, test_checklist_builder.py, test_checklist_ordering.py, test_concept_registry.py, test_concept_merger.py, test_concept_suppression.py, test_source_selector.py, test_source_capabilities.py", "Signal extraction, concept activation/suppression, fact classification, adaptive checklist, escalation placement, already-complete-step suppression."),
        ("Drafting & grounding", "test_drafting_service.py, test_drafting_provider.py, test_drafting_grounding.py, test_drafting_validator.py, test_claim_checker.py", "Provider abstraction, structured output, required sections, fact-code validation, claim-map validation, source validation, mock-provider determinism."),
        ("Resolution & feedback", "test_resolution_service.py, test_resolution_validator.py, test_resolution_evaluator.py, test_resolution_persistence.py, test_resolution_comparator.py, test_feedback_review.py, test_gap_classifier.py, test_proposal_builder.py, test_regression_builder.py", "Valid/invalid resolutions, hypothesis outcomes, verification evidence, regression cases, gap classification, review-state transitions."),
        ("Application & deployment", "test_deployment.py, test_db_path_resolution.py, test_assistant_service.py", "Flask import, route registration, Vercel SQLite /tmp copy, missing-DB error, CSS template rendering."),
    ]
    file_cards = "".join(
        f"""<details style='margin:4px 0'><summary style='font-weight:720;cursor:pointer'>{category}</summary>
<div class='muted' style='margin:6px 0 0 12px;font-size:13px'><strong>Files:</strong> <code>{files}</code></div>
<div class='muted' style='margin:4px 0 0 12px;font-size:13px'><strong>Coverage:</strong> {coverage}</div>
</details>"""
        for category, files, coverage in test_files
    )

    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Testing strategy</h2></div>
<div class='metric-grid' style='margin-bottom:14px'>
  {_metric_val("Tests passed", _fmt(tests.get("passed", 0)))}
  {_metric_val("Failures", _fmt(tests.get("failures", 0)))}
  {_metric_val("Skipped", _fmt(tests.get("skipped", 0)))}
  {_metric_val("Critical thresholds", "100%")}
</div>

<h4>Evaluation datasets</h4>
<div class='eval-grid' style='grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:14px'>{dataset_cards}</div>

<h4>Test coverage by subsystem</h4>
{file_cards}

<p class='muted' style='margin-top:12px;font-size:12px'>The number of test functions in source code may be lower than the final pytest case count because parametrized tests create multiple executed cases. The verified evidence shown above is loaded from static metadata — the test suite is not re-executed on every page request.</p>
</section>"""


# ---------------------------------------------------------------------------
# 9. Trust model
# ---------------------------------------------------------------------------
def _trust_model() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>How the system prevents confident nonsense</h2></div>

<h4>Secret sanitisation</h4>
<p class='muted'>Credentials, Bearer tokens, webhook URLs, and sensitive fields (<code>Authorization: Bearer <REDACTED></code>) are removed or replaced before evidence reaches drafting or persistence.</p>

<h4>Fact-state separation</h4>
<div class='chip-list' style='margin:8px 0'>
  {_badge("Observed", "ok")}
  {_badge("Doc-supported", "accent")}
  {_badge("Hypothesis", "warn")}
  {_badge("Missing", "bad")}
  {_badge("Human-confirmed", "ok")}
</div>
<p class='muted'>These states are not interchangeable. A hypothesis cannot silently become a confirmed fact.</p>

<h4>Source allow-listing</h4>
<p class='muted'>Used source URLs must belong to the retrieved documentation package. External URLs are rejected during validation.</p>

<h4>Claim mapping</h4>
<p class='muted'>Every important generated claim identifies its supporting fact codes, making the evidence chain auditable.</p>

<h4>Human review</h4>
<div class='chip-list' style='margin:8px 0'>
  {_badge("Needs review", "warn")}
  {_badge("Approved", "ok")}
  {_badge("Rejected", "bad")}
  {_badge("Used", "ok")}
</div>
<p class='muted'>Validated drafts remain untrusted until a person approves them. Only approved answers should be used in customer communication.</p>

<h4>Confirmed resolution boundary</h4>
<p class='muted'><strong>A generated explanation is not a confirmed root cause.</strong> Only a human-confirmed resolution can become reusable regression knowledge.</p>
</section>"""


# ---------------------------------------------------------------------------
# 10. Case lifecycle (synthetic)
# ---------------------------------------------------------------------------
def _case_lifecycle() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Complete case lifecycle</h2><span class='badge warn'>SYNTHETIC WALKTHROUGH</span></div>
<p class='muted' style='margin-bottom:14px'>Synthetic walkthrough — not a real Metronome customer case. Uses placeholder identifiers throughout.</p>

<div class='flow'>
  <div class='flow-step'><div class='flow-num'>1</div><div><div class='flow-title'>Issue submitted</div><div class='flow-sub'>"A usage event was accepted but no invoice line item appeared. The event sends <code>token_cost_usd</code> while the billable metric expects <code>cost_usd</code>."</div></div></div>
  <div class='flow-step'><div class='flow-num'>2</div><div><div class='flow-title'>Sanitised</div><div class='flow-sub'>Credentials removed; customer identifiers redacted.</div></div></div>
  <div class='flow-step'><div class='flow-num'>3</div><div><div class='flow-title'>Signals detected</div><div class='flow-sub'>Product area=usage, operation=ingest, property mismatch flagged.</div></div></div>
  <div class='flow-step'><div class='flow-num'>4</div><div><div class='flow-title'>Usage concepts activated</div><div class='flow-sub'>usage.accepted_not_billed, usage.compare_property_filters, usage.event_type_mismatch.</div></div></div>
  <div class='flow-step'><div class='flow-num'>5</div><div><div class='flow-title'>Observations created</div><div class='flow-sub'>Event accepted (HTTP 200), no charge generated, property name differs.</div></div></div>
  <div class='flow-step'><div class='flow-num'>6</div><div><div class='flow-title'>Missing evidence identified</div><div class='flow-sub'>transaction_id not provided, billable-metric filter configuration unknown.</div></div></div>
  <div class='flow-step'><div class='flow-num'>7</div><div><div class='flow-title'>Documentation retrieved</div><div class='flow-sub'>Usage ingestion docs, billable-metric matching, Event Search endpoint.</div></div></div>
  <div class='flow-step'><div class='flow-num'>8</div><div><div class='flow-title'>Hypothesis created</div><div class='flow-sub'>Property-name mismatch between event and billable metric is likely cause.</div></div></div>
  <div class='flow-step'><div class='flow-num'>9</div><div><div class='flow-title'>Checklist generated</div><div class='flow-sub'>Capture transaction_id → Event Search → compare property filters → verify rate card → check invoice period → escalate if still unmatched.</div></div></div>
  <div class='flow-step'><div class='flow-num'>10</div><div><div class='flow-title'>Grounding package built</div><div class='flow-sub'>Allowed facts + allowed sources + labelled hypotheses + missing evidence → closed package.</div></div></div>
  <div class='flow-step'><div class='flow-num'>11</div><div><div class='flow-title'>Gemini drafts answer</div><div class='flow-sub'>Structured JSON output with answer text, used fact codes, used source URLs, claim map.</div></div></div>
  <div class='flow-step'><div class='flow-num'>12</div><div><div class='flow-title'>Claim map validates</div><div class='flow-sub'>Fact references, source existence, hypothesis wording, and secret leakage all checked.</div></div></div>
  <div class='flow-step'><div class='flow-num'>13</div><div><div class='flow-title'>Human reviews</div><div class='flow-sub'>Approves the grounded answer or rejects with notes.</div></div></div>
  <div class='flow-step'><div class='flow-num'>14</div><div><div class='flow-title'>Confirmation → learning</div><div class='flow-sub'>If confirmed: property mismatch was the root cause → regression case + documentation feedback recorded.</div></div></div>
</div>
</section>"""


# ---------------------------------------------------------------------------
# 11. Storage
# ---------------------------------------------------------------------------
def _storage_section() -> str:
    tables = [
        ("support_tickets", "Question and case identity", "id, external_ticket_id, subject, customer_message, status, created_at"),
        ("support_ticket_evidence", "Sanitized ticket evidence", "ticket_id, http_method, endpoint_path, request/response headers and body, logs"),
        ("support_ticket_analyses", "Investigation results", "ticket_id, signals, observations, hypotheses, missing evidence, checklist, concepts"),
        ("support_ticket_document_links", "Retrieved documentation sources", "ticket_id, page_title, source_url, heading, relevance_score, matched_tokens"),
        ("support_generated_drafts", "Generated answer with grounding and validation", "ticket_id, body, grounding_package, claim_map, validation status, review status"),
        ("support_ticket_resolutions", "Human-confirmed resolution", "ticket_id, root_cause_code, resolution_summary, confirmed_by, confirmed_at"),
        ("support_hypothesis_outcomes", "Comparison of hypotheses vs confirmed outcome", "resolution_id, hypothesis_code, outcome (confirmed/rejected/inconclusive)"),
        ("support_regression_cases", "Generated regression candidates", "resolution_id, case_code, scenario, preconditions, input, expected_behavior"),
        ("support_feedback_items", "Documentation, product, and observability feedback", "resolution_id, feedback_type, gap_code, priority, status, owner"),
    ]
    lifecycle = "Question → support ticket → evidence → analysis → documentation links → generated draft → claim map and validation → human review → optional confirmed resolution → hypothesis outcomes → regression cases → feedback items"
    table_html = "".join(
        f"<div class='metric-row'><span style='font-family:monospace'>{name}</span><span>{desc}<br><span class='small muted'>{cols}</span></span></div>"
        for name, desc, cols in tables
    )
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Storage and auditability</h2></div>
<div class='excerpt' style='margin-bottom:14px'>{lifecycle}</div>
{table_html}
</section>"""


# ---------------------------------------------------------------------------
# 12. Trade-offs
# ---------------------------------------------------------------------------
def _tradeoffs() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Engineering decisions and trade-offs</h2></div>

<h4>SQLite</h4>
<p class='muted'>SQLite is appropriate for deterministic local development, an indexed documentation corpus, reproducible evaluation, simple inspection, and a portfolio demonstration.</p>
<p class='muted'>On Vercel, the packaged SQLite database is copied to <code>/tmp</code>. The documentation corpus remains available, but writes in the serverless temporary filesystem are not guaranteed to survive cold starts, instance changes or deployments.</p>
<p class='muted' style='font-size:12px;opacity:0.7'><em>Possible production evolution: a persistent datastore (not currently implemented) could replace /tmp writes for case persistence while keeping the documentation corpus in SQLite.</em></p>

<h4>Deterministic retrieval versus embeddings</h4>
<p class='muted'>Deterministic matching excels for API paths, operation IDs, event types, exact property names, transaction IDs, and billable-metric fields. Embeddings are not currently used — the retrieval strategy is hybrid FTS with technical-token and endpoint matching plus deterministic reranking.</p>

<h4>Server-rendered Flask interface</h4>
<p class='muted'>One deployable Python application with shared backend logic. No separate frontend build step, no API layer to maintain. The same modules that power the CLI tools render the web interface.</p>

<h4>Gemini provider abstraction</h4>
<p class='muted'>Provider behaviour is isolated behind <code>DraftingProvider</code>. The <code>MockDraftingProvider</code> returns deterministic structured output for tests, making drafting and validation testable without network calls or API keys.</p>

<h4>Static evaluation evidence</h4>
<p class='muted'>The page displays verified results from the most recent test run rather than re-executing hundreds of tests on every request. This keeps page load fast and avoids side effects on the production database.</p>
</section>"""


# ---------------------------------------------------------------------------
# 13. Limitations
# ---------------------------------------------------------------------------
def _limitations() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Current limitations</h2></div>
<ul class='muted' style='font-size:13px;line-height:1.8'>
<li>Vercel <code>/tmp</code> writes are ephemeral — production cases are not guaranteed to persist across cold starts.</li>
<li>Documentation synchronization is an offline operational task — the corpus reflects the last explicit sync.</li>
<li>Gemini output quality depends on the completeness of provided evidence.</li>
<li>Human confirmation is required for final root cause — the system supports, not replaces, engineering judgement.</li>
<li>Search is optimised for indexed Metronome documentation — general web search is not supported.</li>
<li>This is an engineering portfolio system, not an official Metronome product.</li>
</ul>
</section>"""


# ---------------------------------------------------------------------------
# 14. Summary
# ---------------------------------------------------------------------------
def _summary() -> str:
    return f"""<div style='height:20px'></div>
<section class='card card-pad'><div class='section-title'><h2>Why this project matters</h2></div>
<p class='muted' style='font-size:15px;margin-bottom:16px'>The difficult part was not calling Gemini. The difficult part was designing everything around the model: versioned technical evidence, deterministic retrieval, explicit uncertainty, adaptive investigation planning, closed grounding, claim-level traceability, secret protection, human review, and regression learning. The result is a support-engineering system where AI improves speed and communication without becoming the source of truth.</p>

<div class='chip-list' style='margin-top:12px'>
  {_badge("Python", "accent")}
  {_badge("SQLite", "accent")}
  {_badge("Documentation ingestion", "ok")}
  {_badge("Content hashing", "ok")}
  {_badge("Markdown parsing", "ok")}
  {_badge("OpenAPI extraction", "ok")}
  {_badge("Information retrieval", "accent")}
  {_badge("Workflow modelling", "accent")}
  {_badge("Prompt design", "warn")}
  {_badge("LLM integration", "warn")}
  {_badge("Deterministic validation", "ok")}
  {_badge("Secret handling", "ok")}
  {_badge("Regression evaluation", "ok")}
  {_badge("Flask + Vercel", "accent")}
  {_badge("Automated testing", "ok")}
</div>
</section>"""