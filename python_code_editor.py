"""PyForge code editor widget.

Drop-in replacement: same classes (PythonHighlighter, LineNumberArea,
PythonCodeEditor), same public methods.

Changes vs. the old version:
  * Highlighter no longer uses `tokenize` per line. It is a small regex
    scanner with real block state, so triple-quoted strings work across
    lines and no tokenizer exception can ever reach Qt.
  * Every highlightBlock call is wrapped; a bad line can't take the app down.
  * keyPressEvent no longer calls toPlainText() (copied the whole document on
    every keystroke). It reads single characters from the QTextDocument.
  * Quotes are not auto-paired inside words (don't -> no stray ').
  * Fallback to a real monospace font when JetBrains Mono isn't installed.
  * Line-number margin is only re-laid-out when its width actually changes.
"""

import keyword
import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget


# ---------------------------------------------------------------------------
# Syntax highlighting
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
      (?P<comment>\#[^\n]*)
    | (?P<tri>[rRbBuUfF]{0,2}(?:'''|\"\"\"))
    | (?P<string>[rRbBuUfF]{0,2}(?:'(?:\\.|[^'\\])*'?|"(?:\\.|[^"\\])*"?))
    | (?P<number>\b(?:0[xX][0-9a-fA-F_]+
                    |0[bB][01_]+
                    |0[oO][0-7_]+
                    |\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?[jJ]?)\b)
    | (?P<name>[A-Za-z_]\w*)
    """,
    re.VERBOSE,
)

_KEYWORDS = frozenset(keyword.kwlist)

_STATE_NONE = 0
_STATE_TRI_SINGLE = 1  # inside '''
_STATE_TRI_DOUBLE = 2  # inside """

# Lines longer than this are left unhighlighted (minified/generated code).
_MAX_HIGHLIGHT_LINE = 4000


def _find_closing(text, start, delim):
    """Return the index just past the closing triple quote, or -1."""
    i = start
    while True:
        j = text.find(delim, i)
        if j == -1:
            return -1
        k = j - 1
        backslashes = 0
        while k >= start and text[k] == "\\":
            backslashes += 1
            k -= 1
        if backslashes % 2 == 0:
            return j + 3
        i = j + 1


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        def make_format(color, bold=False, italic=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(
                QFont.Weight.Bold if bold else QFont.Weight.Normal
            )
            fmt.setFontItalic(italic)
            return fmt

        self.fmt_keyword = make_format("#c586c0", bold=True)
        self.fmt_number = make_format("#b5cea8")
        self.fmt_string = make_format("#ce9178")
        self.fmt_comment = make_format("#6a9955", italic=True)

    def highlightBlock(self, text):
        try:
            self._highlight(text)
        except Exception:
            # Never let a Python exception escape into Qt's C++ virtual call.
            self.setCurrentBlockState(_STATE_NONE)

    def _highlight(self, text):
        prev = self.previousBlockState()
        length = len(text)

        if length > _MAX_HIGHLIGHT_LINE:
            self.setCurrentBlockState(
                prev if prev in (_STATE_TRI_SINGLE, _STATE_TRI_DOUBLE)
                else _STATE_NONE
            )
            return

        pos = 0

        # Continue a triple-quoted string from the previous line.
        if prev in (_STATE_TRI_SINGLE, _STATE_TRI_DOUBLE):
            delim = "'''" if prev == _STATE_TRI_SINGLE else '"""'
            end = _find_closing(text, 0, delim)
            if end == -1:
                self.setFormat(0, length, self.fmt_string)
                self.setCurrentBlockState(prev)
                return
            self.setFormat(0, end, self.fmt_string)
            pos = end

        self.setCurrentBlockState(_STATE_NONE)

        while pos < length:
            match = _TOKEN_RE.search(text, pos)
            if match is None:
                break

            kind = match.lastgroup
            start, stop = match.span()

            if kind == "comment":
                self.setFormat(start, stop - start, self.fmt_comment)

            elif kind == "tri":
                delim = match.group()[-3:]
                end = _find_closing(text, stop, delim)
                if end == -1:
                    self.setFormat(start, length - start, self.fmt_string)
                    self.setCurrentBlockState(
                        _STATE_TRI_SINGLE if delim == "'''"
                        else _STATE_TRI_DOUBLE
                    )
                    return
                self.setFormat(start, end - start, self.fmt_string)
                stop = end

            elif kind == "string":
                self.setFormat(start, stop - start, self.fmt_string)

            elif kind == "number":
                self.setFormat(start, stop - start, self.fmt_number)

            elif kind == "name":
                if match.group() in _KEYWORDS:
                    self.setFormat(start, stop - start, self.fmt_keyword)

            pos = stop if stop > pos else pos + 1


# ---------------------------------------------------------------------------
# Line number gutter
# ---------------------------------------------------------------------------

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.paintLineNumbers(event)


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------

_PAIRS = {
    "(": ")",
    "[": "]",
    "{": "}",
    '"': '"',
    "'": "'",
}
_CLOSERS = frozenset(_PAIRS.values())
_QUOTES = frozenset(("'", '"'))


def _is_word_char(ch):
    return ch.isalnum() or ch == "_"


class PythonCodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._gutter_width = -1
        self.lineNumberArea = LineNumberArea(self)

        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.cursorPositionChangedHandler)

        self.updateLineNumberAreaWidth(0)

        self.highlighter = PythonHighlighter(self.document())

    # -- helpers ------------------------------------------------------------

    def _char_at(self, position):
        """Single character at a document position ('' if out of range)."""
        if position < 0:
            return ""
        ch = self.document().characterAt(position)
        return "" if ch == "\x00" else ch

    # -- auto closing -------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        text = event.text()
        mods = event.modifiers()

        # Shortcuts like Ctrl+Z / Ctrl+C go straight to Qt (AltGr = Ctrl+Alt
        # on some layouts, so only bail on Ctrl without Alt).
        if (
            mods & Qt.KeyboardModifier.ControlModifier
            and not mods & Qt.KeyboardModifier.AltModifier
        ):
            super().keyPressEvent(event)
            return

        cursor = self.textCursor()
        has_selection = cursor.hasSelection()
        pos = cursor.position()

        # Skip over an existing closing character.
        if text in _CLOSERS and not has_selection:
            if self._char_at(pos) == text:
                cursor.movePosition(cursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return

        # Opening bracket / quote.
        if text in _PAIRS:
            closing = _PAIRS[text]

            # Wrap the selection.
            if has_selection:
                selected = cursor.selectedText()
                start = cursor.selectionStart()
                cursor.beginEditBlock()
                cursor.insertText(text + selected + closing)
                cursor.endEditBlock()
                cursor.setPosition(start + len(selected) + 2)
                self.setTextCursor(cursor)
                return

            # Don't pair a quote that is part of a word (don't, it's, f"...").
            if text in _QUOTES:
                before = self._char_at(pos - 1)
                after = self._char_at(pos)
                if (before and _is_word_char(before) and before not in "rRbBuUfF") \
                        or (after and _is_word_char(after)):
                    super().keyPressEvent(event)
                    return

            cursor.beginEditBlock()
            cursor.insertText(text + closing)
            cursor.movePosition(cursor.MoveOperation.Left)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return

        # Backspace between an empty pair removes both.
        if (
            key == Qt.Key.Key_Backspace
            and not has_selection
            and pos > 0
        ):
            previous = self._char_at(pos - 1)
            following = self._char_at(pos)
            if previous in _PAIRS and _PAIRS[previous] == following:
                cursor.beginEditBlock()
                cursor.deletePreviousChar()
                cursor.deleteChar()
                cursor.endEditBlock()
                self.setTextCursor(cursor)
                return

        super().keyPressEvent(event)

    # -- line numbers -------------------------------------------------------

    def lineNumberAreaWidth(self):
        digits = len(str(max(1, self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits + 10

    def updateLineNumberAreaWidth(self, _):
        width = self.lineNumberAreaWidth()
        if width != self._gutter_width:
            self._gutter_width = width
            self.setViewportMargins(width, 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(
                0, rect.y(), self.lineNumberArea.width(), rect.height()
            )

        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def cursorPositionChangedHandler(self):
        self.lineNumberArea.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.lineNumberArea.setGeometry(
            QRect(
                rect.left(),
                rect.top(),
                self.lineNumberAreaWidth(),
                rect.height(),
            )
        )

    def paintLineNumbers(self, event):
        painter = QPainter(self.lineNumberArea)
        try:
            painter.fillRect(event.rect(), QColor("#18181b"))
            painter.setFont(self.font())
            painter.setPen(QColor("#52525b"))

            block = self.firstVisibleBlock()
            block_number = block.blockNumber()
            top = round(
                self.blockBoundingGeometry(block)
                .translated(self.contentOffset())
                .top()
            )
            bottom = top + round(self.blockBoundingRect(block).height())

            line_height = self.fontMetrics().height()
            width = self.lineNumberArea.width() - 8

            while block.isValid() and top <= event.rect().bottom():
                if block.isVisible() and bottom >= event.rect().top():
                    painter.drawText(
                        0,
                        top,
                        width,
                        line_height,
                        Qt.AlignmentFlag.AlignRight,
                        str(block_number + 1),
                    )

                block = block.next()
                top = bottom
                bottom = top + round(self.blockBoundingRect(block).height())
                block_number += 1
        finally:
            painter.end()