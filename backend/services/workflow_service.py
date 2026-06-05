from __future__ import annotations

from threading import Thread
from uuid import uuid4

import redis
from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import build_bid_outline, generate_bid_document, load_bid_template
from agents.parser_agent import parse_tender
from agents.reviewer_agent import review
from core.config import settings
from rag import retriever
from schemas.tender import TenderRequirements
from schemas.workflow import WorkflowState, WorkflowTraceEvent
from services import generation_service
from services.project_service import ProjectNotFoundError, _connect


MAX_CORRECTION_ITERATIONS = 3


def start_bid_workflow(project_id: int, background_tasks=None) -> dict[str, object]:
    task_id = uuid4().hex
    _reset_workflow_state(project_id, "processing")
    initial_state = WorkflowState(project_id=project_id, status="processing")
    _append_trace(
        initial_state,
        "generate",
        "running",
        "后台工作流已启动，等待生成 Agent 接管。",
    )
    Thread(
        target=_run_background_workflow,
        args=(project_id,),
        name=f"workflow-{project_id}-{task_id[:8]}",
        daemon=True,
    ).start()
    return {
        "project_id": project_id,
        "task_id": task_id,
        "status": "processing",
        "awaiting_human": False,
        "iteration_count": 0,
        "review_report": None,
    }


def _run_background_workflow(project_id: int) -> None:
    try:
        run_bid_workflow(project_id)
    except Exception as error:
        state = load_workflow_state(project_id) or WorkflowState(project_id=project_id)
        _append_trace(
            state,
            "review",
            "failed",
            f"工作流失败：{error}",
            project_status="failed",
        )
        _set_project_status(project_id, "failed")


def run_bid_workflow(
    project_id: int,
    tender_text: str | None = None,
    pause_for_human: bool = True,
    max_iterations: int = MAX_CORRECTION_ITERATIONS,
) -> WorkflowState:
    _set_project_status(project_id, "processing")
    state = load_workflow_state(project_id) or WorkflowState(project_id=project_id)
    state.status = "processing"
    if tender_text:
        state.tender_text = tender_text

    _append_trace(
        state,
        "generate",
        "running",
        "读取解析结果，准备构建技术标/商务标生成上下文。",
        project_status="processing",
    )
    project = _fetch_project(project_id)
    requirements = _ensure_parsed_requirements(project, state)
    state.parsed = requirements.model_dump()

    bid_template = load_bid_template()
    template_note = (
        f"，使用模板：{bid_template.template_name}"
        if bid_template
        else "，未加载真实模板，使用默认兜底大纲"
    )
    _append_trace(
        state,
        "generate",
        "running",
        f"根据评分项、废标条款和模板结构生成标书大纲{template_note}。",
        project_status="processing",
    )
    outline = build_bid_outline(requirements, bid_template)
    _append_trace(
        state,
        "generate",
        "running",
        f"已生成 {len(outline)} 个大纲章节，开始检索企业知识库。",
        project_status="processing",
    )
    retrieved_by_section = _retrieve_for_outline(requirements, outline)
    state.retrieved_chunks = {
        title: [chunk.content for chunk in chunks]
        for title, chunks in retrieved_by_section.items()
    }
    retrieved_count = sum(len(chunks) for chunks in retrieved_by_section.values())

    _append_trace(
        state,
        "generate",
        "running",
        f"RAG 检索完成，匹配到 {retrieved_count} 个知识片段，开始生成 Markdown 初稿。",
        project_status="generating",
    )
    state.draft_markdown = generate_bid_document(
        requirements,
        retrieved_by_section,
        bid_template,
    )
    _append_trace(
        state,
        "generate",
        "done",
        f"生成 Agent 已输出 {len(state.draft_markdown)} 字 Markdown 初稿。",
        project_status="reviewing",
    )

    _append_trace(
        state,
        "review",
        "running",
        "审查 Agent 开始执行规则引擎和 LLM 废标项检查。",
        project_status="reviewing",
    )
    report = review(requirements, state.draft_markdown)
    state.review_report = report.model_dump()
    state.status = "reviewing"
    _append_trace(
        state,
        "review",
        "running",
        (
            f"审查完成：通过 {report.pass_count} 项，"
            f"风险 {report.fail_count} 项，提醒 {report.warning_count} 项。"
        ),
        project_status="reviewing",
    )

    while report.has_failures and state.iteration_count < max_iterations:
        state.iteration_count += 1
        _append_trace(
            state,
            "review",
            "running",
            f"发现未满足项，进入第 {state.iteration_count} 轮修正。",
            project_status="reviewing",
        )
        state.draft_markdown = correct_markdown(
            state.draft_markdown, report.model_dump()
        )
        report = review(requirements, state.draft_markdown)
        state.review_report = report.model_dump()
        _append_trace(
            state,
            "review",
            "running",
            (
                f"第 {state.iteration_count} 轮复查完成："
                f"剩余风险 {report.fail_count} 项。"
            ),
            project_status="reviewing",
        )

    if pause_for_human:
        state.awaiting_human = True
        state.status = "human_review"
        _append_trace(
            state,
            "confirm",
            "running",
            "工作流已暂停，等待人工终审确认或提交修改意见。",
            project_status="human_review",
        )
    else:
        _append_trace(
            state,
            "download",
            "running",
            "人工暂停已关闭，开始导出 Markdown 和 DOCX。",
            project_status="generating",
        )
        generation_service.export_markdown_for_project(
            project_id,
            state.draft_markdown,
            generation_service.evaluate_generation_quality(state.draft_markdown),
        )
        state.status = "finished"
        _append_trace(
            state,
            "download",
            "done",
            "最终文件已导出并上传到 MinIO。",
            project_status="finished",
        )

    save_workflow_state(state)
    _persist_state(project_id, state)
    return state


def confirm_project(
    project_id: int,
    approved: bool,
    corrections: dict | None = None,
) -> WorkflowState:
    state = load_workflow_state(project_id)
    if not state:
        raise ValueError("Workflow state was not found")

    state.corrections = corrections or {}
    if state.corrections:
        _append_trace(
            state,
            "confirm",
            "running",
            "收到人工修改意见，正在合并到 Markdown 草稿。",
            project_status="needs_revision",
        )
        state.draft_markdown = _apply_human_corrections(
            state.draft_markdown,
            state.corrections,
        )

    _append_trace(
        state,
        "review",
        "running",
        "人工确认后重新执行审查。",
        project_status="reviewing",
    )
    project = _fetch_project(project_id)
    requirements = TenderRequirements.model_validate(project["parsed_json"])
    report = review(requirements, state.draft_markdown)
    state.review_report = report.model_dump()
    state.approved = approved
    state.awaiting_human = False
    final_status = "approved" if approved else "needs_revision"
    state.status = final_status

    _append_trace(
        state,
        "download",
        "running",
        "正在导出最终 Markdown 和 Word DOCX，并上传到 MinIO。",
        project_status="generating",
    )
    generation_service.export_markdown_for_project(
        project_id,
        state.draft_markdown,
        generation_service.evaluate_generation_quality(state.draft_markdown),
    )
    _append_trace(
        state,
        "download",
        "done",
        "最终标书已上传，下载链接可用。",
        project_status=final_status,
    )
    _set_project_status(project_id, final_status)
    save_workflow_state(state)
    _persist_state(project_id, state)
    return state


def correct_markdown(markdown: str, review_report: dict) -> str:
    fail_items = [
        item
        for item in review_report.get("findings", [])
        if item.get("status") == "fail"
    ]
    if not fail_items:
        return markdown

    additions = ["", "## 审查修正说明", ""]
    for item in fail_items:
        suggestion = item.get("suggestion") or "补充响应招标文件要求。"
        additions.append(f"- 针对 `{item.get('rule', 'unknown')}`：{suggestion}")
    additions.append("")
    return markdown.rstrip() + "\n" + "\n".join(additions)


def build_closure_test_report(
    review_report: dict,
    expected_fail_rules: list[str],
) -> dict[str, float | int | list[str]]:
    findings = review_report.get("findings", [])
    failed_rules = {
        item.get("rule") for item in findings if item.get("status") == "fail"
    }
    expected = set(expected_fail_rules)
    detected = sorted(rule for rule in expected if rule in failed_rules)
    missed = sorted(expected - failed_rules)
    detection_rate = len(detected) / len(expected) if expected else 1.0
    return {
        "expected_fail_count": len(expected),
        "detected_fail_count": len(detected),
        "detection_rate": round(detection_rate, 4),
        "detected_rules": detected,
        "missed_rules": missed,
    }


def save_workflow_state(state: WorkflowState) -> None:
    client = _redis_client()
    client.set(_workflow_key(state.project_id), state.model_dump_json())


def _append_trace(
    state: WorkflowState,
    stage: str,
    status: str,
    message: str,
    project_status: str | None = None,
) -> None:
    state.trace_events.append(
        WorkflowTraceEvent(stage=stage, status=status, message=message)
    )
    if project_status:
        state.status = project_status
        _set_project_status(state.project_id, project_status)
    save_workflow_state(state)
    _persist_state(state.project_id, state)


def load_workflow_state(project_id: int) -> WorkflowState | None:
    client = _redis_client()
    raw = client.get(_workflow_key(project_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return WorkflowState.model_validate_json(raw)


def _ensure_parsed_requirements(
    project: dict,
    state: WorkflowState,
) -> TenderRequirements:
    if project.get("parsed_json"):
        return TenderRequirements.model_validate(project["parsed_json"])
    if not state.tender_text.strip():
        raise ValueError("Project has no parsed requirements or tender_text")
    parsed = parse_tender(state.tender_text)
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET parsed_json = %s, status = %s WHERE id = %s",
                (Json(parsed.model_dump()), "parsed", project["id"]),
            )
    return parsed


def _retrieve_for_outline(requirements, outline):
    query = (
        f"安徽正奇建设有限公司 投标文件 施工组织设计 技术文件格式 "
        f"{requirements.project_name} "
        f"{' '.join(section.title for section in outline)} "
        f"{' '.join(point for section in outline for point in section.focus_points)}"
    )
    try:
        shared_chunks = retriever.retrieve(query, top_k=9)
    except Exception:
        shared_chunks = []
    return {section.title: shared_chunks[:3] for section in outline}


def _fetch_project(project_id: int) -> dict:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, parsed_json
                FROM projects
                WHERE id = %s
                """,
                (project_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)


def _persist_state(project_id: int, state: WorkflowState) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET workflow_state_json = %s,
                    review_report_json = %s,
                    status = %s
                WHERE id = %s
                """,
                (
                    Json(state.model_dump(mode="json")),
                    Json(state.review_report),
                    state.status,
                    project_id,
                ),
            )


def _set_project_status(project_id: int, status: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET status = %s WHERE id = %s",
                (status, project_id),
            )


def _reset_workflow_state(project_id: int, status: str) -> None:
    _redis_client().delete(_workflow_key(project_id))
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET status = %s,
                    workflow_state_json = NULL,
                    review_report_json = NULL
                WHERE id = %s
                """,
                (status, project_id),
            )


def _apply_human_corrections(markdown: str, corrections: dict) -> str:
    note = corrections.get("note") or corrections.get("instruction") or ""
    sections = corrections.get("sections") or {}
    additions = ["", "## 人工修正意见", ""]
    if note:
        additions.append(note)
    for title, content in sections.items():
        additions.append(f"### {title}")
        additions.append(str(content))
    additions.append("")
    return markdown.rstrip() + "\n" + "\n".join(additions)


def _redis_client():
    return redis.Redis.from_url(settings.redis_url)


def _workflow_key(project_id: int) -> str:
    return f"workflow:{project_id}"
