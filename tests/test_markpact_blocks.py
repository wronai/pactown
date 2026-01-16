from pactown.markpact_blocks import parse_blocks


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
