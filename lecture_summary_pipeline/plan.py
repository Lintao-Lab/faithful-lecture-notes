from __future__ import annotations

import re
from collections import Counter

from .models import (
    AssemblyPlan,
    AuditReport,
    NecessaryCrossReference,
    SectionWorkOrder,
)


class PlanContractError(ValueError):
    """Raised when a structured Architect response is unsafe to route."""


DETAILED_CROSS_REFERENCE_RE = re.compile(
    r"For\s+a\s+detailed\s+analysis\s+of\s+(?P<concept>[^,\n]+),\s*"
    r"refer\s+to\s+(?:Section\s+)?(?P<target>[0-9]+)",
    re.IGNORECASE,
)
PREVIEW_SIGNAL_RE = re.compile(
    r"\b(?:next\s+(?:week|lecture|class)|preview(?:s|ed|ing)?|"
    r"to\s+be\s+covered\s+next)\b",
    re.IGNORECASE,
)


def normalise_assembly_plan(plan: AssemblyPlan) -> AssemblyPlan:
    """Validate routing semantics and replace model-chosen IDs with stable numeric IDs."""

    if not plan.lecture_focus.strip():
        raise PlanContractError("lecture_focus must contain substantive text.")

    original_ids = [section.section_id.strip() for section in plan.sections]
    if any(not section_id for section_id in original_ids):
        raise PlanContractError("Every section_id must be non-empty.")

    duplicates = sorted(
        section_id for section_id, count in Counter(original_ids).items() if count > 1
    )
    if duplicates:
        raise PlanContractError(f"Duplicate section IDs: {', '.join(duplicates)}")

    _validate_section_types(plan)
    id_map = {
        section_id: str(index) for index, section_id in enumerate(original_ids, start=1)
    }
    normalised_sections: list[SectionWorkOrder] = []

    for index, section in enumerate(plan.sections, start=1):
        source_id = section.section_id.strip()
        if not section.section_title.strip():
            raise PlanContractError(f"Section {source_id} has an empty title.")
        if not section.purpose.strip():
            raise PlanContractError(f"Section {source_id} has an empty purpose.")
        concepts = _unique_non_empty(section.central_concepts)
        if section.section_type == "substantive" and not concepts:
            raise PlanContractError(
                f"Substantive section {source_id} has no central concepts."
            )

        cross_references: list[NecessaryCrossReference] = []
        seen_cross_references: set[tuple[str, str]] = set()
        for item in section.necessary_cross_references:
            target_source_id = _resolve_target_id(item.target_section, original_ids)
            if target_source_id is None:
                raise PlanContractError(
                    f"Section {source_id} has an unknown cross-reference target: {item.target_section}"
                )
            target_id = id_map[target_source_id]
            if target_id == str(index):
                raise PlanContractError(f"Section {source_id} cross-references itself.")
            concept = item.concept.strip()
            if not concept:
                raise PlanContractError(
                    f"Section {source_id} has an empty cross-reference concept."
                )
            key = (concept.casefold(), target_id)
            if key in seen_cross_references:
                continue
            seen_cross_references.add(key)
            cross_references.append(
                NecessaryCrossReference(concept=concept, target_section=target_id)
            )

        normalised_sections.append(
            section.model_copy(
                update={
                    "section_id": str(index),
                    "section_title": section.section_title.strip(),
                    "purpose": section.purpose.strip(),
                    "central_concepts": concepts,
                    "boundary_note": section.boundary_note.strip(),
                    "necessary_cross_references": cross_references,
                }
            )
        )

    return plan.model_copy(
        update={
            "lecture_focus": plan.lecture_focus.strip(),
            "sections": normalised_sections,
        }
    )


def render_global_outline(plan: AssemblyPlan) -> str:
    lines = ["# Global Outline", "", f"Lecture focus: {plan.lecture_focus}", ""]
    lines.extend(
        f"{section.section_id}. **{section.section_title}** — {section.purpose}"
        for section in plan.sections
    )
    return "\n".join(lines)


def render_work_order(section: SectionWorkOrder) -> str:
    lines = [
        f"# Section {section.section_id} Work Order",
        "",
        f"Title: {section.section_title}",
        f"Type: {section.section_type}",
        f"Purpose: {section.purpose}",
        "",
        "Central concepts:",
        "",
    ]
    lines.extend(f"- {concept}" for concept in section.central_concepts)
    if not section.central_concepts:
        lines.append("- None")
    lines.extend(
        [
            "",
            f"Boundary: {section.boundary_note or 'No special boundary.'}",
            "",
            "Necessary cross-references:",
            "",
        ]
    )
    lines.extend(
        f"- {item.concept} → section {item.target_section}"
        for item in section.necessary_cross_references
    )
    if not section.necessary_cross_references:
        lines.append("- None")
    return "\n".join(lines)


def has_expected_section_heading(section: SectionWorkOrder, output: str) -> bool:
    expected_heading = re.compile(
        rf"^\s*##\s+{re.escape(section.section_id)}\.\s+{re.escape(section.section_title)}\s*$",
        re.MULTILINE,
    )
    return bool(expected_heading.search(output or ""))


def audit_outputs(
    *,
    plan: AssemblyPlan,
    section_outputs: list[str],
    final_markdown: str,
) -> AuditReport:
    expected_ids = [section.section_id for section in plan.sections]
    id_counts = Counter(expected_ids)
    missing_ids = (
        expected_ids[len(section_outputs) :]
        if len(section_outputs) < len(expected_ids)
        else []
    )
    duplicate_ids = sorted(
        section_id for section_id, count in id_counts.items() if count > 1
    )
    valid_targets = set(expected_ids)

    invalid_targets: list[str] = []
    for section in plan.sections:
        for item in section.necessary_cross_references:
            if (
                item.target_section not in valid_targets
                or item.target_section == section.section_id
            ):
                invalid_targets.append(
                    f"{section.section_id}:{item.concept}->{item.target_section}"
                )

    missing_headings: list[str] = []
    empty_sections: list[str] = []
    unplanned_mentions: list[str] = []
    preview_signals: list[str] = []
    for section, output in zip(plan.sections, section_outputs):
        text = output or ""
        if not text.strip():
            empty_sections.append(section.section_id)
        if not has_expected_section_heading(section, text):
            missing_headings.append(section.section_id)
        if section.section_type == "substantive":
            for match in PREVIEW_SIGNAL_RE.finditer(text):
                preview_signals.append(f"{section.section_id}:output:{match.group(0)}")

        planned_targets = {
            item.target_section for item in section.necessary_cross_references
        }
        for match in DETAILED_CROSS_REFERENCE_RE.finditer(text):
            target = match.group("target")
            if target not in planned_targets:
                unplanned_mentions.append(
                    f"{section.section_id}:{match.group('concept').strip()}->{target}"
                )

    for section in plan.sections[:-1]:
        fields = {
            "section_title": [section.section_title],
            "purpose": [section.purpose],
            "central_concepts": section.central_concepts,
            "boundary_note": [section.boundary_note],
        }
        for field_name, values in fields.items():
            for value in values:
                if PREVIEW_SIGNAL_RE.search(value):
                    preview_signals.append(f"{section.section_id}:{field_name}:{value}")

    plan_final_rule_passed = (
        bool(plan.sections)
        and all(section.section_type == "substantive" for section in plan.sections[:-1])
        and (
            plan.sections[-1].section_type == "administrative_preview"
            and plan.sections[-1].section_title == "Administrative Notes and Preview"
        )
    )
    final_h2_headings = re.findall(r"^##\s+(.+?)\s*$", final_markdown, re.MULTILINE)
    expected_final_h2 = (
        f"{plan.sections[-1].section_id}. {plan.sections[-1].section_title}"
        if plan.sections
        else ""
    )
    final_rule_passed = (
        plan_final_rule_passed
        and bool(final_h2_headings)
        and final_h2_headings[-1] == expected_final_h2
    )

    disallowed_markers = [
        marker for marker in ("/Users/", ".tmp_", "file://") if marker in final_markdown
    ]
    notes: list[str] = []
    section_count_guideline_passed = 6 <= len(plan.sections) <= 9
    if not section_count_guideline_passed:
        notes.append(
            "Section count falls outside the usual 6–9 range for a typical two-hour lecture; "
            "this is advisory rather than a hard failure."
        )
    if len(section_outputs) > len(plan.sections):
        notes.append("Generated section count exceeds the Architect plan.")

    passed = (
        not any(
            (
                missing_ids,
                duplicate_ids,
                invalid_targets,
                missing_headings,
                empty_sections,
                unplanned_mentions,
                preview_signals,
                disallowed_markers,
            )
        )
        and len(section_outputs) == len(plan.sections)
        and final_rule_passed
    )

    return AuditReport(
        passed=passed,
        expected_sections=len(plan.sections),
        generated_sections=len(section_outputs),
        section_count_guideline_passed=section_count_guideline_passed,
        final_section_rule_passed=final_rule_passed,
        missing_section_ids=missing_ids,
        duplicate_section_ids=duplicate_ids,
        invalid_cross_reference_targets=invalid_targets,
        sections_missing_expected_h2_heading=missing_headings,
        empty_sections=empty_sections,
        unplanned_cross_reference_mentions=unplanned_mentions,
        preview_signals_outside_final=preview_signals,
        disallowed_path_markers=disallowed_markers,
        notes=notes,
    )


def _validate_section_types(plan: AssemblyPlan) -> None:
    if not plan.sections:
        raise PlanContractError("The Assembly Plan must contain at least one section.")
    for section in plan.sections[:-1]:
        if section.section_type != "substantive":
            raise PlanContractError(
                "Only the final section may be administrative_preview."
            )
    final = plan.sections[-1]
    if final.section_type != "administrative_preview":
        raise PlanContractError("The final section must be administrative_preview.")
    if final.section_title.strip() != "Administrative Notes and Preview":
        raise PlanContractError(
            "The final section title must be 'Administrative Notes and Preview'."
        )


def _resolve_target_id(target: str, section_ids: list[str]) -> str | None:
    candidate = target.strip()
    if candidate in section_ids:
        return candidate
    match = re.match(r"^([0-9A-Za-z_-]+)(?:\s|[.:])", candidate)
    if match and match.group(1) in section_ids:
        return match.group(1)
    return None


def _unique_non_empty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
