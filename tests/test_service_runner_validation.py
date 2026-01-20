import pytest
from pactown.service_runner import ServiceRunner, ValidationResult

def test_validate_content_dependency_mismatch():
    runner = ServiceRunner(enable_fast_start=False)

    # Case 1: Node package in Python block
    content_node_in_py = """
```python markpact:file path=main.py
print("hello")
```
```python markpact:deps
express
requests
```
```bash markpact:run
python main.py
```
"""
    result = runner.validate_content(content_node_in_py)
    # Should be valid but contain warnings in errors list if strict validation is off, 
    # OR invalid if warnings are treated as errors. 
    # In my implementation: valid=len(errors) == 0 or all(e.startswith("Warning:") ...)
    # So valid should be True, but errors should contain the warning.
    assert result.valid is True
    assert any("Found Node.js package 'express' in Python dependency block" in e for e in result.errors)

    # Case 2: Python package in Node block
    content_py_in_node = """
```javascript markpact:file path=index.js
console.log("hello")
```
```javascript markpact:deps
fastapi
axios
```
```bash markpact:run
node index.js
```
"""
    result = runner.validate_content(content_py_in_node)
    assert result.valid is True
    assert any("Found Python package 'fastapi' in Node.js dependency block" in e for e in result.errors)

    # Case 3: Valid Python
    content_valid_py = """
```python markpact:file path=main.py
print("hello")
```
```python markpact:deps
fastapi
uvicorn
```
```bash markpact:run
python main.py
```
"""
    result = runner.validate_content(content_valid_py)
    assert result.valid is True
    assert len(result.errors) == 0

    # Case 4: Valid Node
    content_valid_node = """
```javascript markpact:file path=index.js
console.log("hello")
```
```javascript markpact:deps
express
pg
```
```bash markpact:run
node index.js
```
"""
    result = runner.validate_content(content_valid_node)
    assert result.valid is True
    assert len(result.errors) == 0
