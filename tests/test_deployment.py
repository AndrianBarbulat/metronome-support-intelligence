"""Deployment-specific tests: app import, routes, database selection."""
import os
import sys

sys.path.insert(0, ".")


def test_app_import_does_not_start_server():
    """Importing app.py must not start a server or make network calls."""
    # Clear any cached import
    import importlib
    if "app" in sys.modules:
        del sys.modules["app"]

    from app import app as flask_app

    assert flask_app is not None
    # Verify no server was started (Flask is just an object, not a running server)
    import app as app_module
    assert not hasattr(app_module, "server"), "No HTTP server should exist on the app module"
    assert not hasattr(app_module, "ThreadingHTTPServer"), "ThreadingHTTPServer should not be imported"


def test_flask_route_registration():
    """All required routes must be registered on the Flask app."""
    from app import app as flask_app

    routes = {rule.rule: rule.methods for rule in flask_app.url_map.iter_rules()}

    required = {
        "/": {"GET"},
        "/ask": {"POST"},
        "/cases": {"GET"},
        "/cases/<int:ticket_id>": {"GET"},
        "/drafts/<int:draft_id>/review": {"POST"},
        "/documentation": {"GET"},
        "/documentation/articles/<int:article_id>": {"GET"},
        "/how-it-works": {"GET"},
        "/testing": {"GET"},
        "/investigation": {"GET"},
        "/drafting": {"GET"},
        "/overview": {"GET"},
    }

    for path, expected_methods in required.items():
        assert path in routes, f"Route {path} not registered"
        registered = routes[path] - {"HEAD", "OPTIONS"}
        assert expected_methods.issubset(registered), (
            f"Route {path}: expected {expected_methods}, got {registered}"
        )


def test_missing_database_url_on_vercel():
    """When VERCEL=1 and DATABASE_URL is missing, adapter falls through to
    the central DB path resolver.  The resolver raises FileNotFoundError
    with a clear message when the packaged database is not available."""
    original_vercel = os.environ.pop("VERCEL", None)
    original_db_url = os.environ.pop("DATABASE_URL", None)
    try:
        os.environ["VERCEL"] = "1"
        from src.database.adapter import DatabaseAdapter

        try:
            adapter = DatabaseAdapter()
            adapter._resolve_backend()
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError as exc:
            assert "Packaged database not found" in str(exc)
    finally:
        if original_vercel is not None:
            os.environ["VERCEL"] = original_vercel
        else:
            os.environ.pop("VERCEL", None)
        if original_db_url is not None:
            os.environ["DATABASE_URL"] = original_db_url
        else:
            os.environ.pop("DATABASE_URL", None)


def test_sqlite_backend_when_no_env():
    """Default should fall back to local SQLite when not on Vercel."""
    original_db_url = os.environ.pop("DATABASE_URL", None)
    original_vercel = os.environ.pop("VERCEL", None)
    try:
        from src.database.adapter import DatabaseAdapter

        adapter = DatabaseAdapter()
        backend = adapter._resolve_backend()
        assert backend == "sqlite", f"Expected sqlite, got {backend}"
    finally:
        if original_db_url is not None:
            os.environ["DATABASE_URL"] = original_db_url
        if original_vercel is not None:
            os.environ["VERCEL"] = original_vercel


if __name__ == "__main__":
    test_app_import_does_not_start_server()
    print("✓ test_app_import_does_not_start_server passed")
    test_flask_route_registration()
    print("✓ test_flask_route_registration passed")
    test_missing_database_url_on_vercel()
    print("✓ test_missing_database_url_on_vercel passed")
    test_sqlite_backend_when_no_env()
    print("✓ test_sqlite_backend_when_no_env passed")
    print("\nAll deployment tests passed.")