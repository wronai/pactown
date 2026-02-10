from pactown.markpact_blocks import extract_run_command, parse_blocks


def test_parse_blocks_new_format_includes_lang() -> None:
    md = """```python markpact:file path=main.py
print(\"hi\")
```"""

    blocks = parse_blocks(md)

    assert len(blocks) == 1

    block = blocks[0]
    assert block.kind == "file"
    assert block.meta == "path=main.py"
    assert block.lang == "python"
    assert block.body == 'print("hi")'
    assert block.get_path() == "main.py"


def test_parse_blocks_old_format_is_supported() -> None:
    md = """```markpact:file python path=main.py
print(\"hi\")
```"""

    blocks = parse_blocks(md)

    assert len(blocks) == 1

    block = blocks[0]
    assert block.kind == "file"
    assert block.meta == "python path=main.py"
    assert block.lang == ""
    assert block.body == 'print("hi")'
    assert block.get_path() == "main.py"


def test_parse_blocks_run_block_new_format() -> None:
    md = """```bash markpact:run
echo hi
```"""

    blocks = parse_blocks(md)

    assert len(blocks) == 1

    block = blocks[0]
    assert block.kind == "run"
    assert block.meta == ""
    assert block.lang == "bash"
    assert block.body == "echo hi"


def test_extract_run_command_explicit_block() -> None:
    md = """```bash markpact:run
python main.py
```"""
    blocks = parse_blocks(md)
    assert extract_run_command(blocks) == "python main.py"


def test_extract_run_command_from_target_framework() -> None:
    md = """```yaml markpact:target
platform: desktop
framework: electron
```
```javascript markpact:file path=main.js
console.log("hi")
```"""
    blocks = parse_blocks(md)
    assert extract_run_command(blocks) == "npx electron ."


def test_extract_run_command_file_heuristic_main_py() -> None:
    md = """```python markpact:file path=main.py
print("hi")
```"""
    blocks = parse_blocks(md)
    assert extract_run_command(blocks) == "python main.py"


def test_extract_run_command_file_heuristic_index_js() -> None:
    md = """```javascript markpact:file path=index.js
const x = 1
```"""
    blocks = parse_blocks(md)
    assert extract_run_command(blocks) == "node index.js"


def test_extract_run_command_returns_none_when_no_hint() -> None:
    md = """```python markpact:deps
requests
```"""
    blocks = parse_blocks(md)
    assert extract_run_command(blocks) is None


def test_extract_run_command_explicit_overrides_framework() -> None:
    md = """```yaml markpact:target
platform: desktop
framework: electron
```
```bash markpact:run
npm start
```"""
    blocks = parse_blocks(md)
    assert extract_run_command(blocks) == "npm start"
