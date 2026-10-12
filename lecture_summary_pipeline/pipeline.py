from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

from pydantic import BaseModel

from .inputs import load_source_text
from .models import AssemblyPlan, AuditReport, PipelineResult, SectionWorkOrder
from .plan import (
    PlanContractError,
    audit_outputs,
    has_expected_section_heading,
    normalise_assembly_plan,
    render_global_outline,
    render_work_order,
)
from .prompts import (
    ARCHITECT_SYSTEM_PROMPT,
    ASSEMBLER_SYSTEM_PROMPT,
    architect_correction_messages,
    architect_messages,
    assembler_messages,
)


class LLMClient(Protocol):
    def complete_json(self, **kwargs: Any) -> Any:
        ...

    def complete_text(self, **kwargs: Any) -> str:
        ...

    async def acomplete_text(self, **kwargs: Any) -> str:
        ...


class LectureSummaryState(TypedDict, total=False):
    transcript_path: str
    slides_path: str | None
    output_dir: str
    workflow_diagram: str
    transcript_text: str
    slides_text: str
    assembly_plan: AssemblyPlan
    architect_raw: str
    global_outline: str
    work_orders: list[str]
    section_outputs: list[str]
    final_notes: str
    audit: AuditReport
    summary_path: str
    audit_path: str


@dataclass(slots=True)
class PipelineConfig:
    architect_model: str = "deepseek-v4-pro"
    assembler_model: str = "deepseek-v4-pro"
    architect_temperature: float = 0.5
    assembler_temperature: float = 0.2
    architect_reasoning_effort: Literal["high", "max"] = "max"
    assembler_reasoning_effort: Literal["high", "max"] = "max"
    architect_max_tokens: int | None = 65536
    assembler_max_tokens: int | None = 65536
    parallelism: int = 50
    node_retry_attempts: int = 10
    node_retry_delay_seconds: float = 3.0
    architect_enable_thinking: bool = True
    assembler_enable_thinking: bool = True
    resume: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def semantic_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("resume", None)
        return data


class LectureSummaryPipeline:
    """Lecture-note pipeline: Architect, parallel Assemblers, mechanical stitch, audit."""

    def __init__(
        self,
        client: LLMClient,
        config: PipelineConfig | None = None,
        *,
        architect_client: LLMClient | None = None,
        assembler_client: LLMClient | None = None,
    ) -> None:
        self.client = client
        self.architect_client = architect_client or client
        self.assembler_client = assembler_client or client
        self.config = config or PipelineConfig()

    def build_graph(self) -> Any:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "LangGraph is not installed. Install it with `python3 -m pip install langgraph`."
            ) from exc

        graph = StateGraph(LectureSummaryState)
        graph.add_node("load_inputs", self._load_inputs)
        graph.add_node("architect", self._architect)
        graph.add_node("prepare_assembler_jobs", self._prepare_assembler_jobs)
        graph.add_node("assemble_sections", self._assemble_sections)
        graph.add_node("stitch_sections", self._stitch_sections)
        graph.add_node("audit", self._audit)
        graph.add_node("save_summary", self._save_summary)

        graph.add_edge(START, "load_inputs")
        graph.add_edge("load_inputs", "architect")
        graph.add_edge("architect", "prepare_assembler_jobs")
        graph.add_edge("prepare_assembler_jobs", "assemble_sections")
        graph.add_edge("assemble_sections", "stitch_sections")
        graph.add_edge("stitch_sections", "audit")
        graph.add_edge("audit", "save_summary")
        graph.add_edge("save_summary", END)
        return graph.compile()

    def run(
        self,
        *,
        transcript_path: str | Path,
        slides_path: str | Path | None,
        output_dir: str | Path,
    ) -> PipelineResult:
        output_path = Path(output_dir)
        self._preflight_output_dir(output_path)
        compiled_graph = self.build_graph()
        try:
            diagram = compiled_graph.get_graph().draw_mermaid()
        except Exception:
            diagram = ""
        final_state = compiled_graph.invoke(
            {
                "transcript_path": str(transcript_path),
                "slides_path": str(slides_path) if slides_path else None,
                "output_dir": str(output_path),
                "workflow_diagram": diagram,
            }
        )
        return PipelineResult(
            transcript_text=final_state["transcript_text"],
            slides_text=final_state["slides_text"],
            assembly_plan=final_state["assembly_plan"],
            global_outline=final_state["global_outline"],
            section_outputs=final_state["section_outputs"],
            final_markdown=final_state["final_notes"],
            audit=final_state["audit"],
            output_dir=Path(final_state["output_dir"]),
        )

    def _preflight_output_dir(self, output_dir: Path) -> None:
        if output_dir.exists() and not output_dir.is_dir():
            raise NotADirectoryError(f"Output path is not a directory: {output_dir}")
        entries = list(output_dir.iterdir()) if output_dir.exists() else []
        if entries and not self.config.resume:
            raise FileExistsError(
                f"Output directory is not empty: {output_dir}. Use a new run directory "
                "or pass --resume to continue an identical run."
            )
        if (
            entries
            and self.config.resume
            and not (output_dir / "00_run_manifest.json").is_file()
        ):
            raise RuntimeError(
                f"Cannot resume {output_dir}: 00_run_manifest.json is missing."
            )
        output_dir.mkdir(parents=True, exist_ok=True)

    def _load_inputs(self, state: LectureSummaryState) -> dict[str, Any]:
        output_dir = Path(state["output_dir"])
        transcript_text = load_source_text(
            state["transcript_path"], source_name="Transcript"
        )
        slides_text = load_source_text(
            state.get("slides_path"), source_name="Slides", allow_missing=True
        )
        prompt_hashes = {
            "architect": _sha256_text(ARCHITECT_SYSTEM_PROMPT),
            "assembler": _sha256_text(ASSEMBLER_SYSTEM_PROMPT),
        }
        manifest_body = {
            "contract_version": 4,
            "transcript": _source_manifest(state["transcript_path"], transcript_text),
            "slides": _source_manifest(state.get("slides_path"), slides_text),
            "config": self.config.semantic_dict(),
            "prompt_sha256": prompt_hashes,
            "implementation_sha256": _implementation_hashes(),
        }
        manifest = {
            **manifest_body,
            "run_fingerprint": _sha256_json(manifest_body),
        }
        manifest_path = output_dir / "00_run_manifest.json"
        if self.config.resume and manifest_path.is_file():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Cannot resume {output_dir}: 00_run_manifest.json is unreadable or invalid."
                ) from exc
            if previous.get("run_fingerprint") != manifest["run_fingerprint"]:
                raise RuntimeError(
                    "Resume refused: the input content, pipeline configuration, prompts, "
                    "or implementation do not match the existing run manifest."
                )

        self._write_json(manifest_path, manifest)
        if state.get("workflow_diagram"):
            self._write_text(output_dir / "00_workflow.mmd", state["workflow_diagram"])
        self._write_exact_text(output_dir / "inputs" / "transcript.md", transcript_text)
        self._write_exact_text(output_dir / "inputs" / "slides.md", slides_text)
        self._write_exact_text(
            output_dir / "prompts" / "architect.md", ARCHITECT_SYSTEM_PROMPT
        )
        self._write_exact_text(
            output_dir / "prompts" / "assembler.md", ASSEMBLER_SYSTEM_PROMPT
        )
        return {"transcript_text": transcript_text, "slides_text": slides_text}

    def _architect(self, state: LectureSummaryState) -> dict[str, Any]:
        output_dir = Path(state["output_dir"])
        plan_path = output_dir / "01_assembly_plan.json"
        request = {
            "node": "architect",
            "model": self.config.architect_model,
            "temperature": self.config.architect_temperature,
            "reasoning_effort": self.config.architect_reasoning_effort,
            "max_tokens": self.config.architect_max_tokens,
            "thinking": self.config.architect_enable_thinking,
            "prompt": "prompts/architect.md",
            "inputs": ["inputs/transcript.md", "inputs/slides.md"],
        }
        self._write_json(output_dir / "01_architect_request.json", request)
        attempts: list[dict[str, Any]] = []

        if self.config.resume and plan_path.is_file():
            try:
                plan = normalise_assembly_plan(
                    AssemblyPlan.model_validate_json(
                        plan_path.read_text(encoding="utf-8")
                    )
                )
            except Exception as exc:
                attempts.append(
                    {
                        "attempt": 0,
                        "status": "checkpoint_invalid",
                        "elapsed_seconds": 0.0,
                        "error": str(exc),
                    }
                )
            else:
                self._write_json(
                    output_dir / "01_architect_attempts.json",
                    [{"attempt": 0, "status": "resumed", "elapsed_seconds": 0.0}],
                )
                return {"assembly_plan": plan, "architect_raw": ""}

        base_messages = architect_messages(
            state["transcript_text"], state["slides_text"]
        )
        attempt_messages = base_messages
        last_error: Exception | None = None
        raw_plan: AssemblyPlan | None = None
        plan: AssemblyPlan | None = None
        raw_text = ""

        for attempt in range(1, max(1, self.config.node_retry_attempts) + 1):
            started = time.perf_counter()
            try:
                completion = self._complete_json(
                    self.architect_client,
                    model=self.config.architect_model,
                    messages=attempt_messages,
                    temperature=self.config.architect_temperature,
                    schema_type=AssemblyPlan,
                    schema=AssemblyPlan.model_json_schema(),
                    enable_thinking=self.config.architect_enable_thinking,
                    reasoning_effort=self.config.architect_reasoning_effort,
                    max_tokens=self.config.architect_max_tokens,
                    json_object=True,
                )
                raw_plan = _structured_value(completion, AssemblyPlan)
                raw_text = _structured_raw(completion, raw_plan)
                plan = normalise_assembly_plan(raw_plan)
                attempts.append(_attempt_record(attempt, "ok", started))
                break
            except Exception as exc:
                last_error = exc
                attempts.append(_attempt_record(attempt, "error", started, exc))
                if isinstance(exc, PlanContractError):
                    attempt_messages = architect_correction_messages(base_messages, exc)
                if attempt >= max(1, self.config.node_retry_attempts):
                    break
                time.sleep(max(0.0, self.config.node_retry_delay_seconds))

        self._write_json(output_dir / "01_architect_attempts.json", attempts)
        if plan is None or raw_plan is None:
            raise RuntimeError(
                f"Architect failed after {max(1, self.config.node_retry_attempts)} attempts"
            ) from last_error

        self._write_text(output_dir / "01_architect_raw.txt", raw_text)
        self._write_json(
            output_dir / "01_assembly_plan_raw.json", raw_plan.model_dump(mode="json")
        )
        self._write_json(plan_path, plan.model_dump(mode="json"))
        return {"assembly_plan": plan, "architect_raw": raw_text}

    def _prepare_assembler_jobs(self, state: LectureSummaryState) -> dict[str, Any]:
        plan = state["assembly_plan"]
        output_dir = Path(state["output_dir"])
        global_outline = render_global_outline(plan)
        work_orders: list[str] = []
        self._write_exact_text(output_dir / "02_global_outline.md", global_outline)
        for index, section in enumerate(plan.sections, start=1):
            stem = _section_stem(index, section)
            work_orders.append(render_work_order(section))
            self._write_json(
                output_dir / "02_work_orders" / f"{stem}.json",
                section.model_dump(mode="json"),
            )
        self._write_json(output_dir / "02_plan_audit.json", _plan_audit(plan))
        return {"global_outline": global_outline, "work_orders": work_orders}

    def _assemble_sections(self, state: LectureSummaryState) -> dict[str, Any]:
        return {"section_outputs": asyncio.run(self._assemble_sections_async(state))}

    async def _assemble_sections_async(self, state: LectureSummaryState) -> list[str]:
        output_dir = Path(state["output_dir"])
        sections_dir = output_dir / "03_sections"
        sections_dir.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(max(1, self.config.parallelism))

        async def english_section(
            index: int, section: SectionWorkOrder, stem: str
        ) -> str:
            """Return the finished section text, resuming from checkpoint when valid."""
            section_path = sections_dir / f"{stem}.md"
            request = {
                "node": "assembler",
                "section_id": section.section_id,
                "model": self.config.assembler_model,
                "temperature": self.config.assembler_temperature,
                "reasoning_effort": self.config.assembler_reasoning_effort,
                "max_tokens": self.config.assembler_max_tokens,
                "thinking": self.config.assembler_enable_thinking,
                "prompt": "../prompts/assembler.md",
                "global_outline": "../02_global_outline.md",
                "work_order": f"../02_work_orders/{stem}.json",
                "inputs": ["../inputs/transcript.md", "../inputs/slides.md"],
            }
            self._write_json(sections_dir / f"{stem}.request.json", request)
            attempts: list[dict[str, Any]] = []

            if self.config.resume and section_path.is_file():
                try:
                    existing = section_path.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError) as exc:
                    attempts.append(
                        {
                            "attempt": 0,
                            "status": "checkpoint_invalid",
                            "elapsed_seconds": 0.0,
                            "error": str(exc),
                        }
                    )
                else:
                    if existing and has_expected_section_heading(section, existing):
                        self._write_json(
                            sections_dir / f"{stem}.attempts.json",
                            [
                                {
                                    "attempt": 0,
                                    "status": "resumed",
                                    "elapsed_seconds": 0.0,
                                }
                            ],
                        )
                        return existing
                    attempts.append(
                        {
                            "attempt": 0,
                            "status": "checkpoint_invalid",
                            "elapsed_seconds": 0.0,
                            "error": "Section is empty or lacks its required H2 heading.",
                        }
                    )

            messages = assembler_messages(
                section=section,
                global_outline=state["global_outline"],
                transcript_text=state["transcript_text"],
                slides_text=state["slides_text"],
            )
            last_error: Exception | None = None
            text = ""
            for attempt in range(1, max(1, self.config.node_retry_attempts) + 1):
                started = time.perf_counter()
                try:
                    async with semaphore:
                        text = await _acomplete_text(
                            self.assembler_client,
                            model=self.config.assembler_model,
                            messages=messages,
                            temperature=self.config.assembler_temperature,
                            enable_thinking=self.config.assembler_enable_thinking,
                            reasoning_effort=self.config.assembler_reasoning_effort,
                            max_tokens=self.config.assembler_max_tokens,
                            json_object=False,
                        )
                    if not text.strip() or not has_expected_section_heading(
                        section, text
                    ):
                        raise ValueError(
                            f"Section {section.section_id} is empty or lacks its required H2 heading."
                        )
                    attempts.append(_attempt_record(attempt, "ok", started))
                    break
                except Exception as exc:
                    last_error = exc
                    attempts.append(_attempt_record(attempt, "error", started, exc))
                    if attempt >= max(1, self.config.node_retry_attempts):
                        break
                    await asyncio.sleep(max(0.0, self.config.node_retry_delay_seconds))
            self._write_json(sections_dir / f"{stem}.attempts.json", attempts)
            if not text.strip() or not has_expected_section_heading(section, text):
                raise RuntimeError(
                    f"Assembler section {section.section_id} failed after "
                    f"{max(1, self.config.node_retry_attempts)} attempts"
                ) from last_error
            self._write_text(section_path, text)
            return text

        async def assemble_one(index: int, section: SectionWorkOrder) -> str:
            stem = _section_stem(index, section)
            return await english_section(index, section, stem)

        tasks = [
            assemble_one(index, section)
            for index, section in enumerate(state["assembly_plan"].sections, start=1)
        ]
        return list(await asyncio.gather(*tasks))

    def _stitch_sections(self, state: LectureSummaryState) -> dict[str, Any]:
        return {"final_notes": stitch_section_outputs(state["section_outputs"])}

    def _audit(self, state: LectureSummaryState) -> dict[str, Any]:
        audit = audit_outputs(
            plan=state["assembly_plan"],
            section_outputs=state["section_outputs"],
            final_markdown=state["final_notes"],
        )
        audit_path = Path(state["output_dir"]) / "05_audit.json"
        self._write_json(audit_path, audit.model_dump(mode="json"))
        return {"audit": audit, "audit_path": str(audit_path)}

    def _save_summary(self, state: LectureSummaryState) -> dict[str, Any]:
        summary_path = Path(state["output_dir"]) / "04_final" / "lecture_summary.md"
        self._write_text(summary_path, state["final_notes"])
        return {"summary_path": str(summary_path)}

    def _complete_json(self, client: LLMClient, **kwargs: Any) -> Any:
        signature = inspect.signature(client.complete_json)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if not accepts_kwargs:
            supported = set(signature.parameters)
            kwargs = {key: value for key, value in kwargs.items() if key in supported}
        return client.complete_json(**kwargs)

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((text or "").rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _write_exact_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def stitch_section_outputs(section_outputs: list[str]) -> str:
    cleaned = [
        _strip_all_think_blocks(output or "").strip() for output in section_outputs
    ]
    return "\n\n".join(output for output in cleaned if output)


def _strip_all_think_blocks(text: str) -> str:
    text = re.sub(
        r"<think\b[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<think\b[^>]*>.*", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r".*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE, count=1)
    return re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE)


async def _acomplete_text(client: LLMClient, **kwargs: Any) -> str:
    if hasattr(client, "acomplete_text"):
        return await client.acomplete_text(**kwargs)
    return await asyncio.to_thread(client.complete_text, **kwargs)


def _attempt_record(
    attempt: int, status: str, started: float, error: Exception | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "attempt": attempt,
        "status": status,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    if error is not None:
        record["error"] = str(error)
    return record


def _structured_value(completion: Any, schema_type: type[BaseModel]) -> Any:
    if isinstance(completion, schema_type):
        return completion
    value = getattr(completion, "value", None)
    if isinstance(value, schema_type):
        return value
    if isinstance(completion, dict):
        return schema_type.model_validate(completion)
    raise TypeError("Structured completion did not contain the required schema value.")


def _structured_raw(completion: Any, value: BaseModel) -> str:
    raw_text = getattr(completion, "raw_text", "")
    return (
        raw_text
        if isinstance(raw_text, str) and raw_text
        else value.model_dump_json(indent=2)
    )


def _source_manifest(path: str | Path | None, text: str) -> dict[str, Any]:
    return {
        "path": str(Path(path).resolve()) if path else None,
        "sha256": _sha256_text(text),
        "characters": len(text),
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(data: Any) -> str:
    payload = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _sha256_text(payload)


def _implementation_hashes() -> dict[str, str]:
    package_dir = Path(__file__).resolve().parent
    filenames = (
        "client.py",
        "convert.py",
        "inputs.py",
        "models.py",
        "pipeline.py",
        "plan.py",
        "prompts.py",
    )
    return {
        filename: hashlib.sha256((package_dir / filename).read_bytes()).hexdigest()
        for filename in filenames
    }


def _section_stem(index: int, section: SectionWorkOrder) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", section.section_title).strip("_").lower()
    return f"{index:02d}_{section.section_id}_{slug or 'section'}"


def _plan_audit(plan: AssemblyPlan) -> dict[str, Any]:
    admin_sections = [
        section
        for section in plan.sections
        if section.section_type == "administrative_preview"
    ]
    return {
        "sections": len(plan.sections),
        "section_count_guideline_passed": 6 <= len(plan.sections) <= 9,
        "final_section_rule_passed": len(admin_sections) <= 1
        and (
            not admin_sections
            or admin_sections[0].section_title == "Administrative Notes and Preview"
        ),
        "cross_references": sum(
            len(section.necessary_cross_references) for section in plan.sections
        ),
    }
