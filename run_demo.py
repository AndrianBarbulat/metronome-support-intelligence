#!/usr/bin/env python3
"""Metronome Support Intelligence web application.

Run::

    python scripts/run_demo.py

Then open http://127.0.0.1:8501. Questions are persisted as support cases,
analysed against the indexed Metronome documentation, drafted by Gemini or the
mock provider, validated, and exposed through a reviewable case history.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.assistant.service import answer_metronome_question
from src.database.repository import DocumentationRepository
from src.drafting.config import load_config
from src.drafting.service import review_generated_draft

load_config()

DB_PATH = _PROJECT_ROOT / "data" / "metronome_docs.db"
PORT = int(os.getenv("DEMO_PORT", "8501"))


_STYLE = r"""
:root{
  color-scheme:dark;
  --bg:#07101e;--sidebar:#0a1323;--surface:#0f1a2d;--surface-2:#121f35;
  --surface-3:#0b1628;--border:#21324c;--border-soft:#182842;
  --text:#ecf3ff;--muted:#91a2b8;--faint:#687a91;--accent:#6ea8fe;
  --accent-strong:#3f7ddd;--accent-soft:rgba(110,168,254,.12);
  --ok:#4fd1a5;--ok-soft:rgba(79,209,165,.12);--warn:#f2b65d;
  --warn-soft:rgba(242,182,93,.12);--bad:#ff7474;--bad-soft:rgba(255,116,116,.11);
  --shadow:0 20px 50px rgba(0,0,0,.22);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(circle at 80% 0%,#10233f 0,transparent 29%),var(--bg);color:var(--text);font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:inherit;text-decoration:none}
button,input,textarea,select{font:inherit}
.app{min-height:100vh;display:grid;grid-template-columns:250px minmax(0,1fr)}
.sidebar{position:sticky;top:0;height:100vh;padding:22px 17px;border-right:1px solid var(--border-soft);background:rgba(8,17,31,.94);backdrop-filter:blur(16px);display:flex;flex-direction:column;z-index:5}
.brand{display:flex;align-items:center;gap:11px;padding:4px 8px 24px}.logo{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#4a89ee,#7d5cf1);font-weight:800;box-shadow:0 10px 25px rgba(74,137,238,.3)}
.brand-name{font-size:15px;font-weight:750;letter-spacing:.1px}.brand-sub{font-size:11px;color:var(--muted)}
.nav-label{padding:0 11px;margin:13px 0 7px;color:var(--faint);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:1.2px}
.nav{display:flex;flex-direction:column;gap:5px}.nav a{display:flex;align-items:center;gap:10px;padding:10px 11px;border-radius:10px;color:var(--muted);font-weight:620}.nav a:hover,.nav a.active{background:var(--accent-soft);color:#dceaff}.nav-icon{width:18px;text-align:center}
.side-status{margin-top:auto;border:1px solid var(--border);border-radius:13px;padding:13px;background:var(--surface-3)}.status-line{display:flex;justify-content:space-between;gap:8px;align-items:center;margin:5px 0;color:var(--muted);font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px var(--ok-soft)}
.main{min-width:0}.topbar{height:68px;padding:0 30px;border-bottom:1px solid var(--border-soft);display:flex;justify-content:space-between;align-items:center;background:rgba(7,16,30,.72);backdrop-filter:blur(14px);position:sticky;top:0;z-index:4}.breadcrumbs{color:var(--muted);font-size:13px}.breadcrumbs strong{color:var(--text)}.top-actions{display:flex;gap:9px;align-items:center}
.content{max-width:1420px;margin:0 auto;padding:28px 30px 56px}.page-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:24px}.page-head h1{margin:0 0 5px;font-size:28px;line-height:1.2;letter-spacing:-.4px}.page-head p{margin:0;color:var(--muted);max-width:760px}
.btn{border:1px solid var(--border);border-radius:10px;padding:9px 14px;background:var(--surface-2);color:var(--text);cursor:pointer;font-weight:700;display:inline-flex;align-items:center;justify-content:center;gap:7px}.btn:hover{border-color:#42658f;background:#172943}.btn.primary{background:linear-gradient(135deg,#3478dc,#6556df);border-color:#568ae5;box-shadow:0 10px 24px rgba(52,120,220,.2)}.btn.good{background:#174b40;border-color:#2e7d69}.btn.danger{background:#51272f;border-color:#8b434f}.btn.small{padding:6px 10px;font-size:12px}.btn[disabled]{opacity:.45;cursor:not-allowed}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border:1px solid var(--border);border-radius:999px;color:var(--muted);font-size:11px;font-weight:760;letter-spacing:.25px;white-space:nowrap}.badge.ok{color:var(--ok);border-color:#2c6d5c;background:var(--ok-soft)}.badge.warn{color:var(--warn);border-color:#745a2f;background:var(--warn-soft)}.badge.bad{color:var(--bad);border-color:#783b44;background:var(--bad-soft)}.badge.accent{color:#aecdff;border-color:#385b8c;background:var(--accent-soft)}
.card{background:linear-gradient(180deg,rgba(18,31,53,.96),rgba(13,25,44,.96));border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow)}.card-pad{padding:20px}.card-head{padding:16px 20px;border-bottom:1px solid var(--border-soft);display:flex;justify-content:space-between;gap:14px;align-items:center}.card-head h2,.card-head h3{margin:0;font-size:15px}.card-sub{color:var(--muted);font-size:12px;margin-top:2px}
.hero{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(280px,.65fr);gap:18px;margin-bottom:18px}.ask-card{padding:25px}.ask-kicker{color:#9bc1ff;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:1px}.ask-card h1{font-size:27px;line-height:1.25;margin:8px 0 8px}.ask-card p{color:var(--muted);margin:0 0 18px}.textarea{width:100%;min-height:155px;resize:vertical;padding:14px 15px;color:var(--text);background:#091426;border:1px solid #2a3b57;border-radius:12px;outline:none}.textarea:focus,.input:focus,.select:focus{border-color:#5c91dc;box-shadow:0 0 0 3px rgba(92,145,220,.12)}.form-row{display:flex;align-items:end;gap:10px;margin-top:11px}.field{display:flex;flex-direction:column;gap:6px}.field.grow{flex:1}.label{color:var(--muted);font-size:11px;font-weight:760;text-transform:uppercase;letter-spacing:.7px}.input,.select{height:39px;padding:0 11px;color:var(--text);background:#0c182b;border:1px solid var(--border);border-radius:9px;outline:none}.select{min-width:145px}
.pipeline{padding:20px}.pipeline h3{margin:0 0 14px;font-size:14px}.flow{display:flex;flex-direction:column;gap:9px}.flow-step{display:flex;gap:10px;align-items:center;padding:9px;border:1px solid var(--border-soft);border-radius:10px;background:rgba(9,20,38,.65)}.flow-num{width:25px;height:25px;display:grid;place-items:center;border-radius:8px;background:var(--accent-soft);color:#aecdff;font-size:11px;font-weight:800}.flow-title{font-weight:720;font-size:12px}.flow-sub{font-size:10px;color:var(--muted)}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0}.metric-card{padding:17px 18px}.metric-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;font-weight:750}.metric-value{font-size:27px;line-height:1.2;font-weight:800;margin-top:7px}.metric-foot{font-size:11px;color:var(--muted);margin-top:4px}
.table-card{overflow:hidden}.table-wrap{overflow:auto}.table{width:100%;border-collapse:collapse}.table th{text-align:left;padding:11px 16px;color:var(--faint);font-size:10px;text-transform:uppercase;letter-spacing:.8px;border-bottom:1px solid var(--border-soft)}.table td{padding:13px 16px;border-bottom:1px solid var(--border-soft);vertical-align:middle}.table tr:last-child td{border-bottom:0}.table tbody tr:hover{background:rgba(110,168,254,.04)}.case-title{font-weight:720}.case-sub{font-size:11px;color:var(--muted);max-width:520px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.empty{padding:42px 20px;text-align:center;color:var(--muted)}
.notice{padding:13px 15px;border:1px solid #2d765f;border-radius:12px;background:var(--ok-soft);color:#bdeedc;margin-bottom:18px}.notice.error{border-color:#7b3c47;background:var(--bad-soft);color:#ffd1d5}
.case-header{padding:22px;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.case-id{font-size:11px;color:#9ec4ff;font-weight:800;text-transform:uppercase;letter-spacing:1px}.case-header h1{font-size:24px;margin:5px 0}.case-question{color:var(--muted);max-width:870px;white-space:pre-wrap}.case-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}
.tabs{display:flex;gap:4px;padding:6px;border:1px solid var(--border);background:var(--surface-3);border-radius:12px;margin:18px 0;overflow:auto}.tab{border:0;background:transparent;color:var(--muted);border-radius:8px;padding:9px 13px;cursor:pointer;font-weight:700;white-space:nowrap}.tab.active{color:var(--text);background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--border)}.tab-panel{display:none}.tab-panel.active{display:block}
.two-col{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(320px,.65fr);gap:16px}.three-col{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.stack{display:flex;flex-direction:column;gap:14px}
.answer-box{padding:22px}.answer-meta{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:16px}.answer-body{font-size:14px;line-height:1.72}.answer-body h2{font-size:17px;margin:23px 0 8px}.answer-body h3{font-size:14px;margin:18px 0 6px}.answer-body p{margin:7px 0}.answer-body ul,.answer-body ol{padding-left:22px}.answer-body li{margin:5px 0}.answer-body code{padding:2px 5px;border-radius:5px;background:#081223;color:#b7d2ff}.review-box{padding:18px}.review-box h3{margin:0 0 8px}.review-form{display:flex;flex-direction:column;gap:8px}.review-form .input{width:100%}.review-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:3px}
.section-title{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:11px}.section-title h2{margin:0;font-size:16px}.section-title h3{margin:0;font-size:14px}.muted{color:var(--muted)}.small{font-size:11px}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.fact{padding:11px 12px;border:1px solid var(--border-soft);border-left:3px solid var(--accent);border-radius:9px;background:#091426;margin:8px 0}.fact.hyp{border-left-color:var(--warn)}.fact.missing{border-left-color:var(--bad)}.fact-code{font-size:11px;color:#aecdff;margin-bottom:4px}.fact-text{font-size:12px}.fact-meta{font-size:10px;color:var(--muted);margin-top:5px}.chip-list{display:flex;gap:6px;flex-wrap:wrap}.checklist{margin:0;padding:0;list-style:none;counter-reset:step}.checklist li{position:relative;margin:0;padding:0 0 15px 39px;counter-increment:step}.checklist li:before{content:counter(step);position:absolute;left:0;top:0;width:27px;height:27px;display:grid;place-items:center;border-radius:8px;background:var(--accent-soft);color:#aecdff;font-size:11px;font-weight:800}.checklist li:not(:last-child):after{content:"";position:absolute;left:13px;top:29px;bottom:2px;width:1px;background:var(--border)}.step-action{font-size:12px;font-weight:690}.step-code{font-size:10px;color:var(--muted);margin-top:3px}.source{padding:12px 0;border-bottom:1px solid var(--border-soft)}.source:last-child{border-bottom:0}.source-title{font-size:12px;font-weight:720;color:#b9d5ff}.source-meta{font-size:10px;color:var(--muted);margin-top:3px}.claim{padding:11px 0;border-bottom:1px solid var(--border-soft)}.claim:last-child{border-bottom:0}.claim-text{font-size:12px}.claim-codes{font-size:10px;color:#aecdff;margin-top:4px}
.status-timeline{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.status-node{padding:7px 10px;border:1px solid var(--border);border-radius:9px;color:var(--muted);font-size:11px;font-weight:700}.status-node.current{border-color:#4777b4;background:var(--accent-soft);color:#cce0ff}.status-arrow{color:var(--faint)}
.footer{padding-top:30px;color:var(--faint);font-size:11px;text-align:center}
.toast{position:fixed;right:22px;bottom:22px;padding:11px 14px;border-radius:10px;background:#183a32;color:#c7f7e6;border:1px solid #2c6d5c;box-shadow:var(--shadow);display:none;z-index:20}
@media(max-width:1050px){.app{grid-template-columns:82px minmax(0,1fr)}.sidebar{padding:20px 10px}.brand-copy,.nav span:not(.nav-icon),.nav-label,.side-status{display:none}.brand{justify-content:center;padding-left:0;padding-right:0}.nav a{justify-content:center}.hero,.two-col{grid-template-columns:1fr}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:720px){.app{display:block}.sidebar{position:static;height:auto;border-right:0;border-bottom:1px solid var(--border);flex-direction:row;align-items:center;padding:11px 14px}.brand{padding:0}.nav{margin-left:auto;flex-direction:row}.nav a{padding:9px}.topbar{display:none}.content{padding:18px 14px 42px}.page-head,.case-header{display:block}.case-actions{justify-content:flex-start;margin-top:14px}.metric-grid,.three-col{grid-template-columns:1fr}.form-row{align-items:stretch;flex-direction:column}.select{width:100%}.ask-card{padding:19px}}
"""

_SCRIPT = r"""
<script>
(function(){
  const tabs = document.querySelectorAll('[data-tab]');
  const panels = document.querySelectorAll('[data-panel]');
  tabs.forEach(btn => btn.addEventListener('click', () => {
    tabs.forEach(x => x.classList.remove('active'));
    panels.forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    const target = document.querySelector('[data-panel="' + btn.dataset.tab + '"]');
    if (target) target.classList.add('active');
    history.replaceState(null, '', '#' + btn.dataset.tab);
  }));
  const requested = location.hash.replace('#','');
  if (requested) {
    const btn = document.querySelector('[data-tab="' + requested + '"]');
    if (btn) btn.click();
  }
  document.querySelectorAll('[data-copy]').forEach(btn => btn.addEventListener('click', async () => {
    const target = document.querySelector(btn.dataset.copy);
    if (!target) return;
    try {
      await navigator.clipboard.writeText(target.innerText);
      const toast = document.getElementById('toast');
      if (toast) { toast.style.display='block'; setTimeout(()=>toast.style.display='none',1800); }
    } catch (e) { btn.textContent='Copy failed'; }
  }));
  const form = document.getElementById('ask-form');
  if (form) form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.disabled=true; button.textContent='Analysing…'; }
  });
})();
</script>
"""


def _json(value: object, fallback: object) -> object:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback


def _fmt_date(value: object) -> str:
    if not value:
        return "—"
    raw = str(value)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%d %b %Y · %H:%M")
    except ValueError:
        return raw[:19].replace("T", " ")


def _short(value: object, length: int = 90) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def _status_badge(status: str | None) -> str:
    value = (status or "unknown").lower()
    cls = "ok" if value in {"valid", "approved", "used", "confirmed"} else "bad" if value in {"invalid", "rejected", "validation_failed"} else "warn" if value in {"warning", "needs_review", "unconfirmed"} else "accent"
    return f"<span class='badge {cls}'>{escape(value.replace('_', ' ').upper())}</span>"


def _format_draft_body(body: str) -> str:
    lines = body.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    list_type: str | None = None

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    for raw in lines:
        line = raw.strip()
        if not line:
            close_list()
            continue
        if line.startswith("## "):
            close_list(); out.append(f"<h2>{escape(line[3:])}</h2>"); continue
        if line.startswith("### "):
            close_list(); out.append(f"<h3>{escape(line[4:])}</h3>"); continue
        if re.match(r"^\d+\.\s+", line):
            if list_type != "ol": close_list(); out.append("<ol>"); list_type = "ol"
            out.append(f"<li>{escape(re.sub(r'^\d+\.\s+', '', line))}</li>"); continue
        if line.startswith(("- ", "* ")):
            if list_type != "ul": close_list(); out.append("<ul>"); list_type = "ul"
            out.append(f"<li>{escape(line[2:])}</li>"); continue
        close_list()
        formatted = escape(line)
        formatted = re.sub(r"`([^`]+)`", r"<code>\1</code>", formatted)
        out.append(f"<p>{formatted}</p>")
    close_list()
    return "".join(out)


def _provider_ready() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_MODEL"))


def _layout(body: str, *, active: str = "assistant", breadcrumb: str = "Assistant", title: str = "Metronome Support Intelligence") -> str:
    gemini = "Ready" if _provider_ready() else "Not configured"
    gemini_dot = "<span class='dot'></span>" if _provider_ready() else "<span class='dot' style='background:var(--warn)'></span>"
    nav = {
        "assistant": ("/", "✦", "Assistant"),
        "cases": ("/cases", "▣", "Case history"),
        "overview": ("/overview", "◫", "System overview"),
    }
    nav_html = "".join(
        f"<a class='{'active' if key == active else ''}' href='{href}'><span class='nav-icon'>{icon}</span><span>{label}</span></a>"
        for key, (href, icon, label) in nav.items()
    )
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{escape(title)}</title><style>{_STYLE}</style></head><body>
<div class='app'>
  <aside class='sidebar'>
    <a href='/' class='brand'><div class='logo'>M</div><div class='brand-copy'><div class='brand-name'>Metronome SI</div><div class='brand-sub'>Support intelligence</div></div></a>
    <div class='nav-label'>Workspace</div><nav class='nav'>{nav_html}</nav>
    <div class='side-status'><div class='status-line'><span>Gemini</span><span>{gemini_dot} {escape(gemini)}</span></div><div class='status-line'><span>Validation</span><span class='badge ok'>ENABLED</span></div><div class='status-line'><span>Review</span><span class='badge accent'>HUMAN</span></div></div>
  </aside>
  <main class='main'>
    <header class='topbar'><div class='breadcrumbs'>Metronome Support Intelligence / <strong>{escape(breadcrumb)}</strong></div><div class='top-actions'><a class='btn small' href='/cases'>Browse saved cases</a><a class='btn small primary' href='/'>New analysis</a></div></header>
    <div class='content'>{body}<div class='footer'>Documentation mapping → deterministic investigation → grounded Gemini communication → human approval</div></div>
  </main>
</div><div id='toast' class='toast'>Copied to clipboard</div>{_SCRIPT}</body></html>"""


def _db() -> DocumentationRepository:
    repo = DocumentationRepository(DB_PATH)
    repo.initialize_schema()
    return repo


def _dashboard_data() -> dict[str, object]:
    repo = _db()
    try:
        conn = repo._get_conn()
        metrics = {
            "articles": conn.execute("SELECT COUNT(*) FROM documentation_pages WHERE status='active'").fetchone()[0],
            "cases": conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0],
            "answers": conn.execute("SELECT COUNT(*) FROM support_generated_drafts WHERE draft_type='support_answer'").fetchone()[0],
            "approved": conn.execute("SELECT COUNT(*) FROM support_generated_drafts WHERE status IN ('approved','used')").fetchone()[0],
        }
        recent = conn.execute(
            """SELECT t.id, t.subject, t.customer_message, t.created_at,
                      d.id AS draft_id, d.status AS draft_status,
                      d.validation_status, d.provider, d.model
               FROM support_tickets t
               LEFT JOIN support_generated_drafts d ON d.id = (
                   SELECT gd.id FROM support_generated_drafts gd
                   WHERE gd.ticket_id = t.id
                   ORDER BY gd.created_at DESC, gd.id DESC LIMIT 1
               )
               ORDER BY t.created_at DESC, t.id DESC LIMIT 7"""
        ).fetchall()
        return {"metrics": metrics, "recent": recent}
    finally:
        repo.close()


def _ask_form(question: str = "", provider: str | None = None) -> str:
    selected = provider or ("gemini" if _provider_ready() else "mock")
    placeholder = "Our ai_usage event was accepted, but no charge appeared. We sent token_cost_usd while the billable metric expects cost_usd."
    return f"""
<section class='card ask-card'>
  <div class='ask-kicker'>Evidence-grounded support intelligence</div>
  <h1>Ask a Metronome question</h1>
  <p>Search the indexed documentation, map the issue to investigation concepts, and create a validated answer with customer and internal communication.</p>
  <form id='ask-form' method='post' action='/ask'>
    <label class='label' for='question'>Question or support issue</label>
    <textarea class='textarea' id='question' name='question' required placeholder='{escape(placeholder)}'>{escape(question)}</textarea>
    <div class='form-row'>
      <div class='field grow'><label class='label' for='provider'>Drafting provider</label><select class='select' id='provider' name='provider'><option value='gemini' {'selected' if selected == 'gemini' else ''}>Gemini live</option><option value='mock' {'selected' if selected == 'mock' else ''}>Deterministic mock</option></select></div>
      <button class='btn primary' type='submit'>✦ Analyse and answer</button>
    </div>
  </form>
</section>"""


def _recent_cases(rows: list[object]) -> str:
    if not rows:
        return "<div class='empty'>No saved cases yet. Ask your first Metronome question above.</div>"
    body = "".join(
        f"""<tr><td><a href='/cases/{row['id']}'><div class='case-title'>Case #{row['id']} · {escape(_short(row['subject'], 62))}</div><div class='case-sub'>{escape(_short(row['customer_message'], 100))}</div></a></td><td>{_status_badge(row['draft_status']) if row['draft_status'] else '<span class="badge">NO DRAFT</span>'}</td><td>{_status_badge(row['validation_status']) if row['validation_status'] else '—'}</td><td><span class='small muted'>{escape(str(row['provider'] or '—'))}</span></td><td><span class='small muted'>{escape(_fmt_date(row['created_at']))}</span></td><td><a class='btn small' href='/cases/{row['id']}'>Open</a></td></tr>"""
        for row in rows
    )
    return f"<div class='table-wrap'><table class='table'><thead><tr><th>Saved case</th><th>Review</th><th>Validation</th><th>Provider</th><th>Created</th><th></th></tr></thead><tbody>{body}</tbody></table></div>"


def _dashboard(error: str | None = None) -> str:
    data = _dashboard_data()
    m = data["metrics"]
    notice = f"<div class='notice error'>{escape(error)}</div>" if error else ""
    metrics = f"""
<section class='metric-grid'>
  <div class='card metric-card'><div class='metric-label'>Documentation</div><div class='metric-value'>{m['articles']}</div><div class='metric-foot'>indexed Metronome articles</div></div>
  <div class='card metric-card'><div class='metric-label'>Saved cases</div><div class='metric-value'>{m['cases']}</div><div class='metric-foot'>questions and issues analysed</div></div>
  <div class='card metric-card'><div class='metric-label'>Grounded answers</div><div class='metric-value'>{m['answers']}</div><div class='metric-foot'>versioned answer records</div></div>
  <div class='card metric-card'><div class='metric-label'>Approved</div><div class='metric-value'>{m['approved']}</div><div class='metric-foot'>human-reviewed communication</div></div>
</section>"""
    pipeline = """
<section class='card pipeline'><h3>Controlled intelligence workflow</h3><div class='flow'>
  <div class='flow-step'><div class='flow-num'>1</div><div><div class='flow-title'>Documentation mapping</div><div class='flow-sub'>Search the indexed Metronome corpus</div></div></div>
  <div class='flow-step'><div class='flow-num'>2</div><div><div class='flow-title'>Deterministic investigation</div><div class='flow-sub'>Evidence, hypotheses, gaps and checks</div></div></div>
  <div class='flow-step'><div class='flow-num'>3</div><div><div class='flow-title'>Grounded Gemini drafting</div><div class='flow-sub'>Answer and communication from allowed facts</div></div></div>
  <div class='flow-step'><div class='flow-num'>4</div><div><div class='flow-title'>Validation and review</div><div class='flow-sub'>Claim map, sources and human approval</div></div></div>
</div></section>"""
    body = f"""
<div class='page-head'><div><h1>Support Intelligence Workspace</h1><p>Turn a Metronome question into a documented investigation and reviewable grounded answer.</p></div>{_status_badge('valid') if _provider_ready() else _status_badge('warning')}</div>
{notice}<section class='hero'>{_ask_form()}{pipeline}</section>{metrics}
<section class='card table-card'><div class='card-head'><div><h2>Recent saved cases</h2><div class='card-sub'>Every analysis and generated answer is retained as a reviewable record.</div></div><a class='btn small' href='/cases'>View all cases</a></div>{_recent_cases(data['recent'])}</section>"""
    return _layout(body, active="assistant", breadcrumb="Assistant")


def _load_case(ticket_id: int) -> dict[str, object] | None:
    repo = _db()
    try:
        conn = repo._get_conn()
        ticket = conn.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
        if ticket is None:
            return None
        evidence = conn.execute("SELECT * FROM support_ticket_evidence WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (ticket_id,)).fetchone()
        analysis = conn.execute("SELECT * FROM support_ticket_analyses WHERE ticket_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (ticket_id,)).fetchone()
        docs = conn.execute("SELECT * FROM support_ticket_document_links WHERE ticket_id=? ORDER BY relevance_score DESC,id", (ticket_id,)).fetchall()
        drafts = conn.execute("SELECT * FROM support_generated_drafts WHERE ticket_id=? ORDER BY created_at DESC,id DESC", (ticket_id,)).fetchall()
        resolution = conn.execute("SELECT * FROM support_ticket_resolutions WHERE ticket_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (ticket_id,)).fetchone()
        return {"ticket": ticket, "evidence": evidence, "analysis": analysis, "docs": docs, "drafts": drafts, "resolution": resolution}
    finally:
        repo.close()


def _render_review(latest: object | None) -> str:
    if latest is None:
        return "<div class='review-box'><h3>No answer stored</h3><p class='muted'>Generate a new analysis from the assistant workspace.</p></div>"
    status = str(latest["status"])
    reviewer = escape(str(latest["reviewed_by"] or ""))
    notes = escape(str(latest["review_notes"] or ""))
    timeline_order = ["needs_review", "approved", "used"]
    nodes = []
    for item in timeline_order:
        cls = "current" if item == status else ""
        nodes.append(f"<span class='status-node {cls}'>{escape(item.replace('_',' ').title())}</span>")
    timeline = "<span class='status-arrow'>→</span>".join(nodes)
    if status == "needs_review":
        actions = f"""<form class='review-form' method='post' action='/drafts/{latest['id']}/review'><label class='label'>Reviewer</label><input class='input' name='reviewer' value='Andrian' required><label class='label'>Review notes</label><input class='input' name='notes' placeholder='Optional review note'><div class='review-actions'><button class='btn good' name='decision' value='approve'>✓ Approve answer</button><button class='btn danger' name='decision' value='reject'>Reject</button></div></form>"""
    elif status == "approved":
        actions = f"""<form class='review-form' method='post' action='/drafts/{latest['id']}/review'><input type='hidden' name='reviewer' value='{reviewer or 'Andrian'}'><input type='hidden' name='notes' value='{notes}'><button class='btn primary' name='decision' value='mark_used'>Mark communication as used</button></form>"""
    else:
        actions = f"<p class='muted'>Reviewed by {reviewer or '—'}{f' · {notes}' if notes else ''}</p>"
    return f"<div class='review-box'><h3>Human review</h3><p class='muted'>Validated drafts remain untrusted until a person approves them.</p><div class='status-timeline'>{timeline}</div><div style='height:14px'></div>{actions}</div>"


def _case_page(ticket_id: int, *, message: str | None = None, error: str | None = None) -> str:
    data = _load_case(ticket_id)
    if data is None:
        return _layout("<div class='notice error'>Case not found.</div><a class='btn' href='/cases'>Back to case history</a>", active="cases", breadcrumb="Case not found")
    t, e, a, docs, drafts, resolution = data["ticket"], data["evidence"], data["analysis"], data["docs"], data["drafts"], data["resolution"]
    latest = drafts[0] if drafts else None
    notice = f"<div class='notice'>{escape(message)}</div>" if message else f"<div class='notice error'>{escape(error)}</div>" if error else ""

    concepts = _json(a["selected_concepts_json"], []) if a else []
    observations = _json(a["observations_json"], []) if a else []
    hypotheses = _json(a["hypotheses_json"], []) if a else []
    missing = _json(a["missing_evidence_json"], []) if a else []
    steps = _json(a["investigation_steps_json"], []) if a else []

    chips = "".join(f"<span class='badge accent'>{escape(str(code))}</span>" for code in concepts) or "<span class='muted'>No concepts mapped.</span>"
    obs_html = "".join(f"<div class='fact'><div class='fact-code'>OBSERVED · {escape(str(item.get('observation_code','')))}</div><div class='fact-text'>{escape(str(item.get('statement','')))}</div></div>" for item in observations) or "<p class='muted'>No observations stored.</p>"
    hyp_html = "".join(f"<div class='fact hyp'><div class='fact-code'>UNCONFIRMED · {escape(str(item.get('hypothesis_code','')))}</div><div class='fact-text'>{escape(str(item.get('title','')))}</div><div class='fact-meta'>{escape(str(item.get('explanation','')))}</div></div>" for item in hypotheses) or "<p class='muted'>No supported hypothesis yet.</p>"
    missing_html = "".join(f"<div class='fact missing'><div class='fact-code'>MISSING · {escape(str(item.get('field','')))}</div><div class='fact-text'>{escape(str(item.get('reason','')))}</div></div>" for item in missing) or "<p class='muted'>No critical evidence gaps.</p>"
    checklist = "".join(f"<li><div class='step-action'>{escape(str(item.get('action','')))}</div><div class='step-code'>{escape(', '.join(str(x) for x in item.get('concept_codes',[])))}</div></li>" for item in steps) or "<li><div class='step-action'>No investigation checklist stored.</div></li>"
    docs_html = "".join(f"<div class='source'><a class='source-title' target='_blank' rel='noreferrer' href='{escape(str(row['source_url']))}'>{escape(str(row['page_title']))}</a><div class='source-meta'>{escape(str(row['heading'] or ''))} · relevance {float(row['relevance_score']):.2f}</div></div>" for row in docs) or "<p class='muted'>No documentation linked.</p>"

    if latest:
        grounding = _json(latest["grounding_package_json"], {})
        facts = []
        for key in ["confirmed_facts", "observed_facts", "documentation_facts", "hypotheses", "missing_evidence"]:
            facts.extend(grounding.get(key, []) if isinstance(grounding, dict) else [])
        fact_html = "".join(f"<div class='fact {'hyp' if item.get('confirmation_status') == 'unconfirmed' else 'missing' if item.get('confirmation_status') == 'missing' else ''}'><div class='fact-code mono'>{escape(str(item.get('fact_code','')))}</div><div class='fact-text'>{escape(str(item.get('statement','')))}</div><div class='fact-meta'>{escape(str(item.get('confirmation_status','')))} · {escape(str(item.get('evidence_reference','')))}</div></div>" for item in facts[:30]) or "<p class='muted'>No grounding facts stored.</p>"
        claims = _json(latest["claim_map_json"], [])
        claims_html = "".join(f"<div class='claim'><div class='claim-text'>{escape(str(item.get('claim','')))}</div><div class='claim-codes mono'>{escape(', '.join(str(x) for x in item.get('fact_codes',[])))}</div></div>" for item in claims) or "<p class='muted'>No claim map stored.</p>"
        errors = _json(latest["validation_errors_json"], [])
        warnings = _json(latest["validation_warnings_json"], [])
        validation_extra = "".join(f"<div class='fact missing'>{escape(str(x))}</div>" for x in errors) + "".join(f"<div class='fact hyp'>{escape(str(x))}</div>" for x in warnings)
        answer_html = f"""<section class='card answer-box'><div class='answer-meta'>{_status_badge(latest['validation_status'])}{_status_badge(latest['status'])}<span class='badge'>{escape(str(latest['provider']))}</span><span class='badge'>{escape(str(latest['model']))}</span><span class='badge accent'>ANSWER #{latest['id']}</span></div><div id='answer-copy' class='answer-body'>{_format_draft_body(str(latest['body']))}</div></section>"""
        review_html = f"<section class='card'>{_render_review(latest)}</section>"
    else:
        fact_html = claims_html = "<p class='muted'>No generated answer exists for this case.</p>"
        validation_extra = ""
        answer_html = "<section class='card answer-box'><p class='muted'>No grounded answer stored.</p></section>"
        review_html = ""

    history_rows = "".join(f"<tr><td>#{row['id']}</td><td>{escape(str(row['provider']))}<div class='case-sub'>{escape(str(row['model']))}</div></td><td>{_status_badge(row['validation_status'])}</td><td>{_status_badge(row['status'])}</td><td><span class='small muted'>{escape(_fmt_date(row['created_at']))}</span></td></tr>" for row in drafts) or "<tr><td colspan='5' class='muted'>No answer versions.</td></tr>"

    resolution_html = "<p class='muted'>No human-confirmed resolution has been recorded for this case.</p>"
    if resolution:
        resolution_html = f"""<div class='fact'><div class='fact-code mono'>{escape(str(resolution['root_cause_code']))}</div><div class='fact-text'>{escape(str(resolution['root_cause_summary']))}</div><div class='fact-meta'>Confirmed by {escape(str(resolution['confirmed_by']))} · {escape(_fmt_date(resolution['confirmed_at']))}</div></div><h3>Resolution</h3><p>{escape(str(resolution['resolution_summary']))}</p>"""

    body = f"""
{notice}
<section class='card case-header'><div><div class='case-id'>Saved support case #{t['id']}</div><h1>{escape(str(t['subject']))}</h1><div class='case-question'>{escape(str(t['customer_message']))}</div><div style='height:12px'></div><div class='chip-list'>{_status_badge(latest['status']) if latest else '<span class="badge">NO ANSWER</span>'}<span class='badge'>Created {escape(_fmt_date(t['created_at']))}</span></div></div><div class='case-actions'><button class='btn' data-copy='#answer-copy' {'disabled' if not latest else ''}>Copy answer</button><a class='btn primary' href='/'>New question</a></div></section>
<div class='tabs'><button class='tab active' data-tab='answer'>Answer</button><button class='tab' data-tab='investigation'>Investigation</button><button class='tab' data-tab='sources'>Sources & grounding</button><button class='tab' data-tab='history'>History & resolution</button></div>
<section class='tab-panel active' data-panel='answer'><div class='two-col'><div>{answer_html}</div><div class='stack'>{review_html}<section class='card card-pad'><div class='section-title'><h3>Record identity</h3></div><div class='fact'><div class='fact-code'>CASE</div><div class='fact-text'>#{t['id']}</div></div><div class='fact'><div class='fact-code'>ANALYSIS</div><div class='fact-text'>#{a['id'] if a else '—'}</div></div><div class='fact'><div class='fact-code'>ANSWER VERSION</div><div class='fact-text'>#{latest['id'] if latest else '—'}</div></div></section></div></div></section>
<section class='tab-panel' data-panel='investigation'><div class='three-col'><section class='card card-pad'><div class='section-title'><h2>Mapped concepts</h2><span class='badge accent'>{len(concepts)}</span></div><div class='chip-list'>{chips}</div></section><section class='card card-pad'><div class='section-title'><h2>Observations</h2><span class='badge ok'>{len(observations)}</span></div>{obs_html}</section><section class='card card-pad'><div class='section-title'><h2>Unconfirmed & missing</h2></div>{hyp_html}{missing_html}</section></div><div style='height:14px'></div><section class='card card-pad'><div class='section-title'><h2>Investigation checklist</h2><span class='badge accent'>{len(steps)} STEPS</span></div><ol class='checklist'>{checklist}</ol></section></section>
<section class='tab-panel' data-panel='sources'><div class='two-col'><section class='card card-pad'><div class='section-title'><h2>Relevant documentation</h2><span class='badge accent'>{len(docs)} SOURCES</span></div>{docs_html}</section><div class='stack'><section class='card card-pad'><div class='section-title'><h2>Grounding facts</h2></div>{fact_html}</section><section class='card card-pad'><div class='section-title'><h2>Claim map & validation</h2>{_status_badge(latest['validation_status']) if latest else ''}</div>{claims_html}{validation_extra}</section></div></div></section>
<section class='tab-panel' data-panel='history'><div class='two-col'><section class='card table-card'><div class='card-head'><div><h2>Answer versions</h2><div class='card-sub'>Every generation is retained for audit and review.</div></div></div><div class='table-wrap'><table class='table'><thead><tr><th>ID</th><th>Provider</th><th>Validation</th><th>Review state</th><th>Created</th></tr></thead><tbody>{history_rows}</tbody></table></div></section><section class='card card-pad'><div class='section-title'><h2>Confirmed resolution</h2>{_status_badge(resolution['resolution_status']) if resolution else ''}</div>{resolution_html}</section></div></section>"""
    return _layout(body, active="cases", breadcrumb=f"Case #{ticket_id}", title=f"Case #{ticket_id} · Metronome SI")


def _cases_page(query: str = "") -> str:
    repo = _db()
    try:
        conn = repo._get_conn()
        params: list[object] = []
        where = ""
        if query:
            where = "WHERE t.subject LIKE ? OR t.customer_message LIKE ?"
            params = [f"%{query}%", f"%{query}%"]
        rows = conn.execute(
            f"""SELECT t.id,t.subject,t.customer_message,t.created_at,
                       d.status AS draft_status,d.validation_status,d.provider,d.model,d.id AS draft_id
                FROM support_tickets t
                LEFT JOIN support_generated_drafts d ON d.id=(SELECT gd.id FROM support_generated_drafts gd WHERE gd.ticket_id=t.id ORDER BY gd.created_at DESC,gd.id DESC LIMIT 1)
                {where} ORDER BY t.created_at DESC,t.id DESC LIMIT 100""",
            params,
        ).fetchall()
    finally:
        repo.close()
    body = f"""<div class='page-head'><div><h1>Saved case history</h1><p>Search and reopen previous questions, investigation evidence, answer versions and review decisions.</p></div><a class='btn primary' href='/'>+ New analysis</a></div><section class='card card-pad'><form method='get' action='/cases' class='form-row'><div class='field grow'><label class='label' for='q'>Search cases</label><input class='input' id='q' name='q' value='{escape(query)}' placeholder='Search question, subject or issue'></div><button class='btn' type='submit'>Search</button></form></section><div style='height:14px'></div><section class='card table-card'>{_recent_cases(rows)}</section>"""
    return _layout(body, active="cases", breadcrumb="Case history")


def _overview_page() -> str:
    data = _dashboard_data(); m = data["metrics"]
    repo = _db()
    try:
        conn = repo._get_conn()
        sections = conn.execute("SELECT COUNT(*) FROM documentation_chunks").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM support_generated_drafts WHERE status='needs_review'").fetchone()[0]
        invalid = conn.execute("SELECT COUNT(*) FROM support_generated_drafts WHERE validation_status='invalid'").fetchone()[0]
    finally:
        repo.close()
    metrics = f"""<section class='metric-grid'><div class='card metric-card'><div class='metric-label'>Articles</div><div class='metric-value'>{m['articles']}</div><div class='metric-foot'>active documentation pages</div></div><div class='card metric-card'><div class='metric-label'>Search chunks</div><div class='metric-value'>{sections}</div><div class='metric-foot'>indexed sections and excerpts</div></div><div class='card metric-card'><div class='metric-label'>Awaiting review</div><div class='metric-value'>{pending}</div><div class='metric-foot'>generated answers needing approval</div></div><div class='card metric-card'><div class='metric-label'>Validation failures</div><div class='metric-value'>{invalid}</div><div class='metric-foot'>blocked unsafe outputs</div></div></section>"""
    body = f"""<div class='page-head'><div><h1>System overview</h1><p>The intelligence engine is deterministic where facts matter and generative only where language helps.</p></div>{_status_badge('valid')}</div>{metrics}<section class='three-col'><div class='card card-pad'><h2>Knowledge layer</h2><p class='muted'>Versioned Metronome documentation, parsed headings, examples, tables and OpenAPI metadata.</p></div><div class='card card-pad'><h2>Investigation layer</h2><p class='muted'>Concept mapping, evidence extraction, hypotheses, missing evidence and adaptive checklists.</p></div><div class='card card-pad'><h2>Communication layer</h2><p class='muted'>Grounded Gemini answers, claim maps, source validation and human approval.</p></div></section>"""
    return _layout(body, active="overview", breadcrumb="System overview")


class AssistantHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)
        if path in {"/", "/assistant", "/investigation", "/drafting"}:
            self._send_html(_dashboard(error=params.get("error", [None])[0]))
            return
        if path == "/cases":
            self._send_html(_cases_page(params.get("q", [""])[0].strip()))
            return
        match = re.fullmatch(r"/cases/(\d+)", path)
        if match:
            self._send_html(_case_page(int(match.group(1)), message=params.get("message", [None])[0], error=params.get("error", [None])[0]))
            return
        if path == "/overview":
            self._send_html(_overview_page())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = self._read_form()
        if path == "/ask":
            self._handle_ask(params)
            return
        match = re.fullmatch(r"/drafts/(\d+)/review", path)
        if match:
            self._handle_review(int(match.group(1)), params)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _handle_ask(self, params: dict[str, list[str]]) -> None:
        question = params.get("question", [""])[0].strip()
        provider = params.get("provider", ["gemini"])[0].strip().lower()
        if not question:
            self._redirect("/?error=" + quote("Enter a question or support issue."))
            return
        try:
            result = answer_metronome_question(question, DB_PATH, provider_name=provider, persist=True)
            if result.investigation.ticket_id is None:
                raise RuntimeError("The analysis completed but the saved case ID was not returned.")
            message = f"Saved as case #{result.investigation.ticket_id} and answer #{result.answer.id}."
            self._redirect(f"/cases/{result.investigation.ticket_id}?message={quote(message)}")
        except Exception as exc:
            self._redirect("/?error=" + quote(str(exc)))

    def _handle_review(self, draft_id: int, params: dict[str, list[str]]) -> None:
        decision = params.get("decision", [""])[0].strip()
        reviewer = params.get("reviewer", ["Andrian"])[0].strip() or "Andrian"
        notes = params.get("notes", [""])[0].strip() or None
        repo = _db()
        try:
            row = repo.get_generated_draft(draft_id)
            ticket_id = int(row["ticket_id"]) if row and row["ticket_id"] is not None else None
        finally:
            repo.close()
        if ticket_id is None:
            self._redirect("/cases?error=" + quote(f"Draft {draft_id} is not linked to a saved case."))
            return
        try:
            updated = review_generated_draft(draft_id=draft_id, decision=decision, reviewer=reviewer, notes=notes, database_path=DB_PATH)
            self._redirect(f"/cases/{ticket_id}?message={quote(f'Answer #{draft_id} is now {updated.status}.')}#answer")
        except Exception as exc:
            self._redirect(f"/cases/{ticket_id}?error={quote(str(exc))}#answer")

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return parse_qs(raw)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(self, content: str, status: int = 200) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def _check() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1
    repo = _db()
    try:
        conn = repo._get_conn()
        articles = repo.count_documentation_pages()
        cases = conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0]
        drafts = conn.execute("SELECT COUNT(*) FROM support_generated_drafts").fetchone()[0]
    finally:
        repo.close()
    print(f"Application ready. Documentation articles: {articles}")
    print(f"Saved cases: {cases}; generated drafts: {drafts}")
    print(f"Gemini configured: {'yes' if _provider_ready() else 'no'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Metronome Support Intelligence.")
    parser.add_argument("--check", action="store_true", help="Validate configuration without starting the server.")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(_check())
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run scripts/sync_documentation.py and scripts/process_documentation.py first.")
        raise SystemExit(1)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), AssistantHandler)
    print("Metronome Support Intelligence")
    print(f"Open: http://127.0.0.1:{PORT}")
    print("Questions, analyses, documentation links, grounded answers and reviews are persisted.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
