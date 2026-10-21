"""Knowledge base documents are parsed and chunked on this server (#126)."""

import json
import re

import pytest

from api.services.documents import (
    DocumentParseError,
    chunk_document,
    estimate_tokens,
    parse_document,
    process_document,
)
from api.services.documents.parse import Block, ParsedDocument, Section
from api.tests.support.documents import make_docx, make_pdf


def _write(tmp_path, name: str, data: bytes | str):
    path = tmp_path / name
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return str(path)


def _headings(parsed):
    return [section.headings for section in parsed.sections]


# Parsing -------------------------------------------------------------------------


def test_pdf_text_pages_and_title(tmp_path):
    path = _write(
        tmp_path,
        "policy.pdf",
        make_pdf(
            [["Returns within 30 days."], ["Shipping takes 2 days."]],
            title="Store policy",
        ),
    )

    parsed = parse_document(path, "policy.pdf")

    assert parsed.format == "pdf"
    assert parsed.title == "Store policy"
    assert parsed.page_count == 2
    assert [(b.text, b.page) for b in parsed.sections[0].blocks] == [
        ("Returns within 30 days.", 1),
        ("Shipping takes 2 days.", 2),
    ]
    assert parsed.full_text == "Returns within 30 days.\n\nShipping takes 2 days."


def test_pdf_without_text_is_reported_as_scanned(tmp_path):
    path = _write(tmp_path, "scan.pdf", make_pdf([[], []]))

    with pytest.raises(DocumentParseError) as error:
        parse_document(path, "scan.pdf")

    assert str(error.value) == (
        "No text found in this PDF. Scanned documents aren't supported yet."
    )


def test_damaged_pdf_is_a_clear_error(tmp_path):
    path = _write(tmp_path, "broken.pdf", b"%PDF-1.4\nnot really a pdf")

    with pytest.raises(DocumentParseError, match="PDF"):
        parse_document(path, "broken.pdf")


def test_docx_headings_lists_and_tables(tmp_path):
    path = str(tmp_path / "handbook.docx")
    make_docx(path)

    parsed = parse_document(path, "handbook.docx")

    assert parsed.format == "docx"
    assert parsed.title == "Staff Handbook"
    assert _headings(parsed) == [
        ("Opening hours",),
        ("Opening hours", "Weekends"),
        ("Prices",),
    ]
    assert parsed.sections[1].text == (
        "On Saturdays we open from 10am to 2pm.\n\n"
        "- Sundays are closed\n- Bank holidays are closed"
    )
    assert parsed.sections[2].text == (
        "| Item | Price |\n| Coffee | 3.00 |\n| Tea | 2.50 |\n\nPrices include VAT."
    )
    assert parsed.full_text.startswith("Staff Handbook\n\n# Opening hours\n\n")
    assert "## Weekends" in parsed.full_text


def test_markdown_headings_skip_code_fences(tmp_path):
    text = (
        "# Menu\n\nFresh daily.\n\n## Starters\nSoup of the day.\n\n"
        "Desserts\n--------\n\nCake.\n\n```\n# not a heading\n```\n"
    )
    path = _write(tmp_path, "menu.md", text)

    parsed = parse_document(path, "menu.md")

    assert parsed.title == "Menu"
    assert _headings(parsed) == [
        ("Menu",),
        ("Menu", "Starters"),
        ("Menu", "Desserts"),
    ]
    assert "# not a heading" in parsed.sections[2].text
    # Markdown is kept exactly as written for full-document mode.
    assert parsed.full_text == text.strip()


def test_html_drops_scripts_and_styles(tmp_path):
    html = """<html><head><title>Help centre</title>
    <style>body { color: red }</style><script>track()</script></head>
    <body><nav>Home</nav><h1>Delivery</h1><p>We deliver
    across Ireland.</p><script>alert(1)</script>
    <ul><li>Next day</li><li>Same day in Dublin</li></ul>
    <table><tr><th>Zone</th><th>Price</th></tr><tr><td>A</td><td>5</td></tr></table>
    <h2>Returns</h2><p>Free<br>within 30 days.</p></body></html>"""
    path = _write(tmp_path, "help.html", html)

    parsed = parse_document(path, "help.html")

    assert parsed.title == "Help centre"
    assert "alert" not in parsed.full_text and "color" not in parsed.full_text
    assert "track" not in parsed.full_text
    assert _headings(parsed) == [(), ("Delivery",), ("Delivery", "Returns")]
    assert parsed.sections[1].text == (
        "We deliver across Ireland.\n\n- Next day\n- Same day in Dublin\n\n"
        "| Zone | Price |\n| A | 5 |"
    )
    assert parsed.sections[2].text == "Free\nwithin 30 days."


def test_csv_rows_name_their_columns(tmp_path):
    path = _write(tmp_path, "prices.csv", "item;price\ncoffee;3.00\ntea;2.50\n")

    parsed = parse_document(path, "prices.csv")

    assert [b.text for b in parsed.sections[0].blocks] == [
        "item: coffee | price: 3.00",
        "item: tea | price: 2.50",
    ]
    assert parsed.full_text.splitlines()[0] == "| item | price |"


def test_plain_text_json_and_legacy_encodings(tmp_path):
    txt = _write(tmp_path, "notes.txt", "Caf\xe9 hours\n\nOpen late.".encode("cp1252"))
    parsed = parse_document(txt, "notes.txt")
    assert parsed.title == "notes"
    assert [b.text for b in parsed.sections[0].blocks] == ["Café hours", "Open late."]

    data = _write(tmp_path, "faq.json", json.dumps({"q": "Parking?", "a": "Yes"}))
    parsed = parse_document(data, "faq.json")
    assert parsed.format == "json"
    assert '"q": "Parking?"' in parsed.full_text


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("old.doc", "Older Word .doc files aren't supported"),
        ("slides.pptx", "This file type isn't supported"),
    ],
)
def test_unsupported_files_are_clear_errors(tmp_path, name, message):
    path = _write(tmp_path, name, b"data")

    with pytest.raises(DocumentParseError, match=message):
        parse_document(path, name)


def test_empty_text_file_is_an_error(tmp_path):
    path = _write(tmp_path, "empty.txt", "  \n\n ")

    with pytest.raises(DocumentParseError, match="No text found"):
        parse_document(path, "empty.txt")


# Chunking ------------------------------------------------------------------------


def _doc(*sections: Section, title: str = "Guide") -> ParsedDocument:
    return ParsedDocument(
        title=title, format="text", sections=list(sections), full_text="x"
    )


def _words(count: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


def test_small_sections_become_one_chunk_each_with_context():
    parsed = _doc(
        Section(("Guide", "Hours"), [Block("Open 9 to 5.")]),
        Section(("Guide", "Parking"), [Block("Free parking.")]),
    )

    chunks = chunk_document(parsed)

    assert [c["chunk_text"] for c in chunks] == ["Open 9 to 5.", "Free parking."]
    assert [c["chunk_index"] for c in chunks] == [0, 1]
    # The title isn't repeated when the first heading is the title.
    assert chunks[0]["contextualized_text"] == "Guide > Hours\n\nOpen 9 to 5."
    assert chunks[1]["chunk_metadata"] == {"headings": ["Guide", "Parking"]}
    assert chunks[0]["token_count"] == estimate_tokens("Open 9 to 5.")


def test_long_section_is_split_with_overlap_and_whole_words():
    text = _words(1000)
    parsed = _doc(Section(("Policies",), [Block(text)]))

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=50)

    assert len(chunks) > 3
    vocabulary = set(text.split())
    for chunk in chunks:
        assert chunk["token_count"] <= 400
        # Never a partial word.
        assert set(chunk["chunk_text"].split()) <= vocabulary
        assert chunk["contextualized_text"].startswith("Guide > Policies\n\n")
    for previous, current in zip(chunks, chunks[1:]):
        tail = previous["chunk_text"].split()
        head = current["chunk_text"].split()
        repeated = [word for word in head if word in set(tail)]
        # The next chunk starts by repeating the end of the previous one.
        assert repeated and head[: len(repeated)] == tail[-len(repeated) :]
        assert 30 <= estimate_tokens(" ".join(repeated)) <= 50
    # Every word is covered, in order.
    covered = []
    for chunk in chunks:
        for word in chunk["chunk_text"].split():
            if not covered or int(word[1:]) > int(covered[-1][1:]):
                covered.append(word)
    assert covered == text.split()


def test_chunks_prefer_paragraph_breaks():
    first = _words(200, "a") + "."
    second = _words(200, "b") + "."
    parsed = _doc(Section((), [Block(first), Block(second)]))

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=0)

    # 200 words is ~267 tokens: the first chunk stops at the paragraph break
    # instead of running on into the second paragraph.
    assert chunks[0]["chunk_text"] == first
    assert chunks[1]["chunk_text"] == second


def test_chunks_never_cross_headings():
    parsed = _doc(
        Section(("A",), [Block(_words(20, "a"))]),
        Section(("B",), [Block(_words(20, "b"))]),
    )

    chunks = chunk_document(parsed, max_tokens=400)

    assert [c["chunk_metadata"]["headings"] for c in chunks] == [["A"], ["B"]]
    assert not re.search(r"\bb\d", chunks[0]["chunk_text"])


def test_chunks_record_pdf_pages():
    parsed = _doc(
        Section((), [Block(_words(250, "p"), page=1), Block(_words(600, "q"), page=2)])
    )

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=50)

    pages = [c["chunk_metadata"]["page_numbers"] for c in chunks]
    assert pages[0] == [1]
    # The overlap carries the end of page 1 into the next chunk.
    assert pages[1] == [1, 2]
    assert pages[-1] == [2]


def _covered(chunks) -> str:
    """The section text the chunks cover, with the overlaps removed."""
    text = ""
    for chunk in chunks:
        piece = chunk["chunk_text"]
        overlap = next(
            (
                n
                for n in range(min(len(text), len(piece)), 0, -1)
                if text.endswith(piece[:n])
            ),
            0,
        )
        text += piece[overlap:]
    return text


def test_text_without_spaces_is_cut_into_bounded_chunks():
    blob = "x" * 1_000_000
    parsed = _doc(Section((), [Block(blob)]))

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=50)

    assert len(chunks) > 600
    assert max(c["token_count"] for c in chunks) <= 400
    assert max(len(c["chunk_text"]) for c in chunks) <= 1600
    assert sum(len(c["chunk_text"]) for c in chunks) >= len(blob)


def test_long_words_beside_normal_text():
    blob = "y" * 4000
    parsed = _doc(Section((), [Block(f"start {blob} end")]))

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=50)

    assert chunks[0]["chunk_text"].startswith("start y")
    assert chunks[-1]["chunk_text"].endswith("y end")
    assert all(c["token_count"] <= 400 for c in chunks)


def test_chinese_without_spaces_is_estimated_per_character_and_split_at_sentences():
    sentence = "这是一个关于退货政策的句子。"
    # Numbered so the text isn't periodic and the coverage check is exact.
    text = "".join(f"第{i}条{sentence}" for i in range(400))
    parsed = _doc(Section((), [Block(text)]))

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=50)

    assert estimate_tokens(sentence) == len(sentence)
    assert len(chunks) > 10
    for chunk in chunks:
        assert estimate_tokens(chunk["chunk_text"]) <= 400
        assert len(chunk["chunk_text"]) <= 450
    # Chunks end between sentences, not mid-sentence.
    assert all(c["chunk_text"].endswith("。") for c in chunks)
    assert _covered(chunks) == text


def test_huge_headings_are_capped_and_counted_in_the_budget():
    heading = "Heading " * 20_000
    parsed = _doc(
        Section(("A", heading), [Block(_words(2000))]), title="Title " * 10_000
    )

    chunks = chunk_document(parsed, max_tokens=400, overlap_tokens=50)

    for chunk in chunks:
        prefix = chunk["contextualized_text"].split("\n\n", 1)[0]
        assert len(prefix) <= 300
        assert estimate_tokens(chunk["contextualized_text"]) <= 400 + 2


def test_parser_caps_headings_and_titles(tmp_path):
    path = _write(tmp_path, "long.md", "# " + "word " * 1000 + "\n\nBody text.")

    parsed = parse_document(path, "long.md")

    assert len(parsed.title) <= 200
    assert parsed.title.endswith("…")
    assert len(parsed.sections[0].headings[0]) <= 200


# Processor -----------------------------------------------------------------------


async def test_process_document_full_document_mode(tmp_path):
    path = str(tmp_path / "handbook.docx")
    make_docx(path)

    result = await process_document(path, "handbook.docx", None, "full_document")

    assert result["mode"] == "full_document"
    assert "# Opening hours" in result["full_text"]
    assert result["docling_metadata"] == {
        "parser": "lightmove",
        "format": "docx",
        "title": "Staff Handbook",
        "sections": 3,
    }
    assert "chunks" not in result


async def test_process_document_chunked_mode(tmp_path):
    path = _write(
        tmp_path,
        "policy.pdf",
        make_pdf([["Returns within 30 days."], ["Shipping takes 2 days."]]),
    )

    result = await process_document(path, "policy.pdf", "application/pdf", "chunked")

    assert result["mode"] == "chunked"
    assert result["docling_metadata"]["pages"] == 2
    assert result["docling_metadata"]["chunks"] == 1
    (chunk,) = result["chunks"]
    assert chunk["chunk_text"] == "Returns within 30 days.\n\nShipping takes 2 days."
    assert chunk["contextualized_text"] == f"policy\n\n{chunk['chunk_text']}"
    assert chunk["chunk_metadata"] == {"headings": [], "page_numbers": [1, 2]}
    assert set(chunk) == {
        "chunk_text",
        "contextualized_text",
        "chunk_index",
        "chunk_metadata",
        "token_count",
    }
