"""Focused tests for database path resolution on Vercel and local."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

os.environ.pop("VERCEL", None)

print("=== Test 1: Explicit temp path ===")
from src.database.connection import resolve_db_path

tmp_path = Path("tests/data/test_temp.db")
result = resolve_db_path(tmp_path)
assert result == tmp_path, f"Expected {tmp_path}, got {result}"
print("PASS")

print()
print("=== Test 2: Local default DB path ===")
result = resolve_db_path()
assert result == Path("data/metronome_docs.db"), f"Expected data/metronome_docs.db, got {result}"
print("PASS")

print()
print("=== Test 3+5: Vercel copy and reuse ===")
test_src = Path(tempfile.gettempdir()) / "var" / "task" / "data" / "metronome_docs.db"
test_src.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2("data/metronome_docs.db", test_src)
test_dst = Path("/tmp/metronome_docs.db")
if test_dst.exists():
    test_dst.unlink()
os.environ["VERCEL"] = "1"

import src.database.connection as conn_module

old = conn_module._VERCEL_PACKAGED_DB
conn_module._VERCEL_PACKAGED_DB = test_src
try:
    result = resolve_db_path()
    assert result == Path("/tmp/metronome_docs.db"), f"Expected /tmp, got {result}"
    assert Path("/tmp/metronome_docs.db").exists(), "Database not copied to /tmp"
    print("PASS: copy to /tmp")

    result2 = resolve_db_path()
    assert result2 == Path("/tmp/metronome_docs.db")
    print("PASS: reuse /tmp")
finally:
    conn_module._VERCEL_PACKAGED_DB = old
    os.environ.pop("VERCEL", None)
    if test_dst.exists():
        test_dst.unlink()
    shutil.rmtree(Path(tempfile.gettempdir()) / "var", ignore_errors=True)

print()
print("=== Test 4: Missing packaged DB error ===")
if Path("/tmp/metronome_docs.db").exists():
    Path("/tmp/metronome_docs.db").unlink()
os.environ["VERCEL"] = "1"
try:
    resolve_db_path()
    raise AssertionError("Should have raised FileNotFoundError")
except FileNotFoundError as e:
    assert "Packaged database not found" in str(e)
    print(f"PASS: {e}")
finally:
    os.environ.pop("VERCEL", None)

print()
print("=== Test 6: CSS template rendering ===")
from app import STYLE_AND_LAYOUT

assert "color-scheme" in STYLE_AND_LAYOUT, "Missing color-scheme"
assert "{title}" in STYLE_AND_LAYOUT, "Missing title placeholder"
assert "{body}" in STYLE_AND_LAYOUT, "Missing body placeholder"

rendered = (
    STYLE_AND_LAYOUT.replace("{title}", "T")
    .replace("{nav_html}", "")
    .replace("{breadcrumb}", "")
    .replace("{body}", "")
    .replace("{gemini_dot}", "")
    .replace("{gemini}", "")
)
assert "color-scheme:dark" in rendered, "CSS lost after template substitution"
assert "KeyError" not in rendered, "KeyError found in rendered template"
print("PASS: Template renders without KeyError")

print()
print("=== Test 7: App import + url_map ===")
from app import app as flask_app

rules = list(flask_app.url_map.iter_rules())
print(f"Routes registered: {len(rules)}")
route_paths = {rule.rule for rule in rules}
expected = {"/", "/ask", "/cases", "/cases/<int:ticket_id>", "/documentation", "/how-it-works", "/testing"}
missing = expected - route_paths
assert not missing, f"Missing routes: {missing}"
print("PASS: All expected routes registered")

print()
print("All focused tests passed!")