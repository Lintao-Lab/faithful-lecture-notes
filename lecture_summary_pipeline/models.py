from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NecessaryCrossReference(StrictModel):
    concept: str = Field(min_length=1)
    target_section: str = Field(min_length=1)


class SectionWorkOrder(StrictModel):
    section_id: str = Field(min_length=1)
    section_title: str = Field(min_length=1)
    section_type: Literal["substantive", "administrative_preview"]
    purpose: str = Field(min_length=1)
    central_concepts: list[str]
    boundary_note: str
    necessary_cross_references: list[NecessaryCrossReference]


class AssemblyPlan(StrictModel):
    lecture_focus: str = Field(min_length=1)
    sections: list[SectionWorkOrder] = Field(min_length=1)


class AuditReport(StrictModel):
    passed: bool
    expected_sections: int
    generated_sections: int
    section_count_guideline_passed: bool
    final_section_rule_passed: bool
    missing_section_ids: list[str] = Field(default_factory=list)
    duplicate_section_ids: list[str] = Field(default_factory=list)
    invalid_cross_reference_targets: list[str] = Field(default_factory=list)
    sections_missing_expected_h2_heading: list[str] = Field(default_factory=list)
    empty_sections: list[str] = Field(default_factory=list)
    unplanned_cross_reference_mentions: list[str] = Field(default_factory=list)
    preview_signals_outside_final: list[str] = Field(default_factory=list)
    disallowed_path_markers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class PipelineResult:
    transcript_text: str
    slides_text: str
    assembly_plan: AssemblyPlan
    global_outline: str
    section_outputs: list[str]
    final_markdown: str
    audit: AuditReport
    output_dir: Path
