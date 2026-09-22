import pytest
from src.agent_framework.utils.json_extractor import extract_json_data

def test_extract_simple_object():
    data = extract_json_data('{"status": "ok", "count": 42}')
    assert data == {"status": "ok", "count": 42}

def test_extract_from_code_block():
    text = """Here is the plan:
```json
{
  "task_type": "search",
  "steps": [{"action": "navigate", "value": "https://example.com"}]
}
```
Let me know if you need changes.
"""
    data = extract_json_data(text)
    assert data["task_type"] == "search"
    assert len(data["steps"]) == 1

def test_extract_multiple_json_blocks_avoids_extra_data():
    text = """First block:
```json
{"version": 1, "nested": {"a": [1, 2, 3]}}
```
Second block:
```json
{"version": 2}
```
"""
    data = extract_json_data(text)
    assert data == {"version": 1, "nested": {"a": [1, 2, 3]}}

def test_extract_nested_structures():
    text = 'Result: {"outer": {"inner": {"value": "deep"}}} trailing text {another: 1}'
    data = extract_json_data(text)
    assert data == {"outer": {"inner": {"value": "deep"}}}

def test_extract_array():
    text = "Tasks: [1, 2, 3] and some notes"
    data = extract_json_data(text)
    assert data == [1, 2, 3]

def test_invalid_text():
    assert extract_json_data("Just plain text with no json") is None
