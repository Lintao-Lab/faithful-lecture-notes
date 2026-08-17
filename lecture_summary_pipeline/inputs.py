from __future__ import annotations

from pathlib import Path

from .convert import CONVERTIBLE_SUFFIXES, LEGACY_SUFFIXES, TEXT_SUFFIXES


DEFAULT_SLIDES_TEXT = "There are no slides for this lecture."


def load_source_text(
    path: str | Path | None,
    *,
    source_name: str,
    allow_missing: bool = False,
) -> str:
    """Load a source as Markdown text, converting PDF/PPTX/DOCX when needed."""

    if path is None:
        if allow_missing:
            return DEFAULT_SLIDES_TEXT
        raise ValueError(f"{source_name} path is required.")

    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError(f"{source_name} input does not exist: {source_path}")

    suffix = source_path.suffix.casefold()
    if suffix in LEGACY_SUFFIXES:
        modern_suffix = ".pptx" if suffix == ".ppt" else ".docx"
        raise ValueError(
            f"{source_name} is a legacy {suffix} file, which this tool cannot read: "
            f"{source_path}. Open it in Office/WPS and re-save it as "
            f"{modern_suffix} first."
        )
    if suffix in CONVERTIBLE_SUFFIXES:
        from .convert import convert_to_markdown

        text = convert_to_markdown(source_path, source_name=source_name)
    elif suffix in TEXT_SUFFIXES:
        try:
            text = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"{source_name} is not valid UTF-8 text: {source_path}"
            ) from exc
    else:
        supported = ", ".join(sorted(TEXT_SUFFIXES | CONVERTIBLE_SUFFIXES))
        raise ValueError(
            f"{source_name} has an unsupported format "
            f"({suffix or 'no extension'}): {source_path}. Supported formats: {supported}."
        )

    if not text.strip():
        raise ValueError(f"{source_name} input is empty: {source_path}")
    return text
