from __future__ import annotations

import logging
import re
from threading import Thread
from uuid import uuid4

import redis
from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import (
    GeneratorAgentError,
    build_bid_outline,
    build_bid_document_outline,
    generate_bid_package,
)
from agents.parser_agent import ParserAgentError, parse_tender
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
from services.company_profile_service import get_company_profile
from services.v2_generation_service import generate_v2_bid_package, V2BidPackage
from services.project_service import (
    ProjectNotFoundError,
    _connect,
    append_final_version,
    get_knowledge_references,
)

logger = logging.getLogger(__name__)

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
    except GeneratorAgentError as error:
        state = load_workflow_state(project_id) or WorkflowState(project_id=project_id)
        _append_trace(
            state,
            "generate",
            "failed",
            f"生成失败 [{type(error).__name__}]：{error}",
            project_status="failed",
        )
    except ParserAgentError as error:
        state = load_workflow_state(project_id) or WorkflowState(project_id=project_id)
        _append_trace(
            state,
            "parse",
            "failed",
            f"解析失败 [{type(error).__name__}]：{error}",
            project_status="failed",
        )
    except Exception as error:
        state = load_workflow_state(project_id) or WorkflowState(project_id=project_id)
        _append_trace(
            state,
            "review",
            "failed",
            f"工作流失败 [{type(error).__name__}]：{error}",
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
        fallback=False,
    )
    project = _fetch_project(project_id)
    if not state.tender_text and project.get("tender_text"):
        state.tender_text = project["tender_text"]
    if not state.tender_text:
        state.tender_text = _load_and_persist_tender_text(project)
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

    bid_template = template_service.bid_template_for_project(project_id)
    template_note = (
        f"，参考公司风格案例：{bid_template.template_name}"
        if bid_template
        else "，未选择公司风格案例，完全按招标文件格式和确认目录生成"
    )
    _append_trace(
        state,
        "generate",
        "running",
        f"根据评分项、废标条款、招标文件格式要求和人工确认目录生成标书大纲{template_note}。",
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
    knowledge_images = _knowledge_images_for_requirements(requirements)
    selected_references = (
        get_knowledge_references(state.selected_chunk_ids)
        if state.selected_chunk_ids
        else []
    )
    from services import bid_plan_service, evidence_pack_service

    template_profile = _template_profile_for_project(project_id)
    evidence_pack = evidence_pack_service.build_evidence_pack(
        requirements,
        selected_references=selected_references,
        image_references=knowledge_images,
        retrieved_results=retrieved_by_section,
    )
    bid_plan = bid_plan_service.build_bid_plan(
        requirements,
        template_profile=template_profile,
        evidence_pack=evidence_pack,
        document_outline=state.document_outline,
    )
    state.evidence_pack = evidence_pack.model_dump(mode="json")
    state.bid_plan = bid_plan.model_dump(mode="json")
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
        (
            f"RAG 检索完成，匹配到 {retrieved_count} 个知识片段；"
            f"证据包包含 {sum(evidence_pack.counts().values())} 项资料，开始生成 Markdown 初稿。"
        ),
        project_status="generating",
    )
    try:
        company_profile = get_company_profile()["profile"]
    except Exception:
        logger.warning("Company profile unavailable; generating without it")
        company_profile = None

    gen_mode = getattr(settings, "bid_generation_mode", "multi_agent")
    if gen_mode == "v2":
        v2_pkg = generate_v2_bid_package(
            requirements,
            retrieved_by_section,
            company_name=str((company_profile or {}).get("company_name", "") or settings.company_name),
            tender_text=state.tender_text,
            company_profile=company_profile,
        )
        state.draft_volumes = v2_pkg.volume_map()
        state.draft_markdown = v2_pkg.combined_markdown
        generation_mode = "v2_format_copy"
        if v2_pkg.audit_result:
            audit_summary = v2_pkg.audit_result.summary
        else:
            audit_summary = "审查未执行"
    else:
        bid_package = generate_bid_package(
            requirements,
            retrieved_by_section,
            bid_template,
            pricing_strategy=pricing_strategy,
            knowledge_images=knowledge_images,
            bid_plan=bid_plan,
            tender_text=state.tender_text,
            company_profile=company_profile,
            document_outline=state.document_outline,
        )
        state.draft_volumes = bid_package.volume_map()
        state.draft_markdown = bid_package.combined_markdown
        generation_mode = bid_package.generation_mode
        audit_summary = ""
    mode_note = f"生成模式：{generation_mode}"
    if audit_summary:
        mode_note += f" | {audit_summary}"
    _append_trace(
        state,
        "generate",
        "done",
        (
            "生成 Agent 已输出商务/技术/报价三卷 Markdown："
            f"商务 {len(state.draft_volumes.get('commercial', ''))} 字，"
            f"技术 {len(state.draft_volumes.get('technical', ''))} 字，"
            f"报价 {len(state.draft_volumes.get('pricing', ''))} 字。"
            f"{mode_note}。"
        ),
        project_status="reviewing",
        model_name=settings.openrouter_model,
        fallback=False,
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
        delivery_markdown = _delivery_markdown(state.draft_markdown)
        exported = generation_service.export_markdown_for_project(
            project_id,
            delivery_markdown,
            generation_service.evaluate_generation_quality(delivery_markdown),
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

    # The project row is fetched first so a manual editor save (edited_markdown)
    # becomes the base draft, with this round's corrections applied on top of it
    # instead of being silently overwritten.
    project = _fetch_project(project_id)
    if project.get("edited_markdown"):
        state.draft_markdown = project["edited_markdown"]
        _clear_edited_markdown(project_id)

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
    delivery_markdown = _delivery_markdown(state.draft_markdown)
    exported = generation_service.export_markdown_for_project(
        project_id,
        delivery_markdown,
        generation_service.evaluate_generation_quality(delivery_markdown),
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


def _delivery_markdown(markdown: str) -> str:
    from utils.docx_exporter import strip_meta_notes

    return strip_meta_notes(markdown)


def _append_meta_block(markdown: str, block: str) -> str:
    """Append a review/correction meta block into the marked notes section.

    Meta text must live under the ``notes`` volume marker so that
    ``split_delivery_markdown`` keeps every delivery volume clean of workflow
    annotations. When the document has no notes section yet, one is created at
    the end.
    """
    from utils.docx_exporter import VOLUME_MARKERS

    notes_marker = VOLUME_MARKERS["notes"]
    block = block.strip()
    if notes_marker not in markdown:
        return markdown.rstrip() + "\n" + "\n" + notes_marker + "\n\n" + block + "\n"

    lines = markdown.splitlines()
    markers = set(VOLUME_MARKERS.values())
    notes_index = next(
        index for index, line in enumerate(lines) if notes_marker in line
    )
    end_index = len(lines)
    for index in range(notes_index + 1, len(lines)):
        if lines[index].strip() in markers:
            end_index = index
            break
    head = "\n".join(lines[:end_index]).rstrip()
    tail = "\n".join(lines[end_index:]).strip()
    combined = head + "\n\n" + block + "\n"
    if tail:
        combined += "\n" + tail + "\n"
    return combined


def correct_markdown(markdown: str, review_report: dict) -> str:
    fail_items = [
        item
        for item in review_report.get("findings", [])
        if item.get("status") == "fail"
    ]
    if not fail_items:
        return markdown

    additions = ["## 审查修正说明", ""]
    for item in fail_items:
        suggestion = item.get("suggestion") or "补充响应招标文件要求。"
        additions.append(f"- 针对 `{item.get('rule', 'unknown')}`：{suggestion}")
    return _append_meta_block(markdown, "\n".join(additions))


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
    # Postgres persistence is comparatively expensive, so the full state is
    # only flushed on project status transitions and terminal events; Redis
    # always holds the latest trace.
    if project_status or status in ("done", "failed"):
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
        return _distribute_selected_chunks(selected_results, outline)

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


_SECTION_KEYWORD_SPLIT_RE = re.compile(r"[\s、，。；：/（）()【】\[\]:;,.\-—]+")


def _section_keywords(section) -> list[str]:
    keywords: list[str] = []
    for text in (section.title, *section.focus_points):
        for token in _SECTION_KEYWORD_SPLIT_RE.split(text or ""):
            token = token.strip()
            if len(token) >= 2 and token not in keywords:
                keywords.append(token)
    return keywords


def _keyword_overlap(keywords: list[str], haystack: str) -> int:
    """Score how well a chunk's text matches one outline section.

    Full keyword hits dominate; partial hits are counted through shared
    two-character grams so long Chinese headings still match related material.
    """
    score = 0
    for keyword in keywords:
        if keyword in haystack:
            score += len(keyword) * 2
            continue
        score += sum(
            1
            for index in range(len(keyword) - 1)
            if keyword[index : index + 2] in haystack
        )
    return score


def _distribute_selected_chunks(selected_results, outline):
    """Spread user-selected chunks across outline sections by keyword overlap.

    Each section keeps its top 3 overlapping chunks, and every selected chunk
    is guaranteed to land in at least its best-matching section so no manual
    selection is silently dropped. Without any overlap the legacy behaviour
    (first 3 chunks for every section) is kept.
    """
    if not outline:
        return {}
    if not selected_results:
        return {section.title: [] for section in outline}

    keywords_by_title = {
        section.title: _section_keywords(section) for section in outline
    }
    scores_by_title: dict[str, list[tuple[int, int]]] = {
        section.title: [] for section in outline
    }
    best_section_for_chunk: list[str | None] = []
    for index, chunk in enumerate(selected_results):
        haystack = f"{chunk.content} {chunk.metadata.get('file_name', '')}"
        best_score = 0
        best_title: str | None = None
        for section in outline:
            score = _keyword_overlap(keywords_by_title[section.title], haystack)
            scores_by_title[section.title].append((score, index))
            if score > best_score:
                best_score = score
                best_title = section.title
        best_section_for_chunk.append(best_title)

    if not any(title for title in best_section_for_chunk):
        return {section.title: selected_results[:3] for section in outline}

    assigned: dict[str, list[int]] = {}
    for section in outline:
        ranked = sorted(
            scores_by_title[section.title],
            key=lambda item: (-item[0], item[1]),
        )
        assigned[section.title] = [index for score, index in ranked[:3] if score > 0]

    placed = {index for indices in assigned.values() for index in indices}
    fallback_title = outline[0].title
    for index, best_title in enumerate(best_section_for_chunk):
        if index not in placed:
            assigned[best_title or fallback_title].append(index)

    return {
        title: [selected_results[index] for index in indices]
        for title, indices in assigned.items()
    }


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


def _template_profile_for_project(project_id: int):
    from services import template_service

    try:
        return template_service.template_profile_for_project(project_id)
    except Exception:
        return None


def _fetch_project(project_id: int) -> dict:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    tender_file_path,
                    parsed_json,
                    confirmed_parsed_json,
                    tender_text,
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


def _load_and_persist_tender_text(project: dict) -> str:
    tender_path = project.get("tender_file_path")
    if not tender_path:
        return ""
    try:
        from utils.file_parser import extract_text
        from utils.minio_client import minio_client

        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT file_name, file_path, file_type
                    FROM documents
                    WHERE project_id = %s AND file_path = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project["id"], tender_path),
                )
                document = cursor.fetchone()
        if not document:
            return ""
        file_bytes = minio_client.download_bytes(
            settings.minio_bucket,
            str(document["file_path"]),
        )
        text = extract_text(
            file_bytes,
            filename=str(document["file_name"]),
            content_type=document["file_type"],
        )
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE projects SET tender_text = %s WHERE id = %s",
                    (text, project["id"]),
                )
        return text
    except Exception:
        return ""


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


def _clear_edited_markdown(project_id: int) -> None:
    """Drop edited_markdown once it has been merged into the workflow draft.

    Leaving it in place would re-apply a stale manual edit on every later
    confirmation round and overwrite newer corrections.
    """
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET edited_markdown = NULL WHERE id = %s",
                (project_id,),
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
    additions = ["## 人工修正意见", ""]
    if note:
        additions.append(note)
    for title, content in sections.items():
        additions.append(f"### {title}")
        additions.append(str(content))
    return _append_meta_block(markdown, "\n".join(additions))


def _build_final_checklist(
    requirements: TenderRequirements,
    state: WorkflowState,
) -> dict:
    manual_fields = (state.pricing_strategy or {}).get("manual_fields") or []
    pricing_manual_fields = [
        _checklist_point(field.get("label"), field.get("reason"))
        for field in manual_fields
        if field.get("label") or field.get("reason")
    ]
    review_points = [
        _checklist_point(
            finding.get("rule"),
            finding.get("suggestion") or finding.get("evidence") or "需人工复核",
        )
        for finding in (state.review_report or {}).get("findings", [])
        if finding.get("status") != "pass"
    ]
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
        "manual_confirmation_points": pricing_manual_fields + review_points,
        "pricing_manual_fields": pricing_manual_fields,
        "attachment_list": [
            item.title for item in requirements.qualification_list if item.title
        ],
    }


def _checklist_point(label: object, detail: object) -> str:
    label_text = str(label or "").strip()
    detail_text = str(detail or "").strip()
    if label_text and detail_text:
        return f"{label_text}：{detail_text}"
    return label_text or detail_text


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
