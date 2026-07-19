#!/usr/bin/env python3
"""Interactive demo interface for Metronome Support Intelligence.

Start with::

    python scripts/run_demo.py

Opens a lightweight local web server showing the complete support-quality
workflow: evidence → grounding → Gemini draft → validation → human review.

No external dependencies beyond the standard library.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from html import escape as html_escape
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.drafting.config import load_config  # loads .env before any provider access
from src.database.repository import DocumentationRepository

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"
PORT = int(os.getenv("DEMO_PORT", "8501"))

# ---------------------------------------------------------------------------
# HTML templates (embedded for zero dependency)
# ---------------------------------------------------------------------------

_PAGE_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Metronome Support Intelligence — Demo</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.5 system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;padding:16px}
  h1{color:#58a6ff;margin-bottom:8px}
  h2{color:#f0f6fc;margin:20px 0 8px;border-bottom:1px solid #30363d;padding-bottom:4px}
  h3{color:#c9d1d9;margin:12px 0 4px}
  a{color:#58a6ff}
  table{border-collapse:collapse;width:100%;margin:8px 0}
  td,th{border:1px solid #30363d;padding:4px 8px;text-align:left}
  th{background:#161b22}
  .card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px;margin:8px 0}
  .row{display:flex;gap:12px;flex-wrap:wrap}
  .col{flex:1;min-width:280px}
  pre{background:#0d1117;border:1px solid #30363d;padding:8px;overflow-x:auto;font-size:12px;white-space:pre-wrap}
  button,input,select{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:6px 12px;border-radius:4px;cursor:pointer}
  button:hover{background:#30363d}
  .tag{display:inline-block;background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb44;padding:1px 6px;border-radius:10px;font-size:12px}
  .tag.ok{background:#23863622;color:#3fb950;border-color:#23863644}
  .tag.warn{background:#d2992222;color:#d29922;border-color:#d2992244}
  .tag.err{background:#f8514922;color:#f85149;border-color:#f8514944}
  .hidden{display:none}
  .status{margin:8px 0;padding:8px;border-radius:4px}
  .status.ok{background:#23863622;border:1px solid #23863644}
  .status.err{background:#f8514922;border:1px solid #f8514944}
</style>
</head>
<body>
<h1>Metronome Support Intelligence</h1>
<p>Deterministic pipeline → Grounding → Gemini drafting → Validation → Human approval</p>
<div class="row">
  <div class="col"><a href="/">Overview</a></div>
  <div class="col"><a href="/investigation">Investigation</a></div>
  <div class="col"><a href="/drafting">Drafting</a></div>
</div>
<hr style="border-color:#30363d;margin:8px 0">
"""

_PAGE_FOOTER = """</body></html>"""

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_overview()
        elif path == "/investigation":
            self._serve_investigation()
        elif path == "/drafting":
            self._serve_drafting_page()
        elif path == "/api/generate-draft":
            self._api_generate_draft()
        elif path == "/api/review-draft":
            self._api_review_draft()
        elif path == "/api/scenarios":
            self._api_scenarios()
        elif path == "/api/overview-data":
            self._api_overview_data()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        # Inline handling for forms
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        params = parse_qs(body) if body else {}
        path = urlparse(self.path).path

        if path == "/api/generate-draft":
            self._api_generate_draft_post(params)
        elif path == "/api/review-draft":
            self._api_review_draft_post(params)
        else:
            self.send_response(404)
            self.end_headers()

    def _html(self, title: str, body: str) -> str:
        return _PAGE_HEADER.replace("<h1>", f"<h1>{html_escape(title)}</h1>", 1) + body + _PAGE_FOOTER

    def _ok(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    # ------------------------------------------------------------------
    def _serve_overview(self):
        repo = DocumentationRepository(DB_PATH)
        repo.initialize_schema()
        try:
            conn = repo._get_conn()
            pages = conn.execute(
                "SELECT COUNT(*) FROM documentation_pages WHERE status='active'"
            ).fetchone()[0]
            tickets = conn.execute(
                "SELECT COUNT(*) FROM support_tickets"
            ).fetchone()[0]
            resolutions = conn.execute(
                "SELECT COUNT(*) FROM support_ticket_resolutions"
            ).fetchone()[0]
            feedback = conn.execute(
                "SELECT COUNT(*) FROM support_feedback_items"
            ).fetchone()[0]
            drafts = conn.execute(
                "SELECT COUNT(*) FROM support_generated_drafts"
            ).fetchone()[0]
            # Latest sync
            sync = conn.execute(
                "SELECT * FROM documentation_sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            repo.close()

        body = f"""<div class="row">
  <div class="col">
    <div class="card">
      <h3>Documentation</h3>
      <p>{pages} articles indexed</p>
      <p>Sync status: {sync['status'] if sync else 'N/A'}</p>
      <p>Last sync: {sync['started_at'][:19] if sync else 'N/A'}</p>
    </div>
  </div>
  <div class="col">
    <div class="card">
      <h3>Support Pipeline</h3>
      <table>
        <tr><td>Tickets</td><td>{tickets}</td></tr>
        <tr><td>Confirmed resolutions</td><td>{resolutions}</td></tr>
        <tr><td>Feedback items</td><td>{feedback}</td></tr>
        <tr><td>Generated drafts</td><td>{drafts}</td></tr>
      </table>
    </div>
  </div>
</div>
<div class="card">
  <h3>Workflow</h3>
  <pre>
Customer ticket → Sanitize → Extract signals → Retrieve documentation
→ Build observations → Adaptive checklist → Human-confirmed resolution
→ Regression case → Feedback proposal → Human review

NEW — Phase 6:
Deterministic grounding → Gemini drafting → Claim validation → Human approval
  </pre>
</div>
<div class="card">
  <h3>Quick Actions</h3>
  <a href="/investigation"><button>View Investigation</button></a>
  <a href="/drafting"><button>Generate Draft</button></a>
</div>"""
        self._ok(self._html("Overview", body))

    # ------------------------------------------------------------------
    def _serve_investigation(self):
        """Show ticket investigation data."""
        repo = DocumentationRepository(DB_PATH)
        repo.initialize_schema()
        try:
            conn = repo._get_conn()
            tickets = conn.execute(
                "SELECT id, subject, customer_message, created_at FROM support_tickets ORDER BY id DESC"
            ).fetchall()
            analyses = {}
            for t in tickets:
                a = conn.execute(
                    "SELECT * FROM support_ticket_analyses WHERE ticket_id=? ORDER BY id DESC LIMIT 1",
                    (t["id"],),
                ).fetchone()
                if a:
                    analyses[t["id"]] = a
        finally:
            repo.close()

        rows = ""
        for t in tickets:
            a = analyses.get(t["id"])
            hyp_count = len(json.loads(a["hypotheses_json"])) if a else 0
            obs_count = len(json.loads(a["observations_json"])) if a else 0
            rows += f"""<tr>
              <td>{t['id']}</td>
              <td>{html_escape(t['subject'])}</td>
              <td>{obs_count} observations</td>
              <td>{hyp_count} hypotheses</td>
              <td>{t['created_at'][:19]}</td>
            </tr>"""

        details = ""
        for t in tickets[:3]:
            a = analyses.get(t["id"])
            if not a:
                continue
            obs = json.loads(a["observations_json"])
            hyps = json.loads(a["hypotheses_json"])
            steps = json.loads(a["investigation_steps_json"])

            details += f"""<div class="card">
              <h3>Ticket {t['id']}: {html_escape(t['subject'])}</h3>
              <p><strong>Message:</strong> {html_escape(t['customer_message'][:200])}</p>
              <p><strong>Retrieval query:</strong> {html_escape(a['retrieval_query'])}</p>
              <h4>Observations ({len(obs)})</h4><ul>"""
            for o in obs[:5]:
                details += f"<li>{html_escape(o.get('statement', str(o)))}</li>"
            details += "</ul><h4>Hypotheses</h4><ul>"
            for h in hyps[:3]:
                details += f"<li>{html_escape(h.get('title', str(h)))}</li>"
            details += f"</ul><h4>Checklist ({len(steps)} steps)</h4><ol>"
            for s in steps[:10]:
                details += f"<li><span class='tag'>{html_escape(s.get('priority',''))}</span> {html_escape(s.get('action',str(s)))}</li>"
            details += "</ol></div>"

        body = f"""<div class="card">
  <h3>Ticket Investigations</h3>
  <table><tr><th>ID</th><th>Subject</th><th>Obs</th><th>Hyp</th><th>Created</th></tr>
  {rows}
  </table>
</div>
{details}"""
        self._ok(self._html("Investigation", body))

    # ------------------------------------------------------------------
    def _serve_drafting_page(self):
        """Serve the drafting panel."""
        body = """<div class="card">
  <h3>Generate Grounded Draft</h3>
  <form method="POST" action="/api/generate-draft">
    <label>Ticket ID: <input name="ticket_id" type="number" value="1"></label>
    <label>Draft type:
      <select name="draft_type">
        <option>customer_update</option>
        <option>customer_resolution</option>
        <option>engineering_escalation</option>
        <option>internal_case_summary</option>
        <option>documentation_proposal</option>
        <option>product_feedback</option>
        <option>executive_summary</option>
      </select>
    </label>
    <label>Provider:
      <select name="provider">
        <option value="mock">Mock (deterministic)</option>
        <option value="gemini">Gemini (live)</option>
      </select>
    </label>
    <button type="submit">Generate Draft</button>
  </form>
</div>
<div id="draft-result" class="card hidden">
  <h3>Draft Result</h3>
  <div id="draft-content"></div>
</div>
<div class="card">
  <h3>Review Draft</h3>
  <form method="POST" action="/api/review-draft">
    <label>Draft ID: <input name="draft_id" type="number"></label>
    <label>Decision:
      <select name="decision">
        <option>approve</option>
        <option>reject</option>
        <option>mark_used</option>
      </select>
    </label>
    <label>Reviewer: <input name="reviewer" value="Demo User"></label>
    <label>Notes: <input name="notes"></label>
    <button type="submit">Submit Review</button>
  </form>
</div>"""
        self._ok(self._html("Drafting", body))

    # ------------------------------------------------------------------
    def _api_generate_draft_post(self, params):
        ticket_id = int(params.get("ticket_id", [1])[0])
        draft_type = params.get("draft_type", ["customer_update"])[0]
        provider_name = params.get("provider", ["mock"])[0]

        from src.drafting.service import generate_grounded_draft
        from src.drafting.providers.mock import MockDraftingProvider

        if provider_name == "gemini":
            try:
                from src.drafting.providers.gemini import GeminiDraftingProvider
                provider = GeminiDraftingProvider()
            except Exception as exc:
                body = f"<h2>Gemini unavailable</h2><p>{html_escape(str(exc))}</p><p>Displaying a previously validated demo draft if available.</p>"
                self._ok(self._html("Drafting", body))
                return
        else:
            provider = MockDraftingProvider(mode="valid")

        try:
            draft = generate_grounded_draft(
                draft_type=draft_type,
                database_path=DB_PATH,
                ticket_id=ticket_id,
                provider=provider,
            )
        except Exception as exc:
            body = f"<h2>Generation failed</h2><p>{html_escape(str(exc))}</p>"
            self._ok(self._html("Drafting", body))
            return

        validation_class = "ok" if draft.validation_status == "valid" else "err"
        status_class = "ok" if draft.status == "needs_review" else "warn"

        body = f"""<h2>Draft #{draft.id}</h2>
<p>Type: <span class='tag'>{html_escape(draft.draft_type)}</span>
   Provider: <span class='tag'>{html_escape(draft.provider)}</span>
   Model: <span class='tag'>{html_escape(draft.model)}</span></p>
<p>Status: <span class='tag {status_class}'>{html_escape(draft.status)}</span>
   Validation: <span class='tag {validation_class}'>{html_escape(draft.validation_status)}</span></p>
<h3>Used Fact Codes</h3><ul>"""
        for fc in draft.used_fact_codes:
            body += f"<li>{html_escape(fc)}</li>"
        body += "</ul><h3>Used Sources</h3><ul>"
        for u in draft.used_source_urls:
            body += f"<li>{html_escape(u)}</li>"
        body += "</ul>"
        if draft.validation_errors:
            body += "<h3>Validation Errors</h3><ul>"
            for e in draft.validation_errors:
                body += f"<li class='tag err'>{html_escape(e)}</li>"
            body += "</ul>"
        if draft.validation_warnings:
            body += "<h3>Warnings</h3><ul>"
            for w in draft.validation_warnings:
                body += f"<li class='tag warn'>{html_escape(w)}</li>"
            body += "</ul>"
        body += "<h3>Draft Body</h3><pre>"
        body += html_escape(draft.body)
        body += "</pre>"

        # Approve/reject form inline
        body += f"""<form method='POST' action='/api/review-draft'>
<input type='hidden' name='draft_id' value='{draft.id}'>
<select name='decision'><option>approve</option><option>reject</option></select>
<input name='reviewer' value='Demo User'>
<input name='notes' placeholder='Review notes'>
<button type='submit'>Submit</button></form>"""

        self._ok(self._html("Drafting", body))

    def _api_review_draft_post(self, params):
        draft_id = int(params.get("draft_id", [0])[0])
        decision = params.get("decision", ["approve"])[0]
        reviewer = params.get("reviewer", ["Demo"])[0]
        notes = params.get("notes", [None])[0]

        from src.drafting.service import review_generated_draft

        try:
            result = review_generated_draft(
                draft_id=draft_id,
                decision=decision,
                reviewer=reviewer,
                notes=notes,
                database_path=DB_PATH,
            )
            body = f"<h2>Review Submitted</h2><p>Draft {draft_id} is now <span class='tag ok'>{html_escape(result.status)}</span>.</p>"
        except Exception as exc:
            body = f"<h2>Review failed</h2><p>{html_escape(str(exc))}</p>"

        self._ok(self._html("Drafting", body))

    def _api_scenarios(self):
        self._json({"scenarios": ["contract_409", "usage_accepted_not_billed", "contract_missing_field"]})

    def _api_overview_data(self):
        repo = DocumentationRepository(DB_PATH)
        repo.initialize_schema()
        try:
            conn = repo._get_conn()
            pages = conn.execute("SELECT COUNT(*) FROM documentation_pages WHERE status='active'").fetchone()[0]
            tickets = conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0]
            drafts = conn.execute("SELECT COUNT(*) FROM support_generated_drafts").fetchone()[0]
        finally:
            repo.close()
        self._json({"pages": pages, "tickets": tickets, "drafts": drafts})

    def _api_generate_draft(self):
        # GET version — redirects to page
        self._serve_drafting_page()

    def _api_review_draft(self):
        self._serve_drafting_page()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run scripts/sync_documentation.py first.")
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", PORT), DemoHandler)
    print(f"=== Metronome Support Intelligence Demo ===")
    print(f"Open: http://127.0.0.1:{PORT}")
    print(f"Press Ctrl+C to stop.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()