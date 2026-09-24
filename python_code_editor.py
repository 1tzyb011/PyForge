
import io
import tokenize
import token
import keyword

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QKeyEvent,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self.formats = {}

        def make_format(color, bold=False, italic=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))

            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            else:
                fmt.setFontWeight(QFont.Weight.Normal)

            fmt.setFontItalic(italic)

            return fmt

        self.formats[token.NAME] = make_format("#e4e4e7")
        self.formats[token.NUMBER] = make_format("#b5cea8")
        self.formats[token.STRING] = make_format("#ce9178")
        self.formats[token.ERRORTOKEN] = make_format("#f87171")
        self.formats[token.OP] = make_format("#d4d4d8")
        self.formats[token.COMMENT] = make_format(
            "#6a9955",
            italic=True
        )

        self.formats[token.NEWLINE] = make_format("#d4d4d8")
        self.formats[token.INDENT] = make_format("#d4d4d8")
        self.formats[token.DEDENT] = make_format("#d4d4d8")

        self.keyword_format = make_format(
            "#c586c0",
            bold=True
        )

        if hasattr(token, "FSTRING_MIDDLE"):
            self.formats[token.FSTRING_MIDDLE] = make_format(
                "#ce9178"
            )

        if hasattr(token, "FSTRING_START"):
            self.formats[token.FSTRING_START] = make_format(
                "#ce9178"
            )

        if hasattr(token, "FSTRING_END"):
            self.formats[token.FSTRING_END] = make_format(
                "#ce9178"
            )

    def highlightBlock(self, text):
        try:
            tokens = tokenize.generate_tokens(
                io.StringIO(text).readline
            )

            for tok in tokens:
                token_type = tok.type

                start = tok.start[1]
                end = tok.end[1]

                if start < 0:
                    continue

                length = max(0, end - start)

                if not length:
                    continue

                if (
                    token_type == token.NAME
                    and keyword.iskeyword(tok.string)
                ):
                    self.setFormat(
                        start,
                        length,
                        self.keyword_format
                    )
                    continue

                if token_type not in self.formats:
                    continue

                self.setFormat(
                    start,
                    length,
                    self.formats[token_type]
                )

        except (tokenize.TokenError, IndentationError):
            pass


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(
            self.editor.lineNumberAreaWidth(),
            0
        )

    def paintEvent(self, event):
        self.editor.paintLineNumbers(event)


class PythonCodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.lineNumberArea = LineNumberArea(self)

        self.blockCountChanged.connect(
            self.updateLineNumberAreaWidth
        )

        self.updateRequest.connect(
            self.updateLineNumberArea
        )

        self.cursorPositionChanged.connect(
            self.cursorPositionChangedHandler
        )

        self.updateLineNumberAreaWidth(0)

        font = QFont("JetBrains Mono", 10)
        self.setFont(font)

        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )

        self.highlighter = PythonHighlighter(
            self.document()
        )

    # ---------------------------------------------------------
    # Auto Closing
    # ---------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        text = event.text()

        cursor = self.textCursor()

        pairs = {
            "(": ")",
            "[": "]",
            "{": "}",
            '"': '"',
            "'": "'",
        }

        closing_characters = {
            ")",
            "]",
            "}",
            '"',
            "'",
        }

        # -----------------------------------------------------
        # Skip over an existing closing character
        # -----------------------------------------------------

        if (
            text in closing_characters
            and not cursor.hasSelection()
        ):
            if cursor.position() < len(self.toPlainText()):
                next_character = self.toPlainText()[
                    cursor.position()
                ]

                if next_character == text:
                    cursor.movePosition(
                        cursor.MoveOperation.Right
                    )

                    self.setTextCursor(cursor)
                    return

        # -----------------------------------------------------
        # Handle opening brackets / quotes
        # -----------------------------------------------------

        if text in pairs:
            closing = pairs[text]

            # -------------------------------------------------
            # If text is selected, wrap the selection
            # -------------------------------------------------

            if cursor.hasSelection():
                selected_text = cursor.selectedText()

                start = cursor.selectionStart()
                end = cursor.selectionEnd()

                cursor.setPosition(start)

                cursor.setPosition(
                    end,
                    cursor.MoveMode.KeepAnchor
                )

                cursor.insertText(
                    text + selected_text + closing
                )

                cursor.setPosition(
                    start + len(selected_text) + 2
                )

                self.setTextCursor(cursor)
                return

            # -------------------------------------------------
            # Insert the pair and leave cursor between them
            # -------------------------------------------------

            cursor.insertText(
                text + closing
            )

            cursor.movePosition(
                cursor.MoveOperation.Left
            )

            self.setTextCursor(cursor)
            return

        # -----------------------------------------------------
        # Paired backspace
        # -----------------------------------------------------

        if (
            key == Qt.Key.Key_Backspace
            and not cursor.hasSelection()
            and cursor.position() > 0
            and cursor.position() < len(self.toPlainText())
        ):
            document_text = self.toPlainText()

            previous_character = document_text[
                cursor.position() - 1
            ]

            next_character = document_text[
                cursor.position()
            ]

            matching_pairs = {
                "(": ")",
                "[": "]",
                "{": "}",
                '"': '"',
                "'": "'",
            }

            if (
                previous_character in matching_pairs
                and matching_pairs[previous_character]
                == next_character
            ):
                cursor.deletePreviousChar()
                cursor.deleteChar()

                self.setTextCursor(cursor)
                return

        # -----------------------------------------------------
        # Normal keyboard input
        # -----------------------------------------------------

        super().keyPressEvent(event)

    # ---------------------------------------------------------
    # Line Numbers
    # ---------------------------------------------------------

    def lineNumberAreaWidth(self):
        digits = len(
            str(max(1, self.blockCount()))
        )

        return (
            10
            + self.fontMetrics().horizontalAdvance("9") * digits
            + 10
        )

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(
            self.lineNumberAreaWidth(),
            0,
            0,
            0
        )

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(
                0,
                rect.y(),
                self.lineNumberArea.width(),
                rect.height()
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
                rect.height()
            )
        )

    def paintLineNumbers(self, event):
        painter = QPainter(self.lineNumberArea)

        painter.fillRect(
            event.rect(),
            QColor("#18181b")
        )

        painter.setFont(self.font())
        painter.setPen(QColor("#52525b"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()

        top = int(
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset())
            .top()
        )

        bottom = (
            top
            + int(self.blockBoundingRect(block).height())
        )

        while (
            block.isValid()
            and top <= event.rect().bottom()
        ):
            if (
                block.isVisible()
                and bottom >= event.rect().top()
            ):
                number = str(block_number + 1)

                painter.drawText(
                    0,
                    top,
                    self.lineNumberArea.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number
                )

            block = block.next()
            top = bottom

            bottom = (
                top
                + int(self.blockBoundingRect(block).height())
            )

            block_number += 1