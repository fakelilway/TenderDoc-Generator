from __future__ import annotations

from threading import Thread
from uuid import uuid4

import redis
from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import (
    build_bid_outline,
    build_bid_document_outline,
    generate_bid_package,
    load_bid_template,
)
from agents.parser_agent import parse_tender
from agents.pricing_agent import (
    extract_pricing_strategy,
    generate_pricing_strategy_report,
)
from agents.reviewer_agent import review
from core.config import settings
from rag import retriever
from schemas.bid import BidSectionOutline
from schemas.tender import TenderRequirements
from schemas.workflow import WorkflowState, WorkflowTraceEvent
from services import generation_service
from services.project_service import (
    ProjectNotFoundError,
    _connect,
    append_final_version,
    get_knowledge_references,
)


MAX_CORRECTION_ITERATIONS = 3


def start_bid_workflow(project_id: int, background_tasks=None) -> dict[str, object]:
    task_id = uuid4().hex
    project = _fetch_project(project_id)
    if not project.get("confirmed_parsed_json") or not project.get("bid_outline_json"):
        state = load_workflow_state(project_id) or WorkflowState(project_id=project_id)
        state.status = "outline_review"
        state.awaiting_human = True
        if project.get("parsed_json"):
            state.parsed = project.get("confirmed_parsed_json") or project.get(
                "parsed_json"
            )
        if project.get("bid_outline_json"):
            state.bid_outline = project["bid_outline_json"]
        if project.get("document_outline_json"):
            state.document_outline = project["document_outline_json"]
        _append_trace(
            state,
            "outline",
            "running",
            "工作流已暂停，等待用户确认解析结果和生成大纲。",
            project_status="outline_review",
        )
        return {
            "project_id": project_id,
            "task_id": task_id,
            "status": "outline_review",
            "awaiting_human": True,
            "iteration_count": state.iteration_count,
            "review_report": None,
        }

    _reset_workflow_state(project_id, "processing")
    initial_state = WorkflowState(project_id=project_id, status="processing")
    initial_state.parsed = project.get("confirmed_parsed_json") or project.get(
        "parsed_json"
    )
    initial_state.bid_outline = project.get("bid_outline_json") or []
    initial_state.document_outline = project.get("document_outline_json") or []
    initial_state.selected_chunk_ids = project.get("selected_chunk_ids") or []
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
        model_name=settings.openrouter_model,
        fallback=not settings.enable_llm_generation,
    )
    project = _fetch_project(project_id)
    requirements = _ensure_parsed_requirements(project, state)
    state.parsed = requirements.model_dump()

    pricing_strategy = extract_pricing_strategy(requirements)
    state.pricing_strategy = pricing_strategy.model_dump()
    _append_trace(
        state,
        "generate",
        "running",
        f"已提取商务标报价策略：付款条件 {len(pricing_strategy.payment_terms)} 项，担保约束 {len(pricing_strategy.guarantee_requirements)} 项。",
        project_status="processing",
    )

    from services import template_service

    bid_template = (
        template_service.bid_template_for_project(project_id) or load_bid_template()
    )
    template_note = (
        f"，使用模板：{bid_template.template_name}" if bid_template else "，未加载真实模板，使用默认兜底大纲"
    )
    _append_trace(
        state,
        "generate",
        "running",
        f"根据评分项、废标条款和模板结构生成标书大纲{template_note}。",
        project_status="processing",
    )
    outline = _outline_from_project(project, requirements, bid_template)
    state.bid_outline = [section.model_dump() for section in outline]
    state.document_outline = project.get("document_outline_json") or [
        section.model_dump()
        for section in build_bid_document_outline(requirements, bid_template)
    ]
    _append_trace(
        state,
        "generate",
        "running",
        f"已生成 {len(state.document_outline) or len(outline)} 个完整标书目录节点，开始检索企业知识库。",
        project_status="processing",
    )
    selected_chunk_ids = project.get("selected_chunk_ids") or state.selected_chunk_ids
    state.selected_chunk_ids = [int(chunk_id) for chunk_id in selected_chunk_ids]
    retrieved_by_section = _retrieve_for_outline(
        requirements, outline, state.selected_chunk_ids
    )
    state.retrieved_chunks = {
        title: [chunk.content for chunk in chunks]
        for title, chunks in retrieved_by_section.items()
    }
    state.rag_references = [
        {
            "section_title": title,
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "score": chunk.score,
            "title": chunk.metadata.get("file_name", ""),
            "snippet": chunk.content[:220],
            "metadata": chunk.metadata,
        }
        for title, chunks in retrieved_by_section.items()
        for chunk in chunks
    ]
    retrieved_count = sum(len(chunks) for chunks in retrieved_by_section.values())

    _append_trace(
        state,
        "generate",
        "running",
        f"RAG 检索完成，匹配到 {retrieved_count} 个知识片段，开始生成 Markdown 初稿。",
        project_status="generating",
    )
    bid_package = generate_bid_package(
        requirements,
        retrieved_by_section,
        bid_template,
        pricing_strategy=pricing_strategy,
        knowledge_images=_knowledge_images_for_requirements(requirements),
    )
    state.draft_volumes = bid_package.volume_map()
    state.draft_markdown = bid_package.combined_markdown
    _append_trace(
        state,
        "generate",
        "done",
        (
            "生成 Agent 已输出商务/技术/报价三卷 Markdown："
            f"商务 {len(state.draft_volumes.get('commercial', ''))} 字，"
            f"技术 {len(state.draft_volumes.get('technical', ''))} 字，"
            f"报价 {len(state.draft_volumes.get('pricing', ''))} 字。"
        ),
        project_status="reviewing",
        model_name=settings.openrouter_model,
        fallback=not settings.enable_llm_generation,
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
        state.draft_volumes = _volumes_from_combined_markdown(state.draft_markdown)
        report = review(requirements, state.draft_markdown)
        state.review_report = report.model_dump()
        _append_trace(
            state,
            "review",
            "running",
            (f"第 {state.iteration_count} 轮复查完成：" f"剩余风险 {report.fail_count} 项。"),
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
        exported = generation_service.export_markdown_for_project(
            project_id,
            state.draft_markdown,
            generation_service.evaluate_generation_quality(state.draft_markdown),
        )
        if exported:
            markdown_path, docx_path = exported
            state.final_versions = append_final_version(
                project_id, markdown_path, docx_path
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
        state.draft_volumes = _volumes_from_combined_markdown(state.draft_markdown)

    _append_trace(
        state,
        "review",
        "running",
        "人工确认后重新执行审查。",
        project_status="reviewing",
    )
    project = _fetch_project(project_id)
    if project.get("edited_markdown"):
        state.draft_markdown = project["edited_markdown"]
        state.draft_volumes = _volumes_from_combined_markdown(state.draft_markdown)
    requirements = TenderRequirements.model_validate(
        project.get("confirmed_parsed_json") or project["parsed_json"]
    )
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
    exported = generation_service.export_markdown_for_project(
        project_id,
        state.draft_markdown,
        generation_service.evaluate_generation_quality(state.draft_markdown),
    )
    state.final_checklist = _build_final_checklist(requirements, state)
    if exported:
        markdown_path, docx_path = exported
        state.final_versions = append_final_version(
            project_id, markdown_path, docx_path
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


def _volumes_from_combined_markdown(markdown: str) -> dict[str, str]:
    from utils.docx_exporter import split_delivery_markdown

    return split_delivery_markdown(markdown)


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
    duration_ms: int | None = None,
    model_name: str | None = None,
    fallback: bool = False,
) -> None:
    state.trace_events.append(
        WorkflowTraceEvent(
            stage=stage,
            status=status,
            message=message,
            duration_ms=duration_ms,
            model_name=model_name,
            fallback=fallback,
        )
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
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if parsed_json:
        return TenderRequirements.model_validate(parsed_json)
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


def _outline_from_project(
    project: dict,
    requirements: TenderRequirements,
    bid_template,
) -> list[BidSectionOutline]:
    outline_json = project.get("bid_outline_json") or []
    if outline_json:
        return [BidSectionOutline.model_validate(item) for item in outline_json]
    return build_bid_outline(requirements, bid_template)


def _retrieve_for_outline(requirements, outline, selected_chunk_ids=None):
    selected_chunk_ids = selected_chunk_ids or []
    if selected_chunk_ids:
        references = get_knowledge_references(selected_chunk_ids)
        selected_results = [
            retriever.RetrievalResult(
                chunk_id=reference["chunk_id"],
                document_id=reference.get("document_id"),
                content=reference.get("content", ""),
                metadata=reference.get("metadata", {}),
                distance=0.0,
                score=1.0,
            )
            for reference in references
        ]
        return {section.title: selected_results[:3] for section in outline}

    query = (
        "历史投标文件 施工组织设计 技术措施 正式标书措辞 素材参考 "
        f"{requirements.project_name} "
        f"{' '.join(section.title for section in outline)} "
        f"{' '.join(point for section in outline for point in section.focus_points)}"
    )
    try:
        shared_chunks = retriever.retrieve(query, top_k=9)
    except Exception:
        shared_chunks = []
    return {section.title: shared_chunks[:3] for section in outline}


def _knowledge_images_for_requirements(
    requirements: TenderRequirements,
) -> list[dict[str, object]]:
    from services import knowledge_service

    try:
        return knowledge_service.list_knowledge_image_references(
            generation_service._image_reference_query(requirements),
            limit=12,
        )
    except Exception:
        return []


def _fetch_project(project_id: int) -> dict:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    parsed_json,
                    confirmed_parsed_json,
                    bid_outline_json,
                    document_outline_json,
                    selected_chunk_ids,
                    edited_markdown
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
                    review_report_json = NULL,
                    edited_markdown = NULL
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


def _build_final_checklist(
    requirements: TenderRequirements,
    state: WorkflowState,
) -> dict:
    markdown = state.draft_markdown
    return {
        "invalid_bid_responses": [
            {
                "title": item.title,
                "requirement": item.description,
                "status": _finding_status(item.title, state.review_report or {}),
                "manual_confirmed": False,
            }
            for item in requirements.invalid_bid_items
        ],
        "manual_confirmation_points": [
            line.strip() for line in markdown.splitlines() if "人工确认点" in line
        ],
        "pricing_manual_fields": [
            line.strip()
            for line in markdown.splitlines()
            if "人工确认点" in line
            and any(keyword in line for keyword in ("报价", "金额", "单价", "清单"))
        ],
        "attachment_list": [
            item.title for item in requirements.qualification_list if item.title
        ],
    }


def _finding_status(title: str, review_report: dict) -> str:
    for finding in review_report.get("findings", []):
        haystack = (
            f"{finding.get('rule', '')} "
            f"{finding.get('field', '')} "
            f"{finding.get('evidence', '')}"
        )
        if title and title in haystack:
            return finding.get("status", "warning")
    return "pending"


def _redis_client():
    return redis.Redis.from_url(settings.redis_url)


def _workflow_key(project_id: int) -> str:
    return f"workflow:{project_id}"
