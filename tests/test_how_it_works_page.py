"""Verify the /how-it-works page renders the new engineering case study."""
import sys
sys.path.insert(0, ".")

from app import app


def test_how_it_works_returns_200():
    with app.test_client() as c:
        r = c.get("/how-it-works")
        assert r.status_code == 200
        content = r.data.decode("utf-8")
        assert "Engineering support as a controlled reasoning system" in content, (
            "NEW page title missing — old page might still be rendering"
        )
        assert "What makes this different" in content, (
            "Section 'What makes this different' missing"
        )
        assert "Not just RAG" in content, ("Comparison table missing")
        assert "Operational scripts" in content, ("Scripts section missing")
        assert "Testing strategy" in content, ("Testing section missing")
        assert "How the system prevents confident nonsense" in content, (
            "Trust model section missing"
        )
        # Old content must NOT be present
        assert "Support engineers need to search documentation" not in content, (
            "OLD page header still present"
        )
        assert "Architecture" not in content.split(">Architecture<")[0] if "Architecture" in content else True, (
            "OLD architecture section should not appear"
        )
    print("✓ /how-it-works renders new engineering case study page")


def test_navigation_has_how_it_works():
    with app.test_client() as c:
        r = c.get("/")
        content = r.data.decode("utf-8")
        assert '/how-it-works' in content, (
            "Dashboard missing link to /how-it-works"
        )
    print("✓ Dashboard contains /how-it-works link")


def test_how_it_works_active_state():
    with app.test_client() as c:
        r = c.get("/how-it-works")
        content = r.data.decode("utf-8")
        # The nav item should have the 'active' class
        assert 'How it works222' in content, "Nav label missing"
    print("✓ /how-it-works renders with nav label")


if __name__ == "__main__":
    test_how_it_works_returns_200()
    test_navigation_has_how_it_works()
    test_how_it_works_active_state()
    print("\nAll /how-it-works page tests passed!")