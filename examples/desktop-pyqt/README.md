# Notes – PyQt Desktop App

A simple sticky-notes desktop application built with PyQt6.

```yaml markpact:target
platform: desktop
framework: pyqt
app_name: StickyNotes
app_id: com.pactown.stickynotes
window_width: 500
window_height: 600
```

```python markpact:file path=main.py
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QListWidget, QWidget, QInputDialog,
)
from PyQt6.QtCore import Qt


class StickyNotes(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sticky Notes")
        self.setMinimumSize(500, 600)
        self.notes: dict[str, str] = {}

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_new = QPushButton("+ New Note")
        btn_new.clicked.connect(self.new_note)
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self.delete_note)
        toolbar.addWidget(btn_new)
        toolbar.addWidget(btn_del)
        layout.addLayout(toolbar)

        # Note list
        self.note_list = QListWidget()
        self.note_list.currentRowChanged.connect(self.load_note)
        layout.addWidget(self.note_list)

        # Editor
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Write your note here...")
        self.editor.textChanged.connect(self.save_current)
        layout.addWidget(self.editor)

        self._current: str | None = None

    def new_note(self):
        title, ok = QInputDialog.getText(self, "New Note", "Title:")
        if ok and title.strip():
            self.notes[title] = ""
            self.note_list.addItem(title)
            self.note_list.setCurrentRow(self.note_list.count() - 1)

    def delete_note(self):
        row = self.note_list.currentRow()
        if row >= 0:
            item = self.note_list.takeItem(row)
            self.notes.pop(item.text(), None)
            self._current = None
            self.editor.clear()

    def load_note(self, row: int):
        if row < 0:
            return
        title = self.note_list.item(row).text()
        self._current = title
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.notes.get(title, ""))
        self.editor.blockSignals(False)

    def save_current(self):
        if self._current:
            self.notes[self._current] = self.editor.toPlainText()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StickyNotes()
    window.show()
    sys.exit(app.exec())
```

```python markpact:deps
PyQt6
pyinstaller
```

```bash markpact:build
pyinstaller --onefile --windowed main.py
```

```bash markpact:run
python main.py
```
