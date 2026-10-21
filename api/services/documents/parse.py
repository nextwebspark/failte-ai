"""Turn an uploaded knowledge base file into headed sections of plain text.

Everything runs in-process with pure-Python libraries (pypdf, python-docx and
the standard library), so a document never leaves the server it was uploaded
to. Parsing is CPU-bound and blocking; async callers run it in a thread.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Extensions the knowledge base accepts. The upload dialog offers the same list.
SUPPORTED_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".html",
    ".htm",
    ".json",
)

_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "text/csv": ".csv",
    "text/html": ".html",
    "application/json": ".json",
}

NO_PDF_TEXT_MESSAGE = (
    "No text found in this PDF. Scanned documents aren't supported yet."
)
NO_TEXT_MESSAGE = "No text found in this document."


class DocumentParseError(ValueError):
    """The file can't be turned into text. The message is shown to the user."""


@dataclass(frozen=True)
class Block:
    """A paragraph-sized piece of text, with the PDF page it came from."""

    text: str
    page: int | None = None


@dataclass
class Section:
    """Text under one heading path, e.g. ("Opening hours", "Weekends")."""

    headings: tuple[str, ...]
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)


@dataclass
class ParsedDocument:
    title: str
    format: str
    sections: list[Section]
    full_text: str
    page_count: int | None = None


def parse_document(
    path: str, filename: str, content_type: str | None = None
) -> ParsedDocument:
    """Parse the file at *path*. Raises DocumentParseError for unusable files."""
    extension = _extension_for(filename, content_type)
    fallback_title = _title_from_filename(filename)

    if extension == ".pdf":
        parsed = _parse_pdf(path, fallback_title)
    elif extension == ".docx":
        parsed = _parse_docx(path, fallback_title)
    else:
        with open(path, "rb") as f:
            text = _decode(f.read())
        if extension == ".md":
            parsed = _parse_markdown(text, fallback_title)
        elif extension in (".html", ".htm"):
            parsed = _parse_html(text, fallback_title)
        elif extension == ".csv":
            parsed = _parse_csv(text, fallback_title)
        elif extension == ".json":
            parsed = _parse_json(text, fallback_title)
        else:
            parsed = _parse_plain_text(text, fallback_title)

    parsed.sections = [s for s in parsed.sections if s.blocks]
    if not parsed.sections or not parsed.full_text.strip():
        raise DocumentParseError(
            NO_PDF_TEXT_MESSAGE if extension == ".pdf" else NO_TEXT_MESSAGE
        )
    return parsed


def _extension_for(filename: str, content_type: str | None) -> str:
    extension = os.path.splitext(filename)[1].lower()
    if extension in SUPPORTED_EXTENSIONS:
        return extension
    if extension == ".doc":
        raise DocumentParseError(
            "Older Word .doc files aren't supported. Save the file as .docx or "
            "PDF and upload it again."
        )
    by_type = _CONTENT_TYPE_EXTENSIONS.get((content_type or "").split(";")[0].strip())
    if not extension and by_type:
        return by_type
    raise DocumentParseError(
        f"This file type isn't supported. Upload one of: "
        f"{', '.join(SUPPORTED_EXTENSIONS)}."
    )


def _title_from_filename(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"[_]+", " ", stem).strip() or "Document"


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _clean(text: str) -> str:
    """Normalise whitespace inside lines and drop runs of blank lines."""
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _paragraph_blocks(text: str, page: int | None = None) -> list[Block]:
    return [
        Block(paragraph, page)
        for paragraph in (p.strip() for p in re.split(r"\n\s*\n", _clean(text)))
        if paragraph
    ]


class _SectionBuilder:
    """Collects blocks under a heading stack as a document is walked in order."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []
        self.sections: list[Section] = [Section(headings=())]

    def heading(self, level: int, text: str) -> None:
        text = _clean(text).replace("\n", " ")
        if not text:
            return
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))
        self.sections.append(Section(headings=tuple(h for _, h in self._stack)))

    def add(self, text: str, page: int | None = None) -> None:
        self.sections[-1].blocks.extend(_paragraph_blocks(text, page))

    def first_heading(self) -> str | None:
        for section in self.sections:
            if section.headings:
                return section.headings[0]
        return None


def _render(sections: list[Section]) -> str:
    """Full text as Markdown: each heading at its depth, then its paragraphs."""
    parts: list[str] = []
    previous: tuple[str, ...] = ()
    for section in sections:
        if section.headings and section.headings != previous:
            depth = min(len(section.headings), 6)
            parts.append(f"{'#' * depth} {section.headings[-1]}")
        previous = section.headings
        parts.extend(block.text for block in section.blocks)
    return "\n\n".join(parts)


# PDF -----------------------------------------------------------------------------


def _parse_pdf(path: str, fallback_title: str) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentParseError(
                "This PDF is password-protected. Remove the password and upload "
                "it again."
            )
        pages = [page.extract_text() or "" for page in reader.pages]
        title = (reader.metadata.title if reader.metadata else None) or ""
    except DocumentParseError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise DocumentParseError(
            "This PDF couldn't be read. It may be damaged."
        ) from exc

    section = Section(headings=())
    for number, page_text in enumerate(pages, start=1):
        section.blocks.extend(_paragraph_blocks(page_text, page=number))
    if not section.blocks:
        raise DocumentParseError(NO_PDF_TEXT_MESSAGE)
    return ParsedDocument(
        title=_clean(str(title)) or fallback_title,
        format="pdf",
        sections=[section],
        full_text="\n\n".join(_clean(text) for text in pages if text.strip()),
        page_count=len(pages),
    )


# DOCX ----------------------------------------------------------------------------

_HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


def _parse_docx(path: str, fallback_title: str) -> ParsedDocument:
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table

    try:
        document = docx.Document(path)
    except (PackageNotFoundError, KeyError, ValueError, OSError) as exc:
        raise DocumentParseError(
            "This Word document couldn't be read. It may be damaged."
        ) from exc
    except Exception as exc:  # zipfile.BadZipFile, lxml errors
        raise DocumentParseError(
            "This Word document couldn't be read. It may be damaged."
        ) from exc

    builder = _SectionBuilder()
    styled_title: str | None = None
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            builder.add(_docx_table_text(item))
            continue
        text = item.text or ""
        style = (item.style.name if item.style is not None else "") or ""
        if style.lower() == "title":
            styled_title = styled_title or _clean(text) or None
            continue
        match = _HEADING_STYLE.match(style.strip())
        if match and text.strip():
            builder.heading(int(match.group(1)), text)
        elif text.strip():
            if style.lower().startswith("list"):
                text = f"- {text.strip()}"
            builder.add(text)

    # Consecutive list items and short lines read best as one block.
    for section in builder.sections:
        section.blocks = _merge_list_blocks(section.blocks)

    title = (
        _clean(document.core_properties.title or "") or styled_title or fallback_title
    )
    return ParsedDocument(
        title=title,
        format="docx",
        sections=builder.sections,
        full_text="\n\n".join(
            part for part in (styled_title, _render(builder.sections)) if part
        ),
    )


def _docx_table_text(table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        seen = set()
        for cell in row.cells:
            # Merged cells repeat the same underlying cell; keep it once.
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            cells.append(_clean(cell.text).replace("\n", " "))
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _merge_list_blocks(blocks: list[Block]) -> list[Block]:
    merged: list[Block] = []
    for block in blocks:
        if (
            merged
            and block.text.startswith("- ")
            and merged[-1].text.splitlines()[-1].startswith("- ")
        ):
            merged[-1] = Block(f"{merged[-1].text}\n{block.text}", merged[-1].page)
        else:
            merged.append(block)
    return merged


# Markdown and plain text ---------------------------------------------------------

_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(=+|-+)\s*$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")


def _parse_markdown(text: str, fallback_title: str) -> ParsedDocument:
    builder = _SectionBuilder()
    lines = text.splitlines()
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        if buffer:
            builder.add("\n".join(buffer))
            buffer.clear()

    skip_underline = False
    for index, line in enumerate(lines):
        if skip_underline:
            skip_underline = False
            continue
        if _FENCE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue
        if in_fence:
            buffer.append(line)
            continue
        atx = _ATX_HEADING.match(line)
        if atx:
            flush()
            builder.heading(len(atx.group(1)), atx.group(2))
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if (
            line.strip()
            and _SETEXT_UNDERLINE.match(next_line)
            and (not buffer or not buffer[-1].strip())
            and not line.lstrip().startswith(("-", "*", "+", "|", ">"))
        ):
            # "Title" over "=====" or "-----" is a heading too.
            flush()
            builder.heading(1 if next_line.strip().startswith("=") else 2, line)
            skip_underline = True
            continue
        buffer.append(line)
    flush()

    return ParsedDocument(
        title=builder.first_heading() or fallback_title,
        format="markdown",
        sections=builder.sections,
        # The original Markdown already reads well; keep it as written.
        full_text=text.strip(),
    )


def _parse_plain_text(text: str, fallback_title: str) -> ParsedDocument:
    section = Section(headings=(), blocks=_paragraph_blocks(text))
    return ParsedDocument(
        title=fallback_title,
        format="text",
        sections=[section],
        full_text=text.strip(),
    )


# CSV and JSON --------------------------------------------------------------------


def _parse_csv(text: str, fallback_title: str) -> ParsedDocument:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text), dialect)
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        raise DocumentParseError(NO_TEXT_MESSAGE)

    header = rows[0]
    has_header = len(rows) > 1 and all(
        cell and not _looks_numeric(cell) for cell in header
    )
    lines: list[str] = []
    for row in rows[1:] if has_header else rows:
        if has_header:
            # Name every value so a row still makes sense in a chunk on its own.
            pairs = [f"{name}: {value}" for name, value in zip(header, row) if value]
            pairs.extend(value for value in row[len(header) :] if value)
            lines.append(" | ".join(pairs))
        else:
            lines.append(" | ".join(row))

    # One block per row keeps rows whole when the text is chunked.
    section = Section(headings=(), blocks=[Block(line) for line in lines if line])
    full_text = "\n".join(["| " + " | ".join(row) + " |" for row in rows])
    return ParsedDocument(
        title=fallback_title,
        format="csv",
        sections=[section],
        full_text=full_text,
    )


def _looks_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"[-+]?[\d.,]+%?", value))


def _parse_json(text: str, fallback_title: str) -> ParsedDocument:
    try:
        text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        pass  # Not valid JSON: index it as the text it is.
    parsed = _parse_plain_text(text, fallback_title)
    parsed.format = "json"
    return parsed


# HTML ----------------------------------------------------------------------------

_SKIPPED_HTML = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK_HTML = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "aside",
    "nav",
    "blockquote",
    "pre",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "form",
    "fieldset",
    "figure",
    "figcaption",
    "address",
    "hr",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.builder = _SectionBuilder()
        self.title = ""
        self._skip_depth = 0
        self._in_title = False
        self._heading_level: int | None = None
        self._heading_text: list[str] = []
        self._text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._pre_depth = 0

    # Text flow -----------------------------------------------------------------

    def _flush(self) -> None:
        text = "".join(self._text)
        self._text = []
        if text.strip():
            self.builder.add(text)

    def _write(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        elif self._heading_level is not None:
            self._heading_text.append(data)
        else:
            self._text.append(data)

    # Parser callbacks ----------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED_HTML:
            # <title> lives in <head>; read it before skipping the rest.
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if self._skip_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._heading_level = int(tag[1])
            self._heading_text = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br":
            self._write("\n")
        elif tag == "li":
            self._write("\n- ")
        elif tag in _BLOCK_HTML:
            self._pre_depth += tag == "pre"
            self._write("\n\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self._skip_depth:
            self._write("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag in _SKIPPED_HTML:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if re.fullmatch(r"h[1-6]", tag) and self._heading_level is not None:
            self.builder.heading(self._heading_level, "".join(self._heading_text))
            self._heading_level = None
        elif tag in ("td", "th") and self._cell is not None:
            cell = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._cell = None
            if self._row is not None:
                self._row.append(cell)
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._text.append("\n| " + " | ".join(self._row) + " |")
            self._row = None
        elif tag in _BLOCK_HTML:
            if tag == "pre":
                self._pre_depth = max(0, self._pre_depth - 1)
            self._write("\n\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        # Line breaks in HTML source are just spaces; structure comes from tags.
        self._write(data if self._pre_depth else re.sub(r"\s+", " ", data))

    def close(self):
        super().close()
        self._flush()


def _parse_html(text: str, fallback_title: str) -> ParsedDocument:
    extractor = _HTMLTextExtractor()
    extractor.feed(text)
    extractor.close()
    sections = extractor.builder.sections
    title = (
        _clean(extractor.title).replace("\n", " ")
        or extractor.builder.first_heading()
        or fallback_title
    )
    return ParsedDocument(
        title=title,
        format="html",
        sections=sections,
        full_text=_render(sections),
    )
