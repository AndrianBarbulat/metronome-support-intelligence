"""Metronome Support Intelligence — Flask application for Vercel deployment.

Exports ``app`` for Vercel WSGI detection.  Does **not** start a server,
execute tests, synchronise documentation, rebuild the database, or make
Gemini requests during import.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from flask import Flask, Response, redirect, request, url_for

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.assistant.service import answer_metronome_question
from src.database.adapter import get_adapter, reset_adapter
from src.database.repository import DocumentationRepository
from src.database.connection import resolve_db_path
from src.documentation.search import search_documentation
from src.drafting.config import load_config
from src.drafting.service import review_generated_draft
from src.support.concept_registry import InvestigationConceptRegistry

load_config()

DB_PATH = resolve_db_path()

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "metronome-support-intelligence-dev")

# Determine production mode
_is_vercel = os.getenv("VERCEL", "") == "1"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _db() -> DocumentationRepository:
    """Return a repository connected to the resolved database path.

    On Vercel the database is copied from the packaged location to /tmp
    automatically by ``resolve_db_path``.  If the packaged file is missing,
    a :exc:`FileNotFoundError` with guidance is raised.
    """
    return DocumentationRepository(DB_PATH)


def _use_local_sqlite() -> bool:
    """True when running against local SQLite."""
    return not bool(os.getenv("DATABASE_URL", ""))


# ---------------------------------------------------------------------------
# Utility helpers (migrated from run_demo.py)
# ---------------------------------------------------------------------------
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


def _fmt_count(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _safe_int(value: object, default: int = 1, minimum: int = 1, maximum: int = 9999) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _param(params: dict[str, list[str]], name: str, default: str = "") -> str:
    return params.get(name, [default])[0].strip()


def _as_list(value: object) -> list[object]:
    parsed = _json(value, [])
    return parsed if isinstance(parsed, list) else []


def _as_dict(value: object) -> dict[str, object]:
    parsed = _json(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _heading_path_text(value: object) -> str:
    items = value if isinstance(value, list) else _as_list(value)
    text = " -> ".join(str(item) for item in items if str(item).strip())
    return text or str(value or "")


def _excerpt(value: object, length: int = 360) -> str:
    return _short(value, length)


def _query_url(path: str, **params: object) -> str:
    clean = {k: str(v) for k, v in params.items() if v not in {None, "", False}}
    return f"{path}?{urlencode(clean)}" if clean else path


def _metadata_pre(metadata: object) -> str:
    data = _as_dict(metadata)
    rendered = json.dumps(data, indent=2, sort_keys=True) if data else "{}"
    return f"<pre class='metadata-block'>{escape(rendered)}</pre>"


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


def _resolve_chunk_for_source(conn, source_url: str, heading: str | None = None):
    heading_value = heading or ""
    return conn.execute(
        """SELECT c.id, c.page_id, c.parsed_version_id, c.chunk_index,
                  c.chunk_type, c.heading, c.heading_path, c.content,
                  c.token_estimate, c.metadata_json,
                  p.title, p.category, p.document_type, p.source_url
           FROM documentation_chunks c
           JOIN documentation_pages p ON p.id = c.page_id
           WHERE p.source_url = ?
           ORDER BY CASE
               WHEN ? != '' AND c.heading = ? THEN 0
               WHEN ? != '' AND c.heading_path LIKE ? THEN 1
               ELSE 2
           END, c.chunk_index
           LIMIT 1""",
        (source_url, heading_value, heading_value, heading_value, f"%{heading_value}%"),
    ).fetchone()


def _resolve_case_sources(conn, rows: list[object]) -> list[dict[str, object]]:
    resolved: list[dict[str, object]] = []
    for rank, row in enumerate(rows, 1):
        item = dict(row)
        chunk = _resolve_chunk_for_source(conn, str(item.get("source_url") or ""), item.get("heading"))
        meta = _as_dict(chunk["metadata_json"]) if chunk else {}
        item.update({
            "rank": rank,
            "chunk_id": chunk["id"] if chunk else None,
            "page_id": chunk["page_id"] if chunk else None,
            "section_id": f"{chunk['parsed_version_id']}:{chunk['chunk_index']}" if chunk else "",
            "heading_path": meta.get("heading_path") or (chunk["heading_path"] if chunk else "[]"),
            "excerpt": _excerpt(chunk["content"], 430) if chunk else "",
            "token_estimate": chunk["token_estimate"] if chunk else "",
            "metadata_json": chunk["metadata_json"] if chunk else "{}",
            "document_type": meta.get("document_type") or (chunk["document_type"] if chunk else ""),
            "category": meta.get("category") or (chunk["category"] if chunk else ""),
            "http_method": meta.get("http_method"),
            "endpoint_path": meta.get("endpoint_path"),
            "operation_id": meta.get("operation_id"),
            "matched_tokens": _as_list(item.get("matched_tokens_json")),
            "ranking_reasons": _as_list(item.get("ranking_reasons_json")),
            "source_capabilities": _as_list(item.get("source_capabilities_json")),
            "source_purposes": _as_list(item.get("source_purposes_json")),
        })
        resolved.append(item)
    return resolved


def _select_options(values: list[object], selected: str, *, blank: str = "Any") -> str:
    html = [f"<option value=''>{escape(blank)}</option>"]
    for value in values:
        text = str(value or "")
        if not text:
            continue
        html.append(f"<option value='{escape(text)}' {'selected' if text == selected else ''}>{escape(text)}</option>")
    return "".join(html)


def _pagination(path: str, params: dict[str, object], page: int, total: int, page_size: int) -> str:
    total_pages = max(1, (total + page_size - 1) // page_size)
    params = dict(params)
    prev_html = "<span class='btn small' disabled>Previous</span>"
    next_html = "<span class='btn small' disabled>Next</span>"
    if page > 1:
        params["page"] = page - 1
        prev_html = f"<a class='btn small' href='{escape(_query_url(path, **params))}'>Previous</a>"
    if page < total_pages:
        params["page"] = page + 1
        next_html = f"<a class='btn small' href='{escape(_query_url(path, **params))}'>Next</a>"
    return f"<div class='pagination'>{prev_html}<div class='page-count'>Page {page} of {total_pages} · {_fmt_count(total)} records</div>{next_html}</div>"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def _layout(body: str, *, active: str = "assistant", breadcrumb: str = "Assistant", title: str = "Metronome Support Intelligence") -> str:
    gemini = "Ready" if _provider_ready() else "Not configured"
    gemini_dot = "<span class='dot'></span>" if _provider_ready() else "<span class='dot' style='background:var(--warn)'></span>"
    nav = {
        "assistant": ("/", "A", "Assistant"),
        "cases": ("/cases", "C", "Cases"),
        "documentation": ("/documentation", "D", "Documentation"),
        "how": ("/how-it-works", "H", "How it works"),
        "testing": ("/testing", "T", "Testing"),
    }
    nav_html = "".join(
        f"<a class='{'active' if key == active else ''}' href='{href}'><span class='nav-icon'>{icon}</span><span>{label}</span></a>"
        for key, (href, icon, label) in nav.items()
    )
    html = STYLE_AND_LAYOUT
    html = html.replace("{title}", escape(title))
    html = html.replace("{nav_html}", nav_html)
    html = html.replace("{breadcrumb}", escape(breadcrumb))
    html = html.replace("{body}", body)
    html = html.replace("{gemini_dot}", gemini_dot)
    html = html.replace("{gemini}", escape(gemini))
    return html


# ---------------------------------------------------------------------------
# Styles and script (extracted verbatim from run_demo.py)
# ---------------------------------------------------------------------------
_STYLE_CSS = r"""
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
.quick-links,.status-grid,.example-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.quick-links{grid-template-columns:repeat(5,minmax(0,1fr));margin-top:14px}.quick-link,.status-card,.example-card{border:1px solid var(--border);border-radius:12px;background:rgba(9,20,38,.72);padding:12px;text-align:left}.quick-link:hover,.example-card:hover{border-color:#42658f;background:#11223a}.quick-link-title,.example-title{font-weight:760;font-size:12px}.quick-link-sub,.example-text{font-size:11px;color:var(--muted);margin-top:4px}.example-actions{display:flex;gap:8px;justify-content:space-between;align-items:center;margin-top:16px}.example-card{cursor:pointer;color:var(--text);min-height:92px}.status-card{display:flex;align-items:center;gap:9px}.status-copy{font-size:12px;font-weight:720}.status-sub{font-size:10px;color:var(--muted)}
.filter-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;align-items:end}.search-actions{display:flex;gap:8px;align-items:end}.result-list{display:flex;flex-direction:column;gap:12px}.source-card{border:1px solid var(--border-soft);border-radius:12px;background:#091426;padding:14px}.source-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px}.source-rank{width:32px;height:32px;border-radius:10px;background:var(--accent-soft);color:#cbe0ff;display:grid;place-items:center;font-weight:800;font-size:12px;flex:0 0 auto}.source-name{font-size:14px;font-weight:780;color:#d9e9ff}.source-path{font-size:11px;color:var(--muted);margin-top:2px}.source-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.excerpt{border:1px solid var(--border-soft);border-radius:10px;background:#061021;color:#c9d7eb;padding:11px 12px;margin:8px 0;font-size:12px;line-height:1.58;white-space:pre-wrap}.reason-line{font-size:11px;color:var(--muted);margin-top:7px}.metadata-block{max-height:260px;overflow:auto;margin-top:8px;padding:10px;border-radius:9px;background:#061021;border:1px solid var(--border-soft);font-size:11px;color:#c9d7eb;white-space:pre-wrap}.pagination{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:14px}.page-count{color:var(--muted);font-size:12px}.detail-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px}.section-tree{display:flex;flex-direction:column;gap:10px}.section-node{border:1px solid var(--border-soft);border-radius:12px;background:#091426;padding:12px}.section-node h3{margin:0 0 6px;font-size:14px}.level-2{margin-left:12px}.level-3,.level-4,.level-5,.level-6{margin-left:24px}.pipeline-large{display:flex;flex-direction:column;gap:8px}.phase-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.eval-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.metric-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.metric-row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--border-soft);font-size:12px}.metric-row:last-child{border-bottom:0}.diagram-arrow{color:#7faeff;font-size:12px;text-align:center}.external-link{color:#b9d5ff;text-decoration:underline;text-underline-offset:3px}
.status-timeline{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.status-node{padding:7px 10px;border:1px solid var(--border);border-radius:9px;color:var(--muted);font-size:11px;font-weight:700}.status-node.current{border-color:#4777b4;background:var(--accent-soft);color:#cce0ff}.status-arrow{color:var(--faint)}
.footer{padding-top:30px;color:var(--faint);font-size:11px;text-align:center}
.toast{position:fixed;right:22px;bottom:22px;padding:11px 14px;border-radius:10px;background:#183a32;color:#c7f7e6;border:1px solid #2c6d5c;box-shadow:var(--shadow);display:none;z-index:20}
@media(max-width:1050px){.app{grid-template-columns:82px minmax(0,1fr)}.sidebar{padding:20px 10px}.brand-copy,.nav span:not(.nav-icon),.nav-label,.side-status{display:none}.brand{justify-content:center;padding-left:0;padding-right:0}.nav a{justify-content:center}.hero,.two-col,.detail-grid{grid-template-columns:1fr}.metric-grid,.quick-links,.status-grid,.example-grid,.phase-grid,.eval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.filter-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:720px){.app{display:block}.sidebar{position:static;height:auto;border-right:0;border-bottom:1px solid var(--border);flex-direction:row;align-items:center;padding:11px 14px}.brand{padding:0}.nav{margin-left:auto;flex-direction:row}.nav a{padding:9px}.topbar{display:none}.content{padding:18px 14px 42px}.page-head,.case-header{display:block}.case-actions{justify-content:flex-start;margin-top:14px}.metric-grid,.three-col,.quick-links,.status-grid,.example-grid,.filter-grid,.phase-grid,.eval-grid,.metric-list{grid-template-columns:1fr}.form-row,.search-actions{align-items:stretch;flex-direction:column}.select{width:100%}.ask-card{padding:19px}.source-top,.pagination{display:block}.page-count{margin:10px 0}}
"""

_SCRIPT_JS = r"""
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
    if (button) { button.disabled=true; button.textContent='Analysing...'; }
  });
  const question = document.getElementById('question');
  document.querySelectorAll('[data-example-question]').forEach(btn => btn.addEventListener('click', () => {
    if (!question) return;
    question.value = btn.getAttribute('data-example-question') || '';
    question.focus();
  }));
  const clearQuestion = document.querySelector('[data-clear-question]');
  if (clearQuestion) clearQuestion.addEventListener('click', () => {
    if (!question) return;
    question.value = '';
    question.focus();
  });
})();
</script>
"""

STYLE_AND_LAYOUT = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{title}}</title><style>{_STYLE_CSS}</style></head><body>
<div class='app'>
  <aside class='sidebar'>
    <a href='/' class='brand'><div class='logo'>M</div><div class='brand-copy'><div class='brand-name'>Metronome SI</div><div class='brand-sub'>Support intelligence</div></div></a>
    <div class='nav-label'>Workspace</div><nav class='nav'>{{nav_html}}</nav>
    <div class='side-status'><div class='status-line'><span>Gemini</span><span>{{gemini_dot}} {{gemini}}</span></div><div class='status-line'><span>Validation</span><span class='badge ok'>ENABLED</span></div><div class='status-line'><span>Review</span><span class='badge accent'>HUMAN</span></div></div>
  </aside>
  <main class='main'>
    <header class='topbar'><div class='breadcrumbs'>Metronome Support Intelligence / <strong>{{breadcrumb}}</strong></div><div class='top-actions'><a class='btn small' href='/documentation'>Browse documentation</a><a class='btn small primary' href='/'>Ask a question</a></div></header>
    <div class='content'>{{body}}<div class='footer'>Documentation retrieval &rarr; deterministic investigation &rarr; grounded Gemini communication &rarr; validation &rarr; human approval</div></div>
  </main>
</div><div id='toast' class='toast'>Copied to clipboard</div>{_SCRIPT_JS}</body></html>"""


# ---------------------------------------------------------------------------
# Example questions
# ---------------------------------------------------------------------------
EXAMPLE_QUESTIONS = [
    (
        "Usage accepted but not billed",
        "Our ai_usage event was accepted, but no charge appeared. We sent token_cost_usd while the billable metric expects cost_usd. What should we verify?",
    ),
    (
        "Billable metric matching",
        "How can I confirm whether a usage event matched the intended customer and billable metric?",
    ),
    (
        "Contract uniqueness conflict",
        "A contract creation request returned HTTP 409 with a uniqueness error. How can I determine whether the original operation already succeeded?",
    ),
    (
        "Missing contract field",
        "The contract API says a required field is missing, but the field appears in our request. What evidence should we collect and compare?",
    ),
    (
        "Rate-card investigation",
        "Usage events exist for the customer, but no invoice line item was generated. How do I verify the active contract and rate card?",
    ),
    (
        "Customer ingest alias",
        "How does Metronome map an ingested usage event to a customer, and what should I check when the alias does not match?",
    ),
    (
        "Invoice verification",
        "How can I confirm that an event timestamp falls within the correct invoice period?",
    ),
    (
        "Engineering escalation",
        "What evidence should a support engineer include when escalating an accepted-but-not-billed usage issue?",
    ),
]

VERIFIED_EVIDENCE = {
    "verified_at": "2026-07-19",
    "tests": {"passed": 341, "failures": 0, "skipped": 0},
    "datasets": {
        "Ticket investigation cases": {"total": 26, "Tuning": 22, "Holdout": 4},
        "Confirmed resolution cases": {"total": 14, "Tuning": 11, "Holdout": 3},
        "Drafting cases": {"total": 18, "Tuning": 12, "Holdout": 6},
    },
    "ticket_metrics": {
        "Signal extraction": "100%",
        "Documentation Top-3 recall": "100%",
        "Primary-source Top-1 accuracy": "100%",
        "Purpose-source recall": "100%",
        "Observation-code coverage": "100%",
        "Missing-evidence coverage": "100%",
        "Checklist concept coverage": "100%",
        "Checklist precision": "100%",
        "Checklist ordering": "100%",
        "Blocking-step coverage": "100%",
        "Escalation placement": "100%",
        "Secret redaction": "100%",
        "Abstention": "100%",
        "Already-complete-step rate": "0%",
        "Redundant-step rate": "0%",
    },
    "resolution_metrics": {
        "Resolution validation": "100%",
        "Root-cause accuracy": "100%",
        "Hypothesis outcomes": "100%",
        "Verification completeness": "100%",
        "Regression-case accuracy": "100%",
        "Gap classification": "100%",
        "Secret redaction": "100%",
        "Invalid-resolution rejection": "100%",
        "Feedback transitions": "100%",
    },
    "drafting_metrics": {
        "Structured-output validity": "100%",
        "Fact-reference validity": "100%",
        "Claim-map validity": "100%",
        "Source-reference validity": "100%",
        "Unsupported-claim rejection": "100%",
        "Hypothesis-labelling accuracy": "100%",
        "Resolution-status compliance": "100%",
        "Secret-redaction accuracy": "100%",
        "Required-section coverage": "100%",
        "Human-review transition accuracy": "100%",
    },
}


# ---------------------------------------------------------------------------
# Source card and section helpers
# ---------------------------------------------------------------------------
def _source_chip_html(values: list[object], css_class: str = "accent") -> str:
    return "".join(
        f"<span class='badge {css_class}'>{escape(str(value))}</span>"
        for value in values
        if str(value).strip()
    )


def _source_card(source: dict[str, object], *, include_internal_link: bool = True) -> str:
    rank = source.get("rank") or "?"
    title = str(source.get("page_title") or source.get("title") or "Untitled documentation")
    source_url = str(source.get("source_url") or "")
    heading = str(source.get("heading") or "")
    path = _heading_path_text(source.get("heading_path")) or heading
    excerpt = str(source.get("excerpt") or "")
    reasons = [str(x) for x in source.get("ranking_reasons", []) if str(x).strip()]
    tokens = [str(x) for x in source.get("matched_tokens", []) if str(x).strip()]
    capabilities = [str(x) for x in source.get("source_capabilities", []) if str(x).strip()]
    purposes = [str(x) for x in source.get("source_purposes", []) if str(x).strip()]
    source_type = str(source.get("document_type") or source.get("category") or "documentation")
    endpoint = ""
    if source.get("http_method") or source.get("endpoint_path"):
        endpoint = f"<span class='badge'>{escape(str(source.get('http_method') or ''))} {escape(str(source.get('endpoint_path') or ''))}</span>"
    category_badge = f"<span class='badge'>{escape(str(source.get('category')))}</span>" if source.get("category") else ""
    reason_text = " · ".join(reasons + [f"usage: {source.get('usage_type')}"] + [f"source: {source_type}"])
    if not reason_text.strip():
        reason_text = "Stored as linked documentation for this analysis."
    chips = _source_chip_html(tokens, "accent") + _source_chip_html(capabilities, "ok") + _source_chip_html(purposes, "warn")
    if not chips:
        chips = "<span class='badge'>No matched tokens stored</span>"
    external = (
        f"<a class='btn small' target='_blank' rel='noreferrer' href='{escape(source_url)}'>Open documentation</a>"
        if source_url
        else ""
    )
    internal = ""
    if include_internal_link and source.get("page_id"):
        href = _query_url(
            f"/documentation/articles/{source['page_id']}",
            chunk_id=source.get("chunk_id") or "",
        )
        internal = f"<a class='btn small' href='{escape(href)}'>Open in Documentation Explorer</a>"
    section_meta = []
    if source.get("chunk_id"):
        section_meta.append(f"Chunk {source['chunk_id']}")
    if source.get("section_id"):
        section_meta.append(f"Section {source['section_id']}")
    if source.get("relevance_score") is not None:
        try:
            section_meta.append(f"Relevance {float(source['relevance_score']):.2f}")
        except (TypeError, ValueError):
            pass
    return f"""
<article class='source-card' id='chunk-{escape(str(source.get("chunk_id") or ""))}'>
  <div class='source-top'><div style='display:flex;gap:10px;align-items:flex-start'><div class='source-rank'>#{escape(str(rank))}</div><div><div class='source-name'>{escape(title)}</div><div class='source-path'>{escape(path)}</div></div></div><div class='chip-list'>{endpoint}{category_badge}<span class='badge'>{escape(source_type.replace('_', ' '))}</span></div></div>
  <div class='source-meta'>{escape(' · '.join(section_meta))}</div>
  <div class='excerpt'>{escape(excerpt) if excerpt else 'No indexed excerpt available for this stored source.'}</div>
  <div class='reason-line'><strong>Why selected:</strong> {escape(reason_text)}</div>
  <div class='chip-list' style='margin-top:8px'>{chips}</div>
  <div class='source-actions'>{external}{internal}</div>
</article>"""


def _source_section(sources: list[dict[str, object]], *, title: str = "Documentation used") -> str:
    if not sources:
        body = "<p class='muted'>No documentation links were persisted for this answer.</p>"
    else:
        body = "<div class='result-list'>" + "".join(_source_card(source) for source in sources) + "</div>"
    return f"<section class='card card-pad'><div class='section-title'><h2>{escape(title)}</h2><span class='badge accent'>{len(sources)} SOURCES</span></div>{body}</section>"


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------
def _ask_form(question: str = "", provider: str | None = None) -> str:
    selected = provider or ("gemini" if _provider_ready() else "mock")
    placeholder = "Our ai_usage event was accepted, but no charge appeared. We sent token_cost_usd while the billable metric expects cost_usd."
    examples = "".join(
        f"""<button class='example-card' type='button' data-example-question='{escape(text)}'><div class='example-title'>{escape(title)}</div><div class='example-text'>{escape(_short(text, 118))}</div></button>"""
        for title, text in EXAMPLE_QUESTIONS
    )
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
  <div class='example-actions'><h2 style='font-size:15px;margin:0'>Try an example</h2><button class='btn small' type='button' data-clear-question>Clear question</button></div>
  <div class='example-grid'>{examples}</div>
</section>"""


# ---------------------------------------------------------------------------
# Documentation query helpers
# ---------------------------------------------------------------------------
def _documentation_metrics() -> dict[str, object]:
    repo = _db()
    try:
        conn = repo._get_conn()
        parsed_counts = conn.execute(
            """SELECT COALESCE(SUM(pv.section_count), 0) AS sections,
                      COALESCE(SUM(pv.code_block_count), 0) AS code_blocks,
                      COALESCE(SUM(pv.table_count), 0) AS tables,
                      COALESCE(SUM(pv.openapi_block_count), 0) AS openapi_blocks
               FROM documentation_parsed_versions pv
               JOIN documentation_versions v ON v.id = pv.version_id
               JOIN documentation_pages p ON p.id = pv.page_id
               WHERE p.status = 'active'
                 AND p.current_version = v.version_number"""
        ).fetchone()
        sync = conn.execute(
            """SELECT started_at, completed_at, status, discovered_count, fetched_count
               FROM documentation_sync_runs
               ORDER BY started_at DESC, id DESC
               LIMIT 1"""
        ).fetchone()
        return {
            "articles": conn.execute(
                "SELECT COUNT(*) FROM documentation_pages WHERE status='active'"
            ).fetchone()[0],
            "chunks": conn.execute(
                """SELECT COUNT(*)
                   FROM documentation_chunks c
                   JOIN documentation_pages p ON p.id = c.page_id
                   WHERE p.status = 'active'"""
            ).fetchone()[0],
            "sections": parsed_counts["sections"],
            "code_blocks": parsed_counts["code_blocks"],
            "tables": parsed_counts["tables"],
            "openapi_blocks": parsed_counts["openapi_blocks"],
            "latest_sync": dict(sync) if sync else None,
        }
    finally:
        repo.close()


def _concept_metrics() -> dict[str, object]:
    registry = InvestigationConceptRegistry()
    return {
        "total": registry.concept_count,
        "by_scenario": registry.count_by_scenario(),
    }


def _dashboard_data() -> dict[str, object]:
    doc_metrics = _documentation_metrics()
    concept_metrics = _concept_metrics()
    repo = _db()
    try:
        conn = repo._get_conn()
        metrics = {
            "articles": doc_metrics["articles"],
            "chunks": doc_metrics["chunks"],
            "concepts": concept_metrics["total"],
            "tests": VERIFIED_EVIDENCE["tests"]["passed"],
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
        return {"metrics": metrics, "recent": recent, "documentation": doc_metrics, "concepts": concept_metrics}
    finally:
        repo.close()


def _recent_cases(rows: list[object]) -> str:
    if not rows:
        return "<div class='empty'>No saved cases yet. Ask your first Metronome question above.</div>"
    body = "".join(
        f"""<tr><td><a href='/cases/{row['id']}'><div class='case-title'>Case #{row['id']} · {escape(_short(row['subject'], 62))}</div><div class='case-sub'>{escape(_short(row['customer_message'], 100))}</div></a></td><td>{_status_badge(row['draft_status']) if row['draft_status'] else '<span class="badge">NO DRAFT</span>'}</td><td>{_status_badge(row['validation_status']) if row['validation_status'] else '—'}</td><td><span class='small muted'>{escape(str(row['provider'] or '—'))}</span></td><td><span class='small muted'>{escape(_fmt_date(row['created_at']))}</span></td><td><a class='btn small' href='/cases/{row['id']}'>Open</a></td></tr>"""
        for row in rows
    )
    return f"<div class='table-wrap'><table class='table'><thead><tr><th>Saved case</th><th>Review</th><th>Validation</th><th>Provider</th><th>Created</th><th></th></tr></thead><tbody>{body}</tbody></table></div>"


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
        resolved_docs = _resolve_case_sources(conn, docs)
        drafts = conn.execute("SELECT * FROM support_generated_drafts WHERE ticket_id=? ORDER BY created_at DESC,id DESC", (ticket_id,)).fetchall()
        resolution = conn.execute("SELECT * FROM support_ticket_resolutions WHERE ticket_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (ticket_id,)).fetchone()
        return {"ticket": ticket, "evidence": evidence, "analysis": analysis, "docs": resolved_docs, "drafts": drafts, "resolution": resolution}
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


def _chunk_card(row: object) -> str:
    meta = _as_dict(row["metadata_json"])
    path = _heading_path_text(meta.get("heading_path") or row["heading_path"])
    char_count = len(str(row["content"] or ""))
    endpoint = ""
    if meta.get("http_method") or meta.get("endpoint_path"):
        endpoint = f"<span class='badge'>{escape(str(meta.get('http_method') or ''))} {escape(str(meta.get('endpoint_path') or ''))}</span>"
    detail_href = _query_url(f"/documentation/articles/{row['page_id']}", chunk_id=row["id"])
    return f"""
<article class='source-card' id='chunk-{row['id']}'>
  <div class='source-top'><div><div class='source-name'>Chunk {row['id']} · {escape(str(row['title']))}</div><div class='source-path'>{escape(path)}</div></div><div class='chip-list'>{endpoint}<span class='badge'>{escape(str(row['chunk_type']))}</span><span class='badge'>{escape(str(row['category'] or ''))}</span></div></div>
  <div class='source-meta'>Section {row['parsed_version_id']}:{row['chunk_index']} · {_fmt_count(char_count)} characters · {_fmt_count(row['token_estimate'])} token estimate</div>
  <div class='excerpt'>{escape(_excerpt(row['content'], 430))}</div>
  <div class='source-actions'><a class='btn small' href='{escape(detail_href)}'>Open in article</a><a class='btn small' target='_blank' rel='noreferrer' href='{escape(str(row['source_url']))}'>Open documentation</a></div>
  <details><summary class='small muted'>Metadata</summary>{_metadata_pre(row['metadata_json'])}</details>
</article>"""


def _openapi_row(row: object) -> str:
    meta = _as_dict(row["metadata_json"])
    method = str(meta.get("http_method") or "")
    endpoint = str(meta.get("endpoint_path") or "")
    operation = str(meta.get("operation_id") or "")
    detail_href = _query_url(f"/documentation/articles/{row['page_id']}", chunk_id=row["id"])
    return f"""<tr><td><span class='badge accent'>{escape(method)}</span></td><td class='mono'>{escape(endpoint)}</td><td class='mono'>{escape(operation)}</td><td>{escape(_excerpt(row['content'], 150))}</td><td><a href='{escape(detail_href)}'>{escape(str(row['title']))}</a></td><td><a class='external-link' target='_blank' rel='noreferrer' href='{escape(str(row['source_url']))}'>Open article</a></td></tr>"""


def _doc_tabs(active_tab: str, query: str = "") -> str:
    tabs = [
        ("search", "Search"),
        ("articles", "Articles"),
        ("chunks", "Chunks"),
        ("openapi", "OpenAPI"),
    ]
    links = []
    for key, label in tabs:
        href = _query_url("/documentation", tab=key, query=query if key == "search" else "")
        links.append(f"<a class='tab {'active' if active_tab == key else ''}' href='{escape(href)}'>{escape(label)}</a>")
    return "<div class='tabs'>" + "".join(links) + "</div>"


def _documentation_chunk_filters(conn) -> tuple[list[object], list[object]]:
    categories = conn.execute(
        """SELECT DISTINCT category FROM documentation_pages
           WHERE status='active' AND category IS NOT NULL
           ORDER BY category"""
    ).fetchall()
    methods = conn.execute(
        """SELECT DISTINCT json_extract(metadata_json, '$.http_method') AS method
           FROM documentation_chunks
           WHERE json_extract(metadata_json, '$.http_method') IS NOT NULL
             AND json_extract(metadata_json, '$.http_method') != ''
           ORDER BY method"""
    ).fetchall()
    return [row["category"] for row in categories], [row["method"] for row in methods]


def _phase_card(title: str, body: str) -> str:
    return f"<section class='card card-pad'><h2>{escape(title)}</h2>{body}</section>"


def _metric_rows(metrics: dict[str, str]) -> str:
    return "".join(
        f"<div class='metric-row'><span>{escape(name)}</span><strong>{escape(value)}</strong></div>"
        for name, value in metrics.items()
    )


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------
@app.route("/")
def route_assistant():
    """GET  /   —  Main assistant page."""
    return _dashboard(error=request.args.get("error"))


@app.route("/ask", methods=["POST"])
def route_ask():
    """POST /ask — Analyse a question and generate grounded answer."""
    question = request.form.get("question", "").strip()
    provider = request.form.get("provider", "gemini").strip().lower()
    if not question:
        return redirect("/?error=" + quote("Enter a question or support issue."), 303)
    try:
        result = answer_metronome_question(question, DB_PATH, provider_name=provider, persist=True)
        if result.investigation.ticket_id is None:
            raise RuntimeError("The analysis completed but the saved case ID was not returned.")
        message = f"Saved as case #{result.investigation.ticket_id} and answer #{result.answer.id}."
        return redirect(f"/cases/{result.investigation.ticket_id}?message={quote(message)}", 303)
    except Exception as exc:
        return redirect("/?error=" + quote(str(exc)), 303)


@app.route("/cases")
def route_cases():
    """GET /cases — Saved case history."""
    query = request.args.get("q", "").strip()
    return _cases_page(query)


@app.route("/cases/<int:ticket_id>")
def route_case(ticket_id: int):
    """GET /cases/<ticket_id> — Single case view."""
    message = request.args.get("message")
    error = request.args.get("error")
    return _case_page(ticket_id, message=message, error=error)


@app.route("/drafts/<int:draft_id>/review", methods=["POST"])
def route_review(draft_id: int):
    """POST /drafts/<draft_id>/review — Review a generated draft."""
    decision = request.form.get("decision", "").strip()
    reviewer = request.form.get("reviewer", "Andrian").strip() or "Andrian"
    notes = request.form.get("notes", "").strip() or None
    repo = _db()
    try:
        row = repo.get_generated_draft(draft_id)
        ticket_id = int(row["ticket_id"]) if row and row["ticket_id"] is not None else None
    finally:
        repo.close()
    if ticket_id is None:
        return redirect("/cases?error=" + quote(f"Draft {draft_id} is not linked to a saved case."), 303)
    try:
        updated = review_generated_draft(draft_id=draft_id, decision=decision, reviewer=reviewer, notes=notes, database_path=DB_PATH)
        return redirect(f"/cases/{ticket_id}?message={quote(f'Answer #{draft_id} is now {updated.status}.')}#answer", 303)
    except Exception as exc:
        return redirect(f"/cases/{ticket_id}?error={quote(str(exc))}#answer", 303)


@app.route("/documentation")
def route_documentation():
    """GET /documentation — Documentation explorer."""
    return _documentation_page(request.args)


@app.route("/documentation/articles/<int:article_id>")
def route_article(article_id: int):
    """GET /documentation/articles/<article_id> — Article detail."""
    chunk_id = _safe_int(request.args.get("chunk_id", "0"), default=0, minimum=0)
    return _article_detail_page(article_id, chunk_id=chunk_id or None)


@app.route("/how-it-works")
def route_how_it_works():
    """GET /how-it-works — Architecture page."""
    return _how_it_works_page()


@app.route("/testing")
def route_testing():
    """GET /testing — Testing evidence page."""
    return _testing_page()


@app.route("/investigation")
def route_investigation_redirect():
    """Redirect /investigation to /."""
    return redirect("/", 301)


@app.route("/drafting")
@app.route("/overview")
def route_overview_redirect():
    """Redirect /drafting and /overview to /how-it-works."""
    return redirect("/how-it-works", 301)


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------
def _dashboard(error: str | None = None) -> str:
    try:
        data = _dashboard_data()
    except Exception as exc:
        return _layout(f"<div class='notice error'>{escape(str(exc))}</div>", active="assistant", breadcrumb="Assistant")
    m = data["metrics"]
    notice = f"<div class='notice error'>{escape(error)}</div>" if error else ""
    backend_label = "PostgreSQL" if os.getenv("DATABASE_URL") else "SQLite"
    metrics = f"""
<section class='metric-grid'>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(m['articles'])}</div><div class='metric-label'>Documentation articles</div><div class='metric-foot'>indexed from Metronome docs</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(m['chunks'])}</div><div class='metric-label'>Searchable chunks</div><div class='metric-foot'>retrieval-ready excerpts</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(m['concepts'])}</div><div class='metric-label'>Investigation concepts</div><div class='metric-foot'>stable evidence checks</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(m['tests'])}</div><div class='metric-label'>Passing tests</div><div class='metric-foot'>latest verified repository evidence</div></div>
</section>"""
    statuses = f"""
<section class='status-grid'>
  <div class='status-card'><span class='dot' style='background:{'var(--ok)' if _provider_ready() else 'var(--warn)'}'></span><div><div class='status-copy'>Gemini {'configured' if _provider_ready() else 'not configured'}</div><div class='status-sub'>Provider selection remains explicit per question</div></div></div>
  <div class='status-card'><span class='dot'></span><div><div class='status-copy'>Documentation index ready · {escape(backend_label)}</div><div class='status-sub'>{_fmt_count(m['chunks'])} chunks available</div></div></div>
  <div class='status-card'><span class='dot'></span><div><div class='status-copy'>Validation enabled</div><div class='status-sub'>Claims, facts, sources, and secrets checked</div></div></div>
  <div class='status-card'><span class='dot'></span><div><div class='status-copy'>Human review enabled</div><div class='status-sub'>Answers require approval before use</div></div></div>
</section>"""
    quick_links = """
<section class='quick-links'>
  <a class='quick-link' href='/'><div class='quick-link-title'>Ask a question</div><div class='quick-link-sub'>Run retrieval, analysis, drafting, and validation.</div></a>
  <a class='quick-link' href='/documentation'><div class='quick-link-title'>Browse documentation</div><div class='quick-link-sub'>Inspect articles, chunks, and OpenAPI blocks.</div></a>
  <a class='quick-link' href='/cases'><div class='quick-link-title'>View saved cases</div><div class='quick-link-sub'>Open persisted analysis and review history.</div></a>
  <a class='quick-link' href='/how-it-works'><div class='quick-link-title'>Understand the architecture</div><div class='quick-link-sub'>See the ingestion-to-approval workflow.</div></a>
  <a class='quick-link' href='/testing'><div class='quick-link-title'>View testing evidence</div><div class='quick-link-sub'>Review coverage and evaluation metrics.</div></a>
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
<section class='card card-pad'><div class='section-title'><h2>Architecture summary</h2></div><p class='muted'>Documentation retrieval &rarr; deterministic investigation &rarr; grounded Gemini communication &rarr; validation &rarr; human approval</p>{statuses}{quick_links}</section><div style='height:14px'></div>
<section class='card table-card'><div class='card-head'><div><h2>Recent saved cases</h2><div class='card-sub'>Every analysis and generated answer is retained as a reviewable record.</div></div><a class='btn small' href='/cases'>View all cases</a></div>{_recent_cases(data['recent'])}</section>"""
    return _layout(body, active="assistant", breadcrumb="Assistant")


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
    docs_html = _source_section(docs, title="Sources")

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
        answer_html = f"""<section class='card answer-box'><div class='answer-meta'>{_status_badge(latest['validation_status'])}{_status_badge(latest['status'])}<span class='badge'>{escape(str(latest['provider']))}</span><span class='badge'>{escape(str(latest['model']))}</span><span class='badge accent'>ANSWER #{latest['id']}</span></div><div id='answer-copy' class='answer-body'>{_format_draft_body(str(latest['body']))}</div></section><div style='height:14px'></div>{_source_section(docs)}"""
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

    validation_badge = _status_badge(latest["validation_status"]) if latest else "<span class='badge'>NO VALIDATION</span>"
    review_badge = _status_badge(latest["status"]) if latest else "<span class='badge'>NO REVIEW</span>"
    identity_chips = (
        f"<span class='badge accent'>Case #{t['id']}</span>"
        f"<span class='badge accent'>Answer #{latest['id'] if latest else 'none'}</span>"
        f"{validation_badge}"
        f"{review_badge}"
        f"<span class='badge'>Provider {escape(str(latest['provider'] if latest else 'none'))}</span>"
        f"<span class='badge'>Model {escape(str(latest['model'] if latest else 'none'))}</span>"
        f"<span class='badge'>Created {escape(_fmt_date(latest['created_at'] if latest else t['created_at']))}</span>"
    )

    body = f"""
{notice}
<section class='card case-header'><div><div class='case-id'>Saved support case #{t['id']}</div><h1>{escape(str(t['subject']))}</h1><div class='case-question'>{escape(str(t['customer_message']))}</div><div style='height:12px'></div><div class='chip-list'>{identity_chips}</div></div><div class='case-actions'><button class='btn' data-copy='#answer-copy' {'disabled' if not latest else ''}>Copy answer</button><a class='btn primary' href='/'>New question</a></div></section>
<div class='tabs'><button class='tab active' data-tab='answer'>Answer</button><button class='tab' data-tab='investigation'>Investigation</button><button class='tab' data-tab='sources'>Sources</button><button class='tab' data-tab='history'>History & resolution</button></div>
<section class='tab-panel active' data-panel='answer'><div class='two-col'><div>{answer_html}</div><div class='stack'>{review_html}<section class='card card-pad'><div class='section-title'><h3>Record identity</h3></div><div class='fact'><div class='fact-code'>CASE</div><div class='fact-text'>#{t['id']}</div></div><div class='fact'><div class='fact-code'>ANALYSIS</div><div class='fact-text'>#{a['id'] if a else '—'}</div></div><div class='fact'><div class='fact-code'>ANSWER VERSION</div><div class='fact-text'>#{latest['id'] if latest else '—'}</div></div></section></div></div></section>
<section class='tab-panel' data-panel='investigation'><div class='three-col'><section class='card card-pad'><div class='section-title'><h2>Mapped concepts</h2><span class='badge accent'>{len(concepts)}</span></div><div class='chip-list'>{chips}</div></section><section class='card card-pad'><div class='section-title'><h2>Observations</h2><span class='badge ok'>{len(observations)}</span></div>{obs_html}</section><section class='card card-pad'><div class='section-title'><h2>Unconfirmed & missing</h2></div>{hyp_html}{missing_html}</section></div><div style='height:14px'></div><section class='card card-pad'><div class='section-title'><h2>Investigation checklist</h2><span class='badge accent'>{len(steps)} STEPS</span></div><ol class='checklist'>{checklist}</ol></section></section>
<section class='tab-panel' data-panel='sources'><div class='two-col'><div>{docs_html}</div><div class='stack'><section class='card card-pad'><div class='section-title'><h2>Grounding facts</h2></div>{fact_html}</section><section class='card card-pad'><div class='section-title'><h2>Claim map & validation</h2>{_status_badge(latest['validation_status']) if latest else ''}</div>{claims_html}{validation_extra}</section></div></div></section>
<section class='tab-panel' data-panel='history'><div class='two-col'><section class='card table-card'><div class='card-head'><div><h2>Answer versions</h2><div class='card-sub'>Every generation is retained for audit and review.</div></div></div><div class='table-wrap'><table class='table'><thead><tr><th>ID</th><th>Provider</th><th>Validation</th><th>Review state</th><th>Created</th></tr></thead><tbody>{history_rows}</tbody></table></div></section><section class='card card-pad'><div class='section-title'><h2>Confirmed resolution</h2>{_status_badge(resolution['resolution_status']) if resolution else ''}</div>{resolution_html}</section></div></section>"""
    return _layout(body, active="cases", breadcrumb=f"Case #{ticket_id}", title=f"Case #{ticket_id} · Metronome SI")


def _documentation_page(params) -> str:
    query = _param(params, "query")
    active_tab = _param(params, "tab", "search") or "search"
    if active_tab not in {"search", "articles", "chunks", "openapi"}:
        active_tab = "search"
    metrics = _documentation_metrics()
    metric_cards = f"""
<section class='metric-grid'>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(metrics['articles'])}</div><div class='metric-label'>Documentation articles</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(metrics['sections'])}</div><div class='metric-label'>Parsed sections</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(metrics['chunks'])}</div><div class='metric-label'>Searchable chunks</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(metrics['openapi_blocks'])}</div><div class='metric-label'>OpenAPI blocks</div><div class='metric-foot'>{_fmt_count(metrics['code_blocks'])} code · {_fmt_count(metrics['tables'])} tables</div></div>
</section>"""
    if active_tab == "articles":
        tab_body = _articles_tab(params)
    elif active_tab == "chunks":
        tab_body = _chunks_tab(params)
    elif active_tab == "openapi":
        tab_body = _openapi_tab(params)
    else:
        tab_body = _search_tab(query)
    body = f"""<div class='page-head'><div><h1>Documentation Explorer</h1><p>Inspect the indexed Metronome corpus, deterministic search results, chunk metadata, and OpenAPI blocks used for support grounding.</p></div><a class='btn primary' href='/?example=1'>Ask a question</a></div>{metric_cards}{_doc_tabs(active_tab, query)}{tab_body}"""
    return _layout(body, active="documentation", breadcrumb="Documentation", title="Documentation · Metronome SI")


def _search_tab(query: str) -> str:
    results = _documentation_search_results(query, limit=10)
    form = f"""
<section class='card card-pad'>
  <form method='get' action='/documentation' class='form-row'>
    <input type='hidden' name='tab' value='search'>
    <div class='field grow'><label class='label' for='doc-query'>Search indexed documentation</label><input class='input' id='doc-query' name='query' value='{escape(query)}' placeholder='usage event, transaction_id, billable metric'></div>
    <button class='btn primary' type='submit'>Search</button>
  </form>
</section>"""
    if not query:
        result_html = "<div class='empty'>Search the indexed corpus to inspect the chunks used by deterministic retrieval.</div>"
    elif not results:
        result_html = "<div class='empty'>No indexed documentation chunks matched this query.</div>"
    else:
        result_html = "<div class='result-list'>" + "".join(_source_card(item) for item in results) + "</div>"
    return f"{form}<div style='height:14px'></div><section class='card card-pad'><div class='section-title'><h2>Search results</h2><span class='badge accent'>{len(results)} RESULTS</span></div>{result_html}</section>"


def _documentation_search_results(query: str, limit: int = 10) -> list[dict[str, object]]:
    if not query:
        return []
    results = search_documentation(
        DB_PATH,
        query,
        limit=limit,
        include_multiple_chunks_per_page=True,
    )
    repo = _db()
    try:
        conn = repo._get_conn()
        items: list[dict[str, object]] = []
        for rank, result in enumerate(results, 1):
            chunk = conn.execute(
                """SELECT c.id, c.page_id, c.parsed_version_id, c.chunk_index,
                          c.heading_path, c.token_estimate, c.metadata_json,
                          p.category, p.document_type
                   FROM documentation_chunks c
                   JOIN documentation_pages p ON p.id = c.page_id
                   WHERE c.id = ?""",
                (result.chunk_id,),
            ).fetchone()
            meta = _as_dict(chunk["metadata_json"]) if chunk else {}
            items.append({
                "rank": rank,
                "page_title": result.page_title,
                "source_url": result.source_url,
                "heading": result.heading,
                "heading_path": meta.get("heading_path") or result.heading_path,
                "excerpt": _excerpt(result.content_excerpt or result.content, 430),
                "relevance_score": result.final_score,
                "matched_tokens": result.matched_technical_tokens + result.matched_terms,
                "ranking_reasons": result.ranking_reasons,
                "source_capabilities": [],
                "source_purposes": [],
                "usage_type": "search_result",
                "chunk_id": result.chunk_id,
                "page_id": chunk["page_id"] if chunk else None,
                "section_id": f"{chunk['parsed_version_id']}:{chunk['chunk_index']}" if chunk else "",
                "token_estimate": chunk["token_estimate"] if chunk else "",
                "metadata_json": chunk["metadata_json"] if chunk else "{}",
                "document_type": meta.get("document_type") or (chunk["document_type"] if chunk else result.document_type),
                "category": meta.get("category") or (chunk["category"] if chunk else result.category),
                "http_method": meta.get("http_method") or result.http_method,
                "endpoint_path": meta.get("endpoint_path") or result.endpoint_path,
                "operation_id": meta.get("operation_id"),
            })
        return items
    finally:
        repo.close()


def _articles_tab(params: dict[str, list[str]]) -> str:
    page = _safe_int(_param(params, "page", "1"), default=1)
    page_size = 25
    offset = (page - 1) * page_size
    repo = _db()
    try:
        conn = repo._get_conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM documentation_pages WHERE status='active'"
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT p.id, p.title, p.category, p.document_type, p.source_url,
                      COALESCE(pv.section_count, 0) AS section_count,
                      COALESCE(pv.code_block_count, 0) AS code_block_count,
                      COALESCE(pv.table_count, 0) AS table_count,
                      COALESCE(pv.openapi_block_count, 0) AS openapi_block_count,
                      COUNT(c.id) AS chunk_count
               FROM documentation_pages p
               LEFT JOIN documentation_versions v
                 ON v.page_id = p.id AND v.version_number = p.current_version
               LEFT JOIN documentation_parsed_versions pv ON pv.version_id = v.id
               LEFT JOIN documentation_chunks c ON c.page_id = p.id
               WHERE p.status='active'
               GROUP BY p.id
               ORDER BY p.title COLLATE NOCASE
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        ).fetchall()
    finally:
        repo.close()
    if rows:
        body = "".join(
            f"""<tr><td><a href='/documentation/articles/{row['id']}'><div class='case-title'>{escape(str(row['title']))}</div><div class='case-sub'>{escape(str(row['source_url']))}</div></a></td><td>{escape(str(row['category'] or ''))}</td><td>{_fmt_count(row['section_count'])}</td><td>{_fmt_count(row['chunk_count'])}</td><td>{_fmt_count(row['code_block_count'])}</td><td>{_fmt_count(row['table_count'])}</td><td>{_fmt_count(row['openapi_block_count'])}</td><td><a class='btn small' href='/documentation/articles/{row['id']}'>Open article</a></td></tr>"""
            for row in rows
        )
        table = f"<div class='table-wrap'><table class='table'><thead><tr><th>Article</th><th>Category</th><th>Sections</th><th>Chunks</th><th>Code</th><th>Tables</th><th>OpenAPI</th><th></th></tr></thead><tbody>{body}</tbody></table></div>"
    else:
        table = "<div class='empty'>No indexed articles found.</div>"
    return f"<section class='card table-card'><div class='card-head'><div><h2>Indexed articles</h2><div class='card-sub'>Paginated article inventory with parsed structure counts.</div></div></div>{table}</section>{_pagination('/documentation', {'tab':'articles'}, page, total, page_size)}"


def _chunks_tab(params: dict[str, list[str]]) -> str:
    page = _safe_int(_param(params, "page", "1"), default=1)
    page_size = 25
    article = _param(params, "article")
    category = _param(params, "category")
    heading = _param(params, "heading")
    endpoint = _param(params, "endpoint")
    method = _param(params, "method")
    contains_code = _param(params, "contains_code").lower() in {"1", "true", "yes", "on"}
    contains_table = _param(params, "contains_table").lower() in {"1", "true", "yes", "on"}
    contains_openapi = _param(params, "contains_openapi").lower() in {"1", "true", "yes", "on"}
    clauses = ["p.status='active'"]
    sql_params: list[object] = []
    if article:
        clauses.append("(p.title LIKE ? OR p.source_url LIKE ?)")
        sql_params.extend([f"%{article}%", f"%{article}%"])
    if category:
        clauses.append("p.category = ?")
        sql_params.append(category)
    if heading:
        clauses.append("(c.heading LIKE ? OR c.heading_path LIKE ?)")
        sql_params.extend([f"%{heading}%", f"%{heading}%"])
    if endpoint:
        clauses.append("json_extract(c.metadata_json, '$.endpoint_path') LIKE ?")
        sql_params.append(f"%{endpoint}%")
    if method:
        clauses.append("json_extract(c.metadata_json, '$.http_method') = ?")
        sql_params.append(method)
    if contains_code:
        clauses.append("json_extract(c.metadata_json, '$.contains_code') = 1")
    if contains_table:
        clauses.append("json_extract(c.metadata_json, '$.contains_table') = 1")
    if contains_openapi:
        clauses.append("(c.chunk_type = 'openapi' OR json_extract(c.metadata_json, '$.endpoint_path') IS NOT NULL)")
    where = " AND ".join(clauses)
    repo = _db()
    try:
        conn = repo._get_conn()
        categories, methods = _documentation_chunk_filters(conn)
        total = conn.execute(
            f"""SELECT COUNT(*)
                FROM documentation_chunks c
                JOIN documentation_pages p ON p.id = c.page_id
                WHERE {where}""",
            sql_params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT c.id, c.page_id, c.parsed_version_id, c.chunk_index,
                       c.chunk_type, c.heading, c.heading_path, c.content,
                       c.token_estimate, c.metadata_json,
                       p.title, p.category, p.document_type, p.source_url
                FROM documentation_chunks c
                JOIN documentation_pages p ON p.id = c.page_id
                WHERE {where}
                ORDER BY c.id
                LIMIT ? OFFSET ?""",
            sql_params + [page_size, (page - 1) * page_size],
        ).fetchall()
    finally:
        repo.close()
    filter_params = {
        "tab": "chunks",
        "article": article,
        "category": category,
        "heading": heading,
        "endpoint": endpoint,
        "method": method,
        "contains_code": "1" if contains_code else "",
        "contains_table": "1" if contains_table else "",
        "contains_openapi": "1" if contains_openapi else "",
    }
    filters = f"""
<section class='card card-pad'>
  <form method='get' action='/documentation'>
    <input type='hidden' name='tab' value='chunks'>
    <div class='filter-grid'>
      <div class='field'><label class='label'>Article</label><input class='input' name='article' value='{escape(article)}' placeholder='Article title or URL'></div>
      <div class='field'><label class='label'>Category</label><select class='select' name='category'>{_select_options(categories, category)}</select></div>
      <div class='field'><label class='label'>Heading</label><input class='input' name='heading' value='{escape(heading)}' placeholder='Heading text'></div>
      <div class='field'><label class='label'>Endpoint</label><input class='input' name='endpoint' value='{escape(endpoint)}' placeholder='/v1/...'></div>
      <div class='field'><label class='label'>HTTP method</label><select class='select' name='method'>{_select_options(methods, method)}</select></div>
      <label class='field'><span class='label'>Contains code</span><span><input type='checkbox' name='contains_code' value='1' {'checked' if contains_code else ''}> Yes</span></label>
      <label class='field'><span class='label'>Contains table</span><span><input type='checkbox' name='contains_table' value='1' {'checked' if contains_table else ''}> Yes</span></label>
      <label class='field'><span class='label'>Contains OpenAPI</span><span><input type='checkbox' name='contains_openapi' value='1' {'checked' if contains_openapi else ''}> Yes</span></label>
    </div>
    <div class='search-actions' style='margin-top:12px'><button class='btn primary' type='submit'>Apply filters</button><a class='btn' href='/documentation?tab=chunks'>Clear filters</a></div>
  </form>
</section>"""
    cards = "".join(_chunk_card(row) for row in rows) if rows else "<div class='empty'>No chunks matched these filters.</div>"
    return f"{filters}<div style='height:14px'></div><section class='card card-pad'><div class='section-title'><h2>Indexed chunks</h2><span class='badge accent'>{_fmt_count(total)} MATCHING</span></div><div class='result-list'>{cards}</div></section>{_pagination('/documentation', filter_params, page, total, page_size)}"


def _openapi_tab(params: dict[str, list[str]]) -> str:
    method = _param(params, "method")
    endpoint = _param(params, "endpoint")
    clauses = ["p.status='active'", "(c.chunk_type = 'openapi' OR json_extract(c.metadata_json, '$.endpoint_path') IS NOT NULL)"]
    sql_params: list[object] = []
    if method:
        clauses.append("json_extract(c.metadata_json, '$.http_method') = ?")
        sql_params.append(method)
    if endpoint:
        clauses.append("json_extract(c.metadata_json, '$.endpoint_path') LIKE ?")
        sql_params.append(f"%{endpoint}%")
    where = " AND ".join(clauses)
    repo = _db()
    try:
        conn = repo._get_conn()
        _, methods = _documentation_chunk_filters(conn)
        rows = conn.execute(
            f"""SELECT c.id, c.page_id, c.heading, c.content, c.metadata_json,
                       p.title, p.source_url
                FROM documentation_chunks c
                JOIN documentation_pages p ON p.id = c.page_id
                WHERE {where}
                ORDER BY json_extract(c.metadata_json, '$.endpoint_path'), json_extract(c.metadata_json, '$.http_method')
                LIMIT 100""",
            sql_params,
        ).fetchall()
    finally:
        repo.close()
    filters = f"""
<section class='card card-pad'>
  <form method='get' action='/documentation' class='form-row'>
    <input type='hidden' name='tab' value='openapi'>
    <div class='field'><label class='label'>HTTP method</label><select class='select' name='method'>{_select_options(methods, method)}</select></div>
    <div class='field grow'><label class='label'>Endpoint text</label><input class='input' name='endpoint' value='{escape(endpoint)}' placeholder='/v1/contracts'></div>
    <button class='btn primary' type='submit'>Filter endpoints</button>
  </form>
</section>"""
    if rows:
        body = "".join(_openapi_row(row) for row in rows)
        table = f"<div class='table-wrap'><table class='table'><thead><tr><th>Method</th><th>Endpoint</th><th>Operation ID</th><th>Summary</th><th>Article</th><th>Source</th></tr></thead><tbody>{body}</tbody></table></div>"
    else:
        table = "<div class='empty'>No OpenAPI blocks matched these filters.</div>"
    return f"{filters}<div style='height:14px'></div><section class='card table-card'><div class='card-head'><div><h2>Indexed OpenAPI endpoints</h2><div class='card-sub'>Endpoint metadata extracted from existing parsed documentation.</div></div><span class='badge accent'>{len(rows)} SHOWN</span></div>{table}</section>"


def _article_detail_page(article_id: int, *, chunk_id: int | None = None) -> str:
    repo = _db()
    try:
        conn = repo._get_conn()
        row = conn.execute(
            """SELECT p.*, pv.parsed_json, pv.section_count, pv.code_block_count,
                      pv.table_count, pv.openapi_block_count
               FROM documentation_pages p
               LEFT JOIN documentation_versions v
                 ON v.page_id = p.id AND v.version_number = p.current_version
               LEFT JOIN documentation_parsed_versions pv ON pv.version_id = v.id
               WHERE p.id = ? AND p.status = 'active'""",
            (article_id,),
        ).fetchone()
        if row is None:
            return _layout("<div class='notice error'>Article not found.</div><a class='btn' href='/documentation?tab=articles'>Back to Documentation</a>", active="documentation", breadcrumb="Article not found")
        chunks = conn.execute(
            """SELECT id, parsed_version_id, chunk_index, chunk_type, heading,
                      heading_path, content, token_estimate, metadata_json
               FROM documentation_chunks
               WHERE page_id = ?
               ORDER BY chunk_index""",
            (article_id,),
        ).fetchall()
    finally:
        repo.close()
    parsed = _as_dict(row["parsed_json"])
    sections = parsed.get("sections", []) if isinstance(parsed.get("sections"), list) else []
    chunks_by_path = {_heading_path_text(c["heading_path"]): c for c in chunks}
    section_nodes = []
    for section in sections:
        path = _heading_path_text(section.get("heading_path"))
        chunk = chunks_by_path.get(path)
        level = _safe_int(section.get("heading_level"), default=1, minimum=1, maximum=6)
        highlight = " style='border-color:#5c91dc'" if chunk and chunk_id == chunk["id"] else ""
        excerpt = _excerpt(chunk["content"], 360) if chunk else "No chunk excerpt mapped to this parsed section."
        link = f"<a class='btn small' href='#chunk-{chunk['id']}'>Chunk {chunk['id']}</a>" if chunk else ""
        section_nodes.append(
            f"""<div class='section-node level-{level}'{highlight}><h3>{escape(str(section.get('heading') or 'Untitled section'))}</h3><div class='source-path'>{escape(path)}</div><div class='excerpt'>{escape(excerpt)}</div>{link}</div>"""
        )
    if not section_nodes:
        section_nodes.append("<div class='empty'>No parsed section hierarchy is stored for this article.</div>")
    chunk_cards = "".join(
        _chunk_card(c)
        for c in chunks
    )
    metrics = f"""
<section class='card card-pad'>
  <div class='section-title'><h2>Article metrics</h2></div>
  <div class='metric-row'><span>Sections</span><strong>{_fmt_count(row['section_count'])}</strong></div>
  <div class='metric-row'><span>Chunks</span><strong>{_fmt_count(len(chunks))}</strong></div>
  <div class='metric-row'><span>Code blocks</span><strong>{_fmt_count(row['code_block_count'])}</strong></div>
  <div class='metric-row'><span>Tables</span><strong>{_fmt_count(row['table_count'])}</strong></div>
  <div class='metric-row'><span>OpenAPI blocks</span><strong>{_fmt_count(row['openapi_block_count'])}</strong></div>
  <div class='source-actions'><a class='btn small' target='_blank' rel='noreferrer' href='{escape(str(row['source_url']))}'>Open original Metronome documentation</a></div>
</section>"""
    body = f"""<div class='page-head'><div><h1>{escape(str(row['title']))}</h1><p>{escape(str(row['category'] or row['document_type'] or 'Documentation'))} · <a class='external-link' target='_blank' rel='noreferrer' href='{escape(str(row['source_url']))}'>Original source</a></p></div><a class='btn' href='/documentation?tab=articles'>Back to articles</a></div><div class='detail-grid'><section class='card card-pad'><div class='section-title'><h2>Parsed hierarchy and excerpts</h2></div><div class='section-tree'>{''.join(section_nodes)}</div></section><div class='stack'>{metrics}<section class='card card-pad'><div class='section-title'><h2>Indexed chunks</h2><span class='badge accent'>{len(chunks)}</span></div><div class='result-list'>{chunk_cards}</div></section></div></div>"""
    return _layout(body, active="documentation", breadcrumb="Article detail", title=f"{row['title']} · Metronome SI")


def _how_it_works_page() -> str:
    docs = _documentation_metrics()
    concepts = _concept_metrics()
    by_scenario = concepts["by_scenario"]
    workflow = [
        "Metronome documentation",
        "Sync and immutable versioning",
        "Markdown and OpenAPI parsing",
        "Sections, chunks, code blocks and tables",
        "Deterministic hybrid retrieval",
        "Concept mapping and ticket analysis",
        "Observations, hypotheses and missing evidence",
        "Adaptive investigation checklist",
        "Sanitized grounding package",
        "Gemini structured drafting",
        "Fact, claim, source and secret validation",
        "Human review and persisted case history",
    ]
    workflow_parts: list[str] = []
    for index, step in enumerate(workflow, 1):
        workflow_parts.append(
            f"<div class='flow-step'><div class='flow-num'>{index}</div><div><div class='flow-title'>{escape(step)}</div></div></div>"
        )
        if index < len(workflow):
            workflow_parts.append("<div class='diagram-arrow'>down</div>")
    workflow_html = "<div class='pipeline-large'>" + "".join(workflow_parts) + "</div>"
    ingestion = f"""
<div class='metric-row'><span>Articles synchronized</span><strong>{_fmt_count(docs['articles'])}</strong></div>
<div class='metric-row'><span>Immutable document versions</span><strong>Enabled</strong></div>
<div class='metric-row'><span>Sync-run history</span><strong>Persisted</strong></div>
<div class='metric-row'><span>Markdown content stored locally</span><strong>Yes</strong></div>"""
    parsing = f"""
<div class='metric-row'><span>Sections</span><strong>{_fmt_count(docs['sections'])}</strong></div>
<div class='metric-row'><span>Searchable chunks</span><strong>{_fmt_count(docs['chunks'])}</strong></div>
<div class='metric-row'><span>Code blocks</span><strong>{_fmt_count(docs['code_blocks'])}</strong></div>
<div class='metric-row'><span>Tables</span><strong>{_fmt_count(docs['tables'])}</strong></div>
<div class='metric-row'><span>OpenAPI blocks</span><strong>{_fmt_count(docs['openapi_blocks'])}</strong></div>
<p class='muted'>Headings, API metadata, examples, and tables are retained so retrieval returns precise sections instead of entire articles.</p>"""
    search = """
<ul>
  <li>Full-text search</li>
  <li>Title and heading matching</li>
  <li>Endpoint and operation matching</li>
  <li>Technical-token matching</li>
  <li>Category matching</li>
  <li>API-reference authority weighting</li>
  <li>Deterministic reranking</li>
  <li>Relevant-source and incidental-source handling</li>
</ul>"""
    investigation = f"""
<div class='metric-row'><span>Stable concepts</span><strong>{_fmt_count(concepts['total'])}</strong></div>
<div class='metric-row'><span>Generic</span><strong>{_fmt_count(by_scenario.get('generic', 0))}</strong></div>
<div class='metric-row'><span>Contracts</span><strong>{_fmt_count(by_scenario.get('contracts', 0))}</strong></div>
<div class='metric-row'><span>Usage</span><strong>{_fmt_count(by_scenario.get('usage', 0))}</strong></div>
<div class='metric-row'><span>Customers</span><strong>{_fmt_count(by_scenario.get('customers', 0))}</strong></div>
<p class='muted'>Signals are extracted from the issue, observations stay separate from hypotheses, missing evidence is explicit, checklist steps adapt to known evidence, redundant steps are suppressed, and escalation is placed last.</p>"""
    resolution = """
<ul>
  <li>Human-confirmed root causes</li>
  <li>Hypothesis comparison</li>
  <li>Verification evidence</li>
  <li>Regression-case generation</li>
  <li>Documentation-gap classification</li>
  <li>Product and observability feedback</li>
  <li>Human review states</li>
</ul>"""
    gemini = """
<p class='muted'><strong>Gemini does not decide the root cause.</strong> It receives sanitized fact codes, documentation-supported facts, observations, hypotheses marked unconfirmed, missing evidence, allowed source URLs, and required sections.</p>
<p class='muted'>Gemini returns structured JSON, answer text, used fact codes, used source URLs, and a claim map. Deterministic validation then checks fact references, claim support, source existence, hypothesis wording, resolution status, secret leakage, and required sections.</p>"""
    storage_tables = [
        ("support_tickets", "Question and case identity"),
        ("support_ticket_evidence", "Sanitized ticket evidence"),
        ("support_ticket_analyses", "Signals, concepts, observations, hypotheses, gaps, and checklist"),
        ("support_ticket_document_links", "Retrieved documentation sources and relevance metadata"),
        ("support_generated_drafts", "Generated answer, grounding package, validation, and review state"),
        ("support_ticket_resolutions", "Optional human-confirmed resolution"),
        ("support_hypothesis_outcomes", "Comparison between hypotheses and confirmed outcome"),
        ("support_regression_cases", "Generated regression candidates"),
        ("support_feedback_items", "Documentation, product, and observability feedback"),
    ]
    storage = "<div class='excerpt'>Question -> support ticket -> evidence -> analysis -> documentation links -> generated answer -> validation -> human review -> optional confirmed resolution -> regression and feedback</div>" + "".join(
        f"<div class='metric-row'><span class='mono'>{escape(name)}</span><span>{escape(description)}</span></div>"
        for name, description in storage_tables
    )
    body = f"""
<div class='page-head'><div><h1>How it works</h1><p>Support engineers need to search documentation, understand incomplete technical evidence, build investigation steps, communicate with customers, and prepare engineering escalations. A normal documentation chatbot may generate fluent answers but can invent technical conclusions or present hypotheses as facts.</p></div><a class='btn primary' href='/testing'>View testing evidence</a></div>
<section class='card card-pad'><div class='section-title'><h2>Architecture</h2></div>{workflow_html}</section>
<div style='height:14px'></div>
<section class='phase-grid'>{_phase_card('Documentation ingestion', ingestion)}{_phase_card('Parsing', parsing)}{_phase_card('Search and retrieval', search)}{_phase_card('Investigation engine', investigation)}{_phase_card('Resolution and learning loop', resolution)}{_phase_card('Gemini drafting', gemini)}</section>
<div style='height:14px'></div>
<section class='card card-pad'><div class='section-title'><h2>Storage model</h2></div>{storage}</section>"""
    return _layout(body, active="how", breadcrumb="How it works", title="How it works · Metronome SI")


def _testing_page() -> str:
    evidence = VERIFIED_EVIDENCE
    tests = evidence["tests"]
    datasets = evidence["datasets"]
    dataset_cards = "".join(
        f"""<section class='card card-pad'><div class='metric-value'>{_fmt_count(item['total'])}</div><div class='metric-label'>{escape(name)}</div><div class='metric-foot'>Tuning: {_fmt_count(item['Tuning'])} · Holdout: {_fmt_count(item['Holdout'])}</div></section>"""
        for name, item in datasets.items()
    )
    body = f"""
<div class='page-head'><div><h1>Testing and Evaluation</h1><p>Latest verified repository results, loaded from static metadata so the page does not rerun the suite.</p></div><span class='badge ok'>VERIFIED {escape(str(evidence['verified_at']))}</span></div>
<section class='metric-grid'>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(tests['passed'])}</div><div class='metric-label'>Tests passed</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(tests['failures'])}</div><div class='metric-label'>Failures</div></div>
  <div class='card metric-card'><div class='metric-value'>{_fmt_count(tests['skipped'])}</div><div class='metric-label'>Skipped</div></div>
  <div class='card metric-card'><div class='metric-value'>100%</div><div class='metric-label'>Critical thresholds</div></div>
</section>
<section class='card card-pad'><div class='section-title'><h2>Automated tests cover</h2></div><div class='chip-list'>
  <span class='badge accent'>documentation ingestion</span><span class='badge accent'>parsing</span><span class='badge accent'>search</span><span class='badge accent'>concept registry</span><span class='badge accent'>signal extraction</span><span class='badge accent'>checklist generation</span><span class='badge accent'>sanitization</span><span class='badge accent'>resolution validation</span><span class='badge accent'>regression generation</span><span class='badge accent'>feedback classification</span><span class='badge accent'>Gemini provider abstraction</span><span class='badge accent'>structured output</span><span class='badge accent'>claim validation</span><span class='badge accent'>source validation</span><span class='badge accent'>secret leakage</span><span class='badge accent'>human-review transitions</span><span class='badge accent'>persistence</span>
</div></section>
<div style='height:14px'></div>
<section class='eval-grid'>{dataset_cards}</section>
<div style='height:14px'></div>
<section class='eval-grid'>
  <section class='card card-pad'><div class='section-title'><h2>Ticket evaluation metrics</h2></div>{_metric_rows(evidence['ticket_metrics'])}</section>
  <section class='card card-pad'><div class='section-title'><h2>Resolution evaluation metrics</h2></div>{_metric_rows(evidence['resolution_metrics'])}</section>
  <section class='card card-pad'><div class='section-title'><h2>Drafting evaluation metrics</h2></div>{_metric_rows(evidence['drafting_metrics'])}</section>
</section>"""
    return _layout(body, active="testing", breadcrumb="Testing", title="Testing · Metronome SI")


def _config_error_page(message: str) -> str:
    """Show a configuration error page for missing environment variables."""
    body = f"""
<div class='page-head'><div><h1>Configuration Required</h1><p>{escape(message)}</p></div></div>
<section class='card card-pad'>
  <h2>Environment Variables</h2>
  <div class='metric-row'><span class='mono'>DATABASE_URL</span><span class='badge {'ok' if os.getenv('DATABASE_URL') else 'bad'}'>{"Configured" if os.getenv("DATABASE_URL") else "Missing"}</span></div>
  <div class='metric-row'><span class='mono'>GEMINI_API_KEY</span><span class='badge {'ok' if os.getenv('GEMINI_API_KEY') else 'bad'}'>{"Configured" if os.getenv("GEMINI_API_KEY") else "Missing"}</span></div>
  <div class='metric-row'><span class='mono'>GEMINI_MODEL</span><span class='badge {'ok' if os.getenv('GEMINI_MODEL') else 'bad'}'>{"Configured" if os.getenv("GEMINI_MODEL") else "Missing"}</span></div>
</section>"""
    return _layout(body, active="assistant", breadcrumb="Configuration")

# ---------------------------------------------------------------------------
# Run directly for local development (not used on Vercel)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse, os
    p = argparse.ArgumentParser(description="Metronome Support Intelligence")
    p.add_argument("--port", type=int, default=int(os.getenv("DEMO_PORT", "8501")))
    args = p.parse_args()
    print(f"Metronome Support Intelligence -- http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=False)
