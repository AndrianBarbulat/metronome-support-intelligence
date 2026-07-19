"""Tests for the Markdown parser and code fence extraction."""

from src.documentation.code_fence_parser import CodeBlock, extract_code_blocks
from src.documentation.markdown_parser import MarkdownSection, parse_markdown
from src.documentation.openapi_parser import OpenApiMetadata, detect_openapi


class TestCodeFenceParser:
    def test_normal_fence(self):
        lines = ["```json\n", '{"key": "value"}\n', "```\n"]
        blocks = extract_code_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].language == "json"
        assert blocks[0].fence_metadata is None
        assert '"key"' in blocks[0].content
        assert blocks[0].start_line == 1
        assert blocks[0].end_line == 3

    def test_custom_4_backtick_openapi_fence(self):
        lines = [
            "````yaml /openapi.json post /v1/alerts/create\n",
            "openapi: 3.0.1\n",
            "paths:\n",
            "````\n",
        ]
        blocks = extract_code_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].language == "yaml"
        assert "/openapi.json post /v1/alerts/create" in blocks[0].fence_metadata
        assert "openapi: 3.0.1" in blocks[0].content

    def test_fence_with_5_backticks(self):
        lines = [
            "`````json\n",
            '{"a": 1}\n',
            "`````\n",
        ]
        blocks = extract_code_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0].language == "json"

    def test_no_code_blocks(self):
        lines = ["No code here\n", "Just text\n"]
        blocks = extract_code_blocks(lines)
        assert len(blocks) == 0

    def test_unclosed_fence(self):
        lines = ["```python\n", "def foo():\n"]
        blocks = extract_code_blocks(lines)
        assert len(blocks) == 1
        assert "def foo()" in blocks[0].content

    def test_multiple_fences(self):
        lines = [
            "```json\n", "{}\n", "```\n",
            "```yaml\n", "key: val\n", "```\n",
        ]
        blocks = extract_code_blocks(lines)
        assert len(blocks) == 2
        assert blocks[0].language == "json"
        assert blocks[1].language == "yaml"


class TestMarkdownParser:
    def test_no_headings(self):
        raw = "This is some text.\nNo headings here.\n"
        parsed = parse_markdown(raw, "My Doc")
        assert len(parsed.sections) == 1
        assert parsed.sections[0].heading is None
        assert "This is some text" in parsed.sections[0].content

    def test_h1_through_h6(self):
        raw = "# H1\n\n## H2\n\n### H3\n\n#### H4\n\n##### H5\n\n###### H6\n"
        parsed = parse_markdown(raw, "Doc")
        assert len(parsed.sections) == 6
        assert parsed.sections[0].heading == "H1"
        assert parsed.sections[0].heading_level == 1
        assert parsed.sections[5].heading == "H6"
        assert parsed.sections[5].heading_level == 6

    def test_nested_heading_paths(self):
        raw = "# Contract\n\n## Request\n\n### Body\n\n#### customer_id\n"
        parsed = parse_markdown(raw, "Doc")
        assert parsed.sections[3].heading_path == ["Contract", "Request", "Body", "customer_id"]

    def test_heading_hierarchy_replacement(self):
        raw = "# A\n\n## B\n\n### C\n\n## D\n\n"
        parsed = parse_markdown(raw, "Doc")
        # Section "D" should have path ["A", "D"] not ["A", "B", "C", "D"]
        last = parsed.sections[-1]
        assert last.heading == "D"
        assert last.heading_path == ["A", "D"]

    def test_heading_inside_code_fence_ignored(self):
        raw = "```markdown\n# Not a real heading\n```\n\n# Real heading\n\nContent\n"
        parsed = parse_markdown(raw, "Doc")
        sections_with_headings = [s for s in parsed.sections if s.heading]
        assert len(sections_with_headings) == 1
        assert sections_with_headings[0].heading == "Real heading"

    def test_preserves_code_fence_content(self):
        raw = "# Test\n\n```python\nx = 1\ny = 2\n```\n"
        parsed = parse_markdown(raw, "Doc")
        assert "x = 1" in parsed.sections[0].content
        assert len(parsed.code_blocks) == 1
        assert parsed.code_blocks[0].language == "python"

    def test_preserves_json_indentation(self):
        raw = "# Data\n\n```json\n{\n  \"key\": \"value\"\n}\n```\n"
        parsed = parse_markdown(raw, "Doc")
        assert '  "key"' in parsed.code_blocks[0].content

    def test_preserves_yaml_indentation(self):
        raw = "# Config\n\n```yaml\nroot:\n  child: value\n```\n"
        parsed = parse_markdown(raw, "Doc")
        assert "  child: value" in parsed.code_blocks[0].content

    def test_detects_table(self):
        raw = "# Table\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        parsed = parse_markdown(raw, "Doc")
        assert len(parsed.tables) == 1
        assert "| A | B |" in parsed.tables[0]["raw_markdown"]

    def test_empty_document(self):
        parsed = parse_markdown("", "Empty")
        assert len(parsed.sections) == 0
        assert len(parsed.code_blocks) == 0


class TestOpenApiParser:
    def test_detects_openapi_yaml(self):
        content = "openapi: 3.0.1\npaths:\n  /test:\n    get:\n      operationId: getTest\n      responses:\n        '200':\n          description: OK\n"
        result = detect_openapi(None, content, "yaml")
        assert result.detected
        assert result.operation_id == "getTest"
        assert "200" in result.response_codes

    def test_extracts_http_method_from_fence_metadata(self):
        content = "openapi: 3.0.1\npaths:\n"
        result = detect_openapi("/openapi.json post /v1/alerts/create", content, "yaml")
        assert result.detected
        assert result.http_method == "POST"
        assert result.endpoint_path == "/v1/alerts/create"

    def test_extracts_operation_id(self):
        content = "operationId: createAlert-v1\n"
        result = detect_openapi(None, content, "yaml")
        assert result.detected
        assert result.operation_id == "createAlert-v1"

    def test_extracts_required_fields(self):
        content = (
            "openapi: 3.0\n"
            "requestBody:\n"
            "required: true\n"
            "properties:\n"
            "  customer_id:\n"
            "    type: string\n"
            "required:\n"
            "  - customer_id\n"
        )
        result = detect_openapi(None, content, "yaml")
        assert result.detected
        field_names = [f["name"] for f in result.request_fields]
        assert "customer_id" in field_names
        customer = next(f for f in result.request_fields if f["name"] == "customer_id")
        assert customer["required"] is True

    def test_extracts_response_codes(self):
        content = "openapi: 3.0\nresponses:\n  '200':\n    description: OK\n  '409':\n    description: Conflict\n"
        result = detect_openapi(None, content, "yaml")
        assert result.detected
        assert "200" in result.response_codes
        assert "409" in result.response_codes

    def test_handles_malformed_yaml_safely(self):
        content = "this is not yaml at all\njust some text\n"
        result = detect_openapi(None, content, None)
        assert not result.detected

    def test_non_openapi_code_block(self):
        content = 'print("hello world")'
        result = detect_openapi(None, content, "python")
        assert not result.detected