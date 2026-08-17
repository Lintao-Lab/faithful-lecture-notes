"""Convert PDF, PPTX and DOCX inputs into Markdown text for the pipeline.

Each converter uses a single lightweight tool:

- PDF  -> pypdf text-layer extraction (scanned PDFs without a text layer are
  rejected with a clear message; run OCR on them first).
- PPTX -> the existing deterministic python-pptx extractor in
  ``pptx_to_llm_markdown`` (native text, tables and SmartArt in slide order).
- DOCX -> a small standard-library reader for ``word/document.xml``
  (paragraphs, headings and tables; no extra dependency).

Legacy binary formats (.ppt, .doc) are rejected with guidance to re-save
them as .pptx/.docx first.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
CONVERTIBLE_SUFFIXES = {".pdf", ".pptx", ".docx"}
LEGACY_SUFFIXES = {".ppt", ".doc"}

_WORDPROCESSING_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MIN_PDF_TEXT_CHARACTERS = 100


def convert_to_markdown(path: Path, *, source_name: str) -> str:
    """Convert a supported document into Markdown text."""

    suffix = path.suffix.casefold()
    try:
        if suffix == ".pdf":
            return pdf_to_markdown(path)
        if suffix == ".pptx":
            return pptx_to_markdown(path)
        if suffix == ".docx":
            return docx_to_markdown(path)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"{source_name} could not be converted to text: {path} ({exc}). "
            "Check that the file is not corrupted or password-protected."
        ) from exc
    raise ValueError(f"Unsupported format for {source_name}: {path}")


def pdf_to_markdown(path: Path) -> str:
    """Extract a PDF text layer page by page using pypdf."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is not installed. Install it with `python3 -m pip install pypdf`."
        ) from exc

    reader = PdfReader(str(path))
    lines = [f"# {path.stem}", ""]
    total_characters = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        total_characters += len(text)
        lines.extend([f"## Page {page_number}", "", text or "(no extractable text)", ""])

    if len(reader.pages) and total_characters < _MIN_PDF_TEXT_CHARACTERS:
        raise ValueError(
            f"PDF has no usable text layer (it is probably a scan): {path}. "
            "Run OCR on it first, then pass the resulting text file."
        )
    return "\n".join(lines).rstrip() + "\n"


def pptx_to_markdown(path: Path) -> str:
    """Extract native PPTX text, tables and SmartArt in slide order."""

    from .pptx_to_llm_markdown import convert_pptx

    with tempfile.TemporaryDirectory(prefix="pptx_convert_") as tmpdir:
        markdown_path = Path(tmpdir) / "slides.md"
        report_path = Path(tmpdir) / "report.json"
        convert_pptx(
            pptx_path=path,
            markdown_path=markdown_path,
            report_path=report_path,
        )
        return markdown_path.read_text(encoding="utf-8")


def docx_to_markdown(path: Path) -> str:
    """Extract DOCX paragraphs, headings and tables with the standard library."""

    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    body = root.find(f"{{{_WORDPROCESSING_NS}}}body")
    if body is None:
        raise ValueError(f"DOCX has no document body: {path}")

    lines = [f"# {path.stem}", ""]
    for element in body:
        tag = _local_name(element.tag)
        if tag == "p":
            markdown = _docx_paragraph_markdown(element)
            if markdown:
                lines.extend([markdown, ""])
        elif tag == "tbl":
            markdown = _docx_table_markdown(element)
            if markdown:
                lines.extend([markdown, ""])
    return "\n".join(lines).rstrip() + "\n"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx_paragraph_markdown(paragraph: ElementTree.Element) -> str:
    text = _docx_text(paragraph)
    if not text:
        return ""
    style = paragraph.find(f"{{{_WORDPROCESSING_NS}}}pPr/{{{_WORDPROCESSING_NS}}}pStyle")
    if style is not None:
        match = re.fullmatch(
            r"Heading([1-6])", style.get(f"{{{_WORDPROCESSING_NS}}}val", "")
        )
        if match:
            return f"{'#' * int(match.group(1))} {text}"
    return text


def _docx_text(element: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        tag = _local_name(node.tag)
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag in {"tab", "br"}:
            parts.append(" ")
    return " ".join("".join(parts).split())


def _docx_table_markdown(table: ElementTree.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{{{_WORDPROCESSING_NS}}}tr"):
        cells = [
            _docx_text(cell).replace("|", "\\|")
            for cell in row.findall(f"{{{_WORDPROCESSING_NS}}}tc")
        ]
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    output = [f"| {' | '.join(rows[0])} |", f"| {' | '.join(['---'] * width)} |"]
    output.extend(f"| {' | '.join(row)} |" for row in rows[1:])
    return "\n".join(output)
