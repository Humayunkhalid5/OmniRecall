import pytest
from docgen import write_docx, write_pdf

from omnirecall.errors import EngineError, UnsupportedFormatError
from omnirecall.extraction.documents import extract_document, format_for

MB = 1024 * 1024


def extract(path, max_bytes=100 * MB, pages=500):
    return extract_document(path, max_bytes, pages)


def test_plain_markdown_and_encodings(tmp_path):
    (tmp_path / "a.txt").write_text("Hello  world\r\nline two", encoding="utf-8")
    assert extract(tmp_path / "a.txt").text == "Hello world\nline two"
    (tmp_path / "b.md").write_bytes("# Title\n\nCafé".encode("utf-16"))
    assert extract(tmp_path / "b.md").text == "# Title\n\nCafé"
    (tmp_path / "c.log").write_bytes("naïve".encode("latin-1"))
    assert extract(tmp_path / "c.log").text == "naïve"


def test_csv_json_html(tmp_path):
    (tmp_path / "t.csv").write_text("name,city\nAda,London\nAlan,Wilmslow\n")
    out = extract(tmp_path / "t.csv")
    assert "Ada | London" in out.text and out.metadata["rows"] == 3
    (tmp_path / "d.json").write_text(
        '{"trip": {"city": "Lisbon", "nights": 4}, "tags": ["a", "b"]}'
    )
    text = extract(tmp_path / "d.json").text
    assert "trip.city: Lisbon" in text and "tags: b" in text
    (tmp_path / "p.html").write_text(
        "<html><head><title>Notes</title><script>alert('x')</script><style>p{}</style></head>"
        "<body><h1>Thylakoid</h1><p>Light&nbsp;reactions &amp; ATP</p></body></html>"
    )
    page = extract(tmp_path / "p.html")
    assert "alert" not in page.text and "p{}" not in page.text
    assert "Thylakoid" in page.text and "Light reactions & ATP" in page.text
    assert page.metadata["title"] == "Notes"


def test_pdf(tmp_path):
    write_pdf(tmp_path / "doc.pdf", ["First page about mitochondria", "Second page (ATP)"])
    out = extract(tmp_path / "doc.pdf")
    assert "mitochondria" in out.text and "(ATP)" in out.text
    assert out.metadata["pages"] == 2


def test_pdf_page_limit(tmp_path):
    write_pdf(tmp_path / "long.pdf", [f"page {i}" for i in range(5)])
    with pytest.raises(EngineError) as info:
        extract(tmp_path / "long.pdf", pages=3)
    assert info.value.code == "limit_exceeded"


def test_docx(tmp_path):
    write_docx(
        tmp_path / "w.docx",
        ["Vendor contract renews in December"],
        [["Item", "Cost"], ["Laptop", "1200"]],
    )
    out = extract(tmp_path / "w.docx")
    assert "Vendor contract" in out.text and "Laptop | 1200" in out.text


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("bad.pdf", b"%PDF-1.4 garbage", "malformed_file"),
        ("bad.docx", b"not a zip", "malformed_file"),
        ("bad.json", b"{oops", "malformed_file"),
        ("bin.txt", b"\x00\x01\x02\x00" * 10, "binary_content"),
        ("blank.txt", b"   \n\n  ", "extraction_empty"),
    ],
)
def test_malformed_files_fail_cleanly(tmp_path, name, data, code):
    (tmp_path / name).write_bytes(data)
    with pytest.raises(EngineError) as info:
        extract(tmp_path / name)
    assert info.value.code == code


def test_size_limit_and_unsupported(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 2048)
    with pytest.raises(EngineError) as info:
        extract(tmp_path / "big.txt", max_bytes=1024)
    assert info.value.code == "limit_exceeded"
    with pytest.raises(UnsupportedFormatError):
        format_for(tmp_path / "movie.mkv")
    with pytest.raises(UnsupportedFormatError):
        format_for(tmp_path / "noext")
