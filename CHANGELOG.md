# Changelog

## 0.2.0 — 2026-10-12

- **Notes now read like a student's own notebook.** Sections state the material directly instead of reporting the lecture — "Every graph has an even number of odd-degree vertices", not "The lecturer explained that…". Attribution is kept only where the source itself matters: the lecturer's own view, an exam-relevance signal, or a student question that shapes the point.
- **The administrative/preview section is optional.** Lectures with announcements or a preview get one such section, placed where the lecture itself puts that material; lectures without simply omit it. (Note: run folders started with 0.1.x cannot be resumed under 0.2.0.)
- **The final audit checks structure only.** It no longer scans the wording of your notes, so reasonable notes no longer fail on an innocent phrase like "next class"; checks are limited to section counts, headings, and cross-references.
- **Fixed on Windows:** run files are now written consistently, so the integrity hashes in the run manifest match what lands on disk.

## 0.1.0 — 2026-08-17

Initial public release.
