from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lecture_summary_pipeline.inputs import DEFAULT_SLIDES_TEXT, load_source_text


class InputTests(unittest.TestCase):
    def test_markdown_and_text_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("source.md", "source.markdown", "source.txt"):
                path = Path(tmpdir) / name
                path.write_text("Canonical source", encoding="utf-8")
                self.assertEqual(
                    load_source_text(path, source_name="Source"), "Canonical source"
                )

    def test_missing_slides_have_explicit_fallback(self) -> None:
        self.assertEqual(
            load_source_text(None, source_name="Slides", allow_missing=True),
            DEFAULT_SLIDES_TEXT,
        )

    def test_legacy_binary_documents_are_rejected_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, modern in (("slides.ppt", ".pptx"), ("notes.doc", ".docx")):
                path = Path(tmpdir) / name
                path.write_bytes(b"legacy binary")
                with self.assertRaisesRegex(ValueError, "legacy") as caught:
                    load_source_text(path, source_name="Slides")
                self.assertIn(modern, str(caught.exception))

    def test_unsupported_suffixes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "slides.rtf"
            path.write_text("{\\rtf1}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported format"):
                load_source_text(path, source_name="Slides")

    def test_corrupt_convertible_documents_raise_a_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "slides.pptx"
            path.write_bytes(b"not a real presentation")
            with self.assertRaisesRegex(ValueError, "could not be converted"):
                load_source_text(path, source_name="Slides")

    def test_empty_and_non_utf8_sources_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            empty = Path(tmpdir) / "empty.md"
            empty.write_text("  \n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "is empty"):
                load_source_text(empty, source_name="Transcript")

            binary = Path(tmpdir) / "binary.txt"
            binary.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
                load_source_text(binary, source_name="Transcript")


if __name__ == "__main__":
    unittest.main()
