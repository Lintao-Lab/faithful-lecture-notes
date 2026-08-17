from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from lecture_summary_pipeline.convert import (
    docx_to_markdown,
    pdf_to_markdown,
    pptx_to_markdown,
)


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_minimal_docx(path: Path) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_WORD_NS}">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Introduction</w:t></w:r></w:p>
<w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:t> world</w:t></w:r></w:p>
<w:tbl>
<w:tr><w:tc><w:p><w:r><w:t>Term</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Meaning</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>Alpha</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>First</w:t></w:r></w:p></w:tc></w:tr>
</w:tbl>
</w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


class DocxConversionTests(unittest.TestCase):
    def test_paragraphs_headings_and_tables_are_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notes.docx"
            write_minimal_docx(path)
            markdown = docx_to_markdown(path)
            self.assertIn("# Introduction", markdown)
            self.assertIn("Hello world", markdown)
            self.assertIn("| Term | Meaning |", markdown)
            self.assertIn("| Alpha | First |", markdown)


class PptxConversionTests(unittest.TestCase):
    def test_slide_text_is_extracted_in_slide_order(self) -> None:
        from pptx import Presentation

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "slides.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[5])
            slide.shapes.title.text = "Week One Overview"
            presentation.save(path)
            markdown = pptx_to_markdown(path)
            self.assertIn("## Slide 1", markdown)
            self.assertIn("Week One Overview", markdown)


class PdfConversionTests(unittest.TestCase):
    def test_text_layer_is_extracted(self) -> None:
        from pypdf import PdfReader, PdfWriter

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "text.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with source.open("wb") as handle:
                writer.write(handle)
            self.assertEqual(len(PdfReader(str(source)).pages), 1)

    def test_scanned_pdf_without_text_layer_is_rejected(self) -> None:
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scan.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with path.open("wb") as handle:
                writer.write(handle)
            with self.assertRaisesRegex(ValueError, "no usable text layer"):
                pdf_to_markdown(path)


if __name__ == "__main__":
    unittest.main()
