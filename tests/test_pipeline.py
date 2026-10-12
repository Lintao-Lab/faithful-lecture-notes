from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from lecture_summary_pipeline.models import (
    AssemblyPlan,
    NecessaryCrossReference,
    SectionWorkOrder,
)
from lecture_summary_pipeline.pipeline import (
    LectureSummaryPipeline,
    PipelineConfig,
    stitch_section_outputs,
)
from lecture_summary_pipeline.plan import (
    PlanContractError,
    audit_outputs,
    normalise_assembly_plan,
)


@dataclass(slots=True)
class FakeCompletion:
    value: object
    raw_text: str


def valid_raw_plan() -> AssemblyPlan:
    return AssemblyPlan(
        lecture_focus="Explain formation, then record practical announcements.",
        sections=[
            SectionWorkOrder(
                section_id="sec-a",
                section_title="Formation",
                section_type="substantive",
                purpose="Explain how agreement is formed.",
                central_concepts=["FORMATION-CENTRAL"],
                boundary_note="Leave administration to the final section.",
                necessary_cross_references=[
                    NecessaryCrossReference(
                        concept="Administrative arrangements",
                        target_section="sec-b",
                    )
                ],
            ),
            SectionWorkOrder(
                section_id="sec-b",
                section_title="Administrative Notes and Preview",
                section_type="administrative_preview",
                purpose="Record the assessment date and next-week preview.",
                central_concepts=["ADMIN-ITEM"],
                boundary_note="Do not expand the preview.",
                necessary_cross_references=[],
            ),
        ],
    )


class FakeClient:
    def __init__(self) -> None:
        self.architect_calls = 0
        self.assembler_calls = 0
        self.assembler_payloads: list[str] = []
        self.models: list[str] = []
        self.reasoning_efforts: list[str | None] = []

    def complete_json(self, **kwargs):
        self.architect_calls += 1
        plan = valid_raw_plan()
        return FakeCompletion(value=plan, raw_text=plan.model_dump_json(indent=2))

    async def acomplete_text(self, *, model, messages, reasoning_effort=None, **kwargs):
        self.assembler_calls += 1
        self.models.append(model)
        self.reasoning_efforts.append(reasoning_effort)
        payload = messages[-1]["content"]
        self.assembler_payloads.append(payload)
        section_id = re.search(r'"section_id":\s*"([^"]+)"', payload).group(1)
        title = re.search(r'"section_title":\s*"([^"]+)"', payload).group(1)
        if section_id == "1":
            return (
                f"## {section_id}. {title}\n\nFORMATION-CENTRAL explained.\n\n"
                "For a detailed analysis of Administrative arrangements, refer to Section 2."
            )
        return f"## {section_id}. {title}\n\n- Assessment date.\n- Brief preview."


class SemanticRetryClient(FakeClient):
    def complete_json(self, **kwargs):
        self.architect_calls += 1
        if self.architect_calls == 1:
            invalid = valid_raw_plan().model_copy(deep=True)
            invalid.sections[1].section_id = "sec-a"
            return FakeCompletion(
                value=invalid, raw_text=invalid.model_dump_json(indent=2)
            )
        plan = valid_raw_plan()
        return FakeCompletion(value=plan, raw_text=plan.model_dump_json(indent=2))


class FlakyAssemblerClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.remaining_failures = 1

    async def acomplete_text(self, **kwargs):
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise RuntimeError("temporary assembler failure")
        return await super().acomplete_text(**kwargs)


class PlanTests(unittest.TestCase):
    def test_normalisation_replaces_ids_and_remaps_cross_references(self) -> None:
        plan = normalise_assembly_plan(valid_raw_plan())
        self.assertEqual([section.section_id for section in plan.sections], ["1", "2"])
        self.assertEqual(
            plan.sections[0].necessary_cross_references[0].target_section, "2"
        )

    def test_unknown_cross_reference_target_is_rejected(self) -> None:
        plan = valid_raw_plan().model_copy(deep=True)
        plan.sections[0].necessary_cross_references[0].target_section = "missing"
        with self.assertRaises(PlanContractError):
            normalise_assembly_plan(plan)

    def test_whitespace_only_section_title_is_rejected(self) -> None:
        plan = valid_raw_plan().model_copy(deep=True)
        plan.sections[0].section_title = "   "
        with self.assertRaises(PlanContractError):
            normalise_assembly_plan(plan)

    def test_preview_wording_does_not_fail_audit(self) -> None:
        plan = normalise_assembly_plan(valid_raw_plan())
        plan.sections[0].purpose = "Explain formation and preview next week's topic."
        outputs = [
            "## 1. Formation\n\nNext week we will cover remedies.",
            "## 2. Administrative Notes and Preview\n\nPreview.",
        ]
        audit = audit_outputs(
            plan=plan, section_outputs=outputs, final_markdown="\n\n".join(outputs)
        )
        self.assertTrue(audit.passed)

    def test_administrative_section_is_optional(self) -> None:
        plan = normalise_assembly_plan(
            AssemblyPlan(
                lecture_focus="Explain formation, then consideration.",
                sections=[
                    SectionWorkOrder(
                        section_id="sec-a",
                        section_title="Formation",
                        section_type="substantive",
                        purpose="Explain how agreement is formed.",
                        central_concepts=["FORMATION-CENTRAL"],
                        boundary_note="",
                        necessary_cross_references=[],
                    ),
                    SectionWorkOrder(
                        section_id="sec-b",
                        section_title="Consideration",
                        section_type="substantive",
                        purpose="Explain the consideration requirement.",
                        central_concepts=["CONSIDERATION-CENTRAL"],
                        boundary_note="",
                        necessary_cross_references=[],
                    ),
                ],
            )
        )
        outputs = [
            "## 1. Formation\n\nFormation.",
            "## 2. Consideration\n\nConsideration.",
        ]
        audit = audit_outputs(
            plan=plan, section_outputs=outputs, final_markdown="\n\n".join(outputs)
        )
        self.assertTrue(audit.passed)

    def test_administrative_section_may_sit_before_the_end(self) -> None:
        raw = valid_raw_plan().model_copy(deep=True)
        raw.sections = [raw.sections[1], raw.sections[0]]
        plan = normalise_assembly_plan(raw)
        self.assertEqual(plan.sections[0].section_type, "administrative_preview")
        outputs = [
            "## 1. Administrative Notes and Preview\n\n- Assessment date.",
            "## 2. Formation\n\nFormation.",
        ]
        audit = audit_outputs(
            plan=plan, section_outputs=outputs, final_markdown="\n\n".join(outputs)
        )
        self.assertTrue(audit.passed)

    def test_a_second_administrative_section_is_rejected(self) -> None:
        plan = valid_raw_plan().model_copy(deep=True)
        plan.sections.append(plan.sections[1].model_copy(update={"section_id": "sec-c"}))
        with self.assertRaises(PlanContractError):
            normalise_assembly_plan(plan)

    def test_administrative_section_title_must_be_exact(self) -> None:
        plan = valid_raw_plan().model_copy(deep=True)
        plan.sections[1].section_title = "Admin Notes"
        with self.assertRaises(PlanContractError):
            normalise_assembly_plan(plan)

    def test_stitcher_removes_closed_and_open_thinking_blocks(self) -> None:
        self.assertEqual(
            stitch_section_outputs(["initial", "<think>hidden</think>\nextra"]),
            "initial\n\nextra",
        )
        self.assertEqual(stitch_section_outputs(["<think>unfinished"]), "")


class PipelineTests(unittest.TestCase):
    def _sources(self, root: Path) -> tuple[Path, Path]:
        transcript = root / "transcript.md"
        slides = root / "slides.md"
        transcript.write_text("Transcript source.", encoding="utf-8")
        slides.write_text("Slides source.", encoding="utf-8")
        return transcript, slides

    def _pipeline(
        self, client: FakeClient, *, resume: bool = False
    ) -> LectureSummaryPipeline:
        return LectureSummaryPipeline(
            client=client,
            config=PipelineConfig(
                parallelism=2,
                node_retry_attempts=2,
                node_retry_delay_seconds=0.0,
                resume=resume,
            ),
        )

    def test_end_to_end_run_is_isolated_compact_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            client = FakeClient()
            result = self._pipeline(client).run(
                transcript_path=transcript,
                slides_path=slides,
                output_dir=root / "run",
            )

            self.assertTrue(result.audit.passed)
            self.assertEqual(
                (client.architect_calls, client.assembler_calls),
                (1, 2),
            )
            self.assertTrue((root / "run" / "00_run_manifest.json").exists())
            self.assertTrue((root / "run" / "00_workflow.mmd").exists())
            self.assertTrue((root / "run" / "02_global_outline.md").exists())
            self.assertTrue((root / "run" / "05_audit.json").exists())
            self.assertIn("## 1. Formation", result.final_markdown)
            self.assertIn(
                "## 2. Administrative Notes and Preview", result.final_markdown
            )

            payloads = {
                re.search(r'"section_id":\s*"([^"]+)"', payload).group(1): payload
                for payload in client.assembler_payloads
            }
            self.assertIn("<Global_Outline>", payloads["1"])
            self.assertIn("FORMATION-CENTRAL", payloads["1"])
            self.assertNotIn("ADMIN-ITEM", payloads["1"])
            self.assertIn("ADMIN-ITEM", payloads["2"])
            self.assertNotIn("FORMATION-CENTRAL", payloads["2"])
            self.assertEqual(client.models, ["deepseek-v4-pro"] * 2)
            self.assertEqual(client.reasoning_efforts, ["max"] * 2)

            manifest = json.loads(
                (root / "run" / "00_run_manifest.json").read_text(encoding="utf-8")
            )
            stored_transcript = (root / "run" / "inputs" / "transcript.md").read_bytes()
            stored_architect_prompt = (
                root / "run" / "prompts" / "architect.md"
            ).read_bytes()
            self.assertEqual(
                hashlib.sha256(stored_transcript).hexdigest(),
                manifest["transcript"]["sha256"],
            )
            self.assertEqual(
                hashlib.sha256(stored_architect_prompt).hexdigest(),
                manifest["prompt_sha256"]["architect"],
            )
            self.assertEqual(
                set(manifest["prompt_sha256"]), {"architect", "assembler"}
            )
            self.assertFalse(
                [
                    path
                    for path in (root / "run").rglob("*")
                    if "case_coverage" in path.name
                ]
            )

            self.assertFalse(list((root / "run").rglob("*.messages.json")))
            requests = list((root / "run").rglob("*.request.json"))
            self.assertTrue(requests)
            combined = "\n".join(path.read_text(encoding="utf-8") for path in requests)
            self.assertNotIn("Transcript source.", combined)
            self.assertNotIn("Slides source.", combined)

    def test_nonempty_output_directory_requires_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "unrelated.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                self._pipeline(FakeClient()).run(
                    transcript_path=transcript,
                    slides_path=slides,
                    output_dir=run_dir,
                )

    def test_invalid_input_does_not_pollute_a_new_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript = root / "transcript.pptx"
            transcript.write_bytes(b"invalid native input")
            run_dir = root / "run"
            with self.assertRaisesRegex(ValueError, "could not be converted"):
                self._pipeline(FakeClient()).run(
                    transcript_path=transcript,
                    slides_path=None,
                    output_dir=run_dir,
                )
            self.assertTrue(run_dir.is_dir())
            self.assertFalse(any(run_dir.iterdir()))

    def test_graph_has_no_obsolete_case_coverage_node(self) -> None:
        graph = self._pipeline(FakeClient()).build_graph().get_graph()
        self.assertNotIn("case_coverage", graph.nodes)
        self.assertTrue(
            {
                "load_inputs",
                "architect",
                "prepare_assembler_jobs",
                "assemble_sections",
                "stitch_sections",
                "audit",
                "save_summary",
            }.issubset(graph.nodes)
        )

    def test_resume_reuses_all_completed_llm_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            run_dir = root / "run"
            first_client = FakeClient()
            self._pipeline(first_client).run(
                transcript_path=transcript, slides_path=slides, output_dir=run_dir
            )
            second_client = FakeClient()
            resumed = self._pipeline(second_client, resume=True).run(
                transcript_path=transcript, slides_path=slides, output_dir=run_dir
            )
            self.assertTrue(resumed.audit.passed)
            self.assertEqual(
                (second_client.architect_calls, second_client.assembler_calls),
                (0, 0),
            )
            architect_attempts = json.loads(
                (run_dir / "01_architect_attempts.json").read_text(encoding="utf-8")
            )
            self.assertEqual(architect_attempts[0]["status"], "resumed")
            for path in (run_dir / "03_sections").glob("*.attempts.json"):
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))[0]["status"], "resumed"
                )

    def test_resume_refuses_changed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            run_dir = root / "run"
            self._pipeline(FakeClient()).run(
                transcript_path=transcript, slides_path=slides, output_dir=run_dir
            )
            transcript.write_text("Changed transcript.", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Resume refused"):
                self._pipeline(FakeClient(), resume=True).run(
                    transcript_path=transcript, slides_path=slides, output_dir=run_dir
                )

    def test_resume_regenerates_only_an_invalid_section_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            run_dir = root / "run"
            self._pipeline(FakeClient()).run(
                transcript_path=transcript, slides_path=slides, output_dir=run_dir
            )
            section_path = sorted(
                (run_dir / "03_sections").glob("*.md")
            )[0]
            section_path.write_text(
                "## Wrong heading\n\nDamaged checkpoint.\n", encoding="utf-8"
            )

            resume_client = FakeClient()
            result = self._pipeline(resume_client, resume=True).run(
                transcript_path=transcript, slides_path=slides, output_dir=run_dir
            )

            self.assertTrue(result.audit.passed)
            self.assertEqual(
                (resume_client.architect_calls, resume_client.assembler_calls),
                (0, 1),
            )
            attempts = json.loads(
                section_path.with_suffix(".attempts.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [record["status"] for record in attempts],
                ["checkpoint_invalid", "ok"],
            )

    def test_architect_semantic_contract_failure_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            client = SemanticRetryClient()
            pipeline = self._pipeline(client)
            state = {
                "transcript_path": str(transcript),
                "slides_path": str(slides),
                "output_dir": str(root / "run"),
            }
            (root / "run").mkdir()
            state.update(pipeline._load_inputs(state))
            state.update(pipeline._architect(state))
            attempts = json.loads(
                (root / "run" / "01_architect_attempts.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(client.architect_calls, 2)
            self.assertEqual(
                [attempt["status"] for attempt in attempts], ["error", "ok"]
            )

    def test_assembler_transient_failure_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transcript, slides = self._sources(root)
            client = FlakyAssemblerClient()
            result = self._pipeline(client).run(
                transcript_path=transcript, slides_path=slides, output_dir=root / "run"
            )
            self.assertEqual(client.remaining_failures, 0)
            self.assertTrue(result.audit.passed)
            attempts = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (root / "run" / "03_sections").glob("*.attempts.json")
            ]
            self.assertTrue(any(len(records) == 2 for records in attempts))

    def test_default_config_uses_deepseek_v4_pro_max(self) -> None:
        config = PipelineConfig()
        self.assertEqual(
            [config.architect_model, config.assembler_model],
            ["deepseek-v4-pro"] * 2,
        )
        self.assertEqual(
            [
                config.architect_reasoning_effort,
                config.assembler_reasoning_effort,
            ],
            ["max"] * 2,
        )
        self.assertEqual(config.parallelism, 50)


if __name__ == "__main__":
    unittest.main()
