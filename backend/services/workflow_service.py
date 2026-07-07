from __future__ import annotations

import logging
import re
from threading import Thread
from uuid import uuid4

import redis
from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import (
    build_bid_outline,
    build_bid_document_outline,
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
from services.v2_generation_service import generate_v2_bid_package
from services.project_service import (
    ProjectNotFoundError,
    _connect,
    _fetch_project,
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

    _append_trace(
        state,
        "generate",
        "running",
        "根据评分项、废标条款、招标文件格式要求和人工确认目录生成标书大纲。",
        project_status="processing",
    )
    outline = _outline_from_project(project, requirements)
    # 招标没识别出技术标结构 → 大纲会退化成"施工组织设计"一节占位,导致技术卷只生成一节(~7页)、
    # 占比详略与逐节知识库检索全部失效。这里按工程量清单分部分项+标准施组章节展开成完整多节大纲,
    # 让下面的"逐节检索知识库"和生成的"按占比定详略"都能真正落到每一节。
    outline = _expand_thin_outline(
        outline, requirements, state.tender_text, project.get("boq_text") or ""
    )
    state.bid_outline = [section.model_dump() for section in outline]
    state.document_outline = project.get("document_outline_json") or [
        section.model_dump()
        for section in build_bid_document_outline(requirements)
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
        requirements, outline, state.selected_chunk_ids, project_id=project_id
    )
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
            f"RAG 检索完成，匹配到 {retrieved_count} 个知识片段，"
            "开始生成 Markdown 初稿。"
        ),
        project_status="generating",
    )
    try:
        company_profile = get_company_profile()["profile"]
    except Exception:
        logger.warning("Company profile unavailable; generating without it")
        company_profile = None
    # 本项目选派的项目经理覆盖档案里的单个默认项目经理(M-人员名册)。
    company_profile = _apply_selected_project_manager(company_profile, project)

    generation_mode = "unknown"
    audit_summary = ""
    tender_bytes: bytes | None = None
    if _original_tender_extension(project) == ".pdf":
        from utils.minio_client import minio_client
        tender_path = str(project.get("tender_file_path", ""))
        logger.debug("Downloading PDF from MinIO: %s", tender_path)
        tender_bytes = minio_client.download_bytes(settings.minio_bucket, tender_path)

    v2_pkg = generate_v2_bid_package(
        requirements,
        retrieved_by_section,
        company_name=str((company_profile or {}).get("company_name", "") or settings.company_name),
        tender_text=state.tender_text,
        company_profile=company_profile,
        original_format_docx_available=_is_original_format(project),
        tender_bytes=tender_bytes,
        confirmed_technical_outline=state.bid_outline,
        project_id=project_id,  # ② 本项目定制插入图按节插入
        boq_text=project.get("boq_text") or "",  # 本项目上传的工程量清单(另册)→ 真实占比
    )
    state.draft_volumes = v2_pkg.volume_map()
    state.draft_markdown = v2_pkg.combined_markdown
    generation_mode = "v2_format_copy"
    state.v2_format_docx = getattr(v2_pkg, 'format_docx_path', None)
    state.v2_appendix_docx = getattr(v2_pkg, 'appendix_docx_path', None)
    if v2_pkg.audit_result:
        ar = v2_pkg.audit_result
        audit_summary = (
            f"通过={ar.passed}, 格式={len(ar.format_issues)} 内容={len(ar.content_issues)} "
            f"证据={len(ar.evidence_issues)} 招标覆盖={len(ar.coverage_issues)}"
        )
        # 招标覆盖校验:评分点未充分正面响应=major(不阻断出标),在此醒目告警让用户决定是否人工补强;
        # 废标项未实质规避=critical,会进入下面的 audit_blocked 分支硬拦。
        cov_majors = [i for i in ar.coverage_issues if i.severity == "major"]
        if cov_majors and not v2_pkg.audit_blocked:
            details = "；".join(i.problem for i in cov_majors[:6])
            audit_summary += f" | 招标覆盖告警(评分点未充分响应,建议人工补强): {details}"
    else:
        audit_summary = "审查未执行"

    # If audit blocked due to critical issues, save content for preview
    # but skip the review loop and mark as generation_failed.
    if v2_pkg.audit_blocked:
        critical_issues = [
            i for i in (v2_pkg.audit_result.all_issues if v2_pkg.audit_result else [])
            if i.severity == "critical"
        ]
        issue_details = "；".join(f"{i.location}: {i.problem}" for i in critical_issues[:5])
        _append_trace(
            state,
            "review",
            "failed",
            f"审查发现严重问题，已暂停后续流程（内容已保存供预览）：{issue_details}",
            project_status="generation_failed",
        )
        # Persist the draft so user can preview it
        save_workflow_state(state)
        _persist_state(project_id, state)
        return state
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
            "自动导出开关已打开，将跳过人工暂停进入导出。",
            project_status="generating",
        )
        state.status = "finished"
        _append_trace(
            state,
            "download",
            "done",
            "最终文件已导出并上传到 MinIO。",
            project_status="finished",
        )
        # Export handled in confirm_project

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
    # Pass marker-intact markdown so export can split volumes by tdg:volume
    # markers; export strips meta/markers itself for the readable bid.md.
    # split-then-strip avoids leaking commercial sections into the technical卷.
    exported = generation_service.export_markdown_for_project(
        project_id,
        state.draft_markdown,
        generation_service.evaluate_generation_quality(
            _delivery_markdown(state.draft_markdown)
        ),
        original_format_path=getattr(state, 'v2_format_docx', None),
        appendix_format_path=getattr(state, 'v2_appendix_docx', None),
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


def _original_tender_extension(project: dict) -> str | None:
    """Return the file extension of the original tender ('.pdf' or '.docx'), or None."""
    tender_path = str(project.get("tender_file_path") or "").lower()
    for ext in (".pdf", ".docx"):
        if tender_path.endswith(ext):
            return ext
    return None


def _is_original_format(project: dict) -> bool:
    """True if the tender is in a known original format (PDF or DOCX)."""
    return _original_tender_extension(project) is not None


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
) -> list[BidSectionOutline]:
    outline_json = project.get("bid_outline_json") or []
    if outline_json:
        return [BidSectionOutline.model_validate(item) for item in outline_json]
    return build_bid_outline(requirements)


# 标准施组"保证措施"章节(招标未写明结构时的兜底)。每条 (标题, 编写要点)。
_CANONICAL_ASSURANCE_SECTIONS = [
    ("施工进度计划与工期保证措施", "施工总进度计划、关键线路与控制性节点、各分部分项进度安排、人材机资源保障、工期风险与赶工补救措施。"),
    ("工程质量管理体系及保证措施", "质量管理体系与质量目标、各分部分项质量控制要点、原材料与试验检测、质量通病防治、成品保护措施。"),
    ("安全生产管理体系及保证措施", "安全管理体系与安全生产责任制、危险源辨识与管控、专项安全技术措施、安全教育培训与应急救援。"),
    ("环境保护与水土保持措施", "环境保护目标、扬尘/噪声/废水/弃渣控制、绿色施工、水土保持与生态恢复措施。"),
    ("文明施工与现场管理措施", "文明施工标准与现场布置、标识标牌、材料堆放、现场协调与周边社会关系处理。"),
    ("交通组织与安全保通方案", "施工期间交通组织、半幅施工或导改方案、行车安全与保通措施、夜间及交通高峰期施工安排。"),
    ("项目风险预测与防范及应急预案", "主要风险源识别与防范、应急组织机构、各类突发情况应急预案、抢险物资储备与演练。"),
]


# 施工方案章节排序 = 施工逻辑顺序(路基→排水→路面→桥涵→交安→绿化)。评审看重工序合理性,
# 不能按造价占比乱排;占比只决定每节"写多少"(adjust_min_chars),不决定"先后"。
_CONSTRUCTION_GROUP_ORDER = ["路基", "排水", "路面", "桥涵", "交安", "绿化"]


def _construction_rank(name: str) -> int:
    """按施工逻辑给分部分项排序:返回其在 _CONSTRUCTION_GROUP_ORDER 的位次,未知归到最后。"""
    from services import boq_service

    groups = boq_service._groups_of(name or "")
    for i, g in enumerate(_CONSTRUCTION_GROUP_ORDER):
        if g in groups:
            return i
    return len(_CONSTRUCTION_GROUP_ORDER)


# 各专业的施工工序(按施工先后逻辑排)。占比大的专业拆成更多道工序章节→大幅加量(每节一次LLM调用,
# 突破单节字数上限),且工序顺序天然合逻辑。
_DISCIPLINE_PROCESS = {
    "路基": [
        ("场地清理与旧路面、结构物挖除", "清表清淤、旧路面及基层挖除、结构物拆除、老路面碎石化处理。"),
        ("路基挖方与土方调配", "路基挖方、淤泥清挖、土方运输、利用土方与弃方处理。"),
        ("特殊路基处理与边坡防护", "软基/淤泥处理、换填加固、边坡及挡墙防护、杉木桩防护。"),
        ("路基填筑、压实与整修", "分层填筑、含水量控制、碾压、压实度与弯沉检测、路基整修。"),
    ],
    "排水": [
        ("排水管道与检查井施工", "管基处理、管道铺设、接口处理、检查井砌筑、排水试验。"),
    ],
    "路面": [
        ("旧路面病害处治与换板施工", "弯沉检测与路面状况调查、旧板破除与换板、板底脱空注浆、错台与裂缝处治。"),
        ("级配碎石基层与垫层施工", "级配碎石拌和运输、摊铺整平、碾压成型、压实度与平整度控制。"),
        ("水泥混凝土面板施工", "模板与传力杆/钢筋安装、混凝土拌和运输浇筑振捣、抹面拉毛、切缝。"),
        ("接缝处理、灌缝与成品养护", "胀缝/缩缝/纵缝设置、切缝清缝、灌缝胶灌注、面板养护与成品保护。"),
        ("沥青混凝土面层施工", "透层与黏层、沥青混合料拌和运输、摊铺、碾压、接缝与平整度控制。"),
    ],
    "桥涵": [
        ("圆管涵基础与管节安装施工", "基坑开挖、基础浇筑、管节预制与安装、接缝处理。"),
        ("桥涵结构防水与台背回填", "结构施工、防水层施工、台背回填与压实。"),
    ],
    "交安": [
        ("波形梁钢护栏施工", "立柱定位与打入、防阻块与波形梁安装、端头处理与旧护栏重新安装。"),
        ("交通标志施工", "标志基础与立柱安装、版面制作与更换、附着式标志安装。"),
        ("交通标线及附属设施施工", "标线放样与涂敷、轮廓标/示警桩/道口标柱/减速带/凸面镜安装。"),
    ],
    "绿化": [
        ("绿化与景观施工", "苗木选型与种植、客土与浇水养护、景观附属设施。"),
    ],
}


def _subsection_count(share_pct: float) -> int:
    """占比越大→拆成越多道工序章节(占比驱动'写多少'的结构级实现)。"""
    if share_pct >= 40:
        return 5
    if share_pct >= 25:
        return 4
    if share_pct >= 15:
        return 3
    if share_pct >= 5:
        return 2
    return 1


def _discipline_sections(boq) -> list[BidSectionOutline]:
    """按工程量清单分部分项 → 施工方案章节:占比越大拆成越多道工序(各自成节、各自一次LLM调用),
    工序按施工逻辑先后排;每节标题带专业前缀(让占比详略/知识库检索按专业落)。"""
    from services import boq_service

    out: list[BidSectionOutline] = []
    if boq is None or boq.is_empty():
        return out
    cats = sorted(boq.categories, key=lambda c: (_construction_rank(c.name), -c.share_pct))
    for c in cats:
        name = (c.name or "").strip()
        if not name or "总则" in name or "临时" in name:
            continue  # 总则/临时类并入"施工组织与现场布置"
        groups = boq_service._groups_of(name)
        procs = None
        for g in _CONSTRUCTION_GROUP_ORDER:
            if g in groups and g in _DISCIPLINE_PROCESS:
                procs = _DISCIPLINE_PROCESS[g]
                break
        kq = (c.key_quantities or "").strip()
        n = _subsection_count(c.share_pct)
        if procs:
            for i, (pname, pfocus) in enumerate(procs[:n]):
                focus = pfocus + (f" 引用本工程量清单真实工程量：{kq}" if (i == 0 and kq) else "")
                out.append(
                    BidSectionOutline(title=f"{name}·{pname}", required=True, focus_points=[focus])
                )
        else:
            title = name if name.endswith(("方案", "措施")) else f"{name}施工方案、方法与技术措施"
            out.append(
                BidSectionOutline(
                    title=title,
                    required=True,
                    focus_points=[
                        f"依据工程量清单真实工程量编写施工工艺、方法、技术措施与质量验收标准。主要工程量：{kq}"
                        if kq
                        else "依据工程量清单真实工程量编写施工工艺、方法、技术措施与质量验收标准。"
                    ],
                )
            )
    return out


def _extract_tender_format_structure(
    tender_text: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    """从招标"投标文件格式"抽技术标规定结构。

    返回 (施工组织设计编制要点, 附表清单[(编号, 名称)])。抽不到→([], [])。
    这是"目录必须跟招标投标文件格式一致 + 有表格就附表格"的数据源。
    """
    text = tender_text or ""
    aps: dict[str, str] = {}
    for m in re.finditer(r"附表([一二三四五六七八九十]+)\s+([^\n附\d]{2,20})", text):
        num, name = m.group(1), m.group(2).strip()
        if num not in aps and len(name) >= 3:
            aps[num] = name
    appendices = [(f"附表{k}", v) for k, v in aps.items()]
    points: list[str] = []
    idx = text.find("投标人应按照以下要点编制施工组织设计")
    if idx >= 0:
        seg = text[idx : idx + 1200]
        points = [
            p.strip()
            for p in re.findall(r"（[一二三四五六七八九十\d]+）\s*([^\n（）]{4,40})", seg)
        ]
    return points, appendices


def _tender_format_outline(
    appendices: list[tuple[str, str]],
    requirements: TenderRequirements,
    tender_text: str,
    boq_text: str,
) -> list[BidSectionOutline]:
    """按招标"投标文件格式"(施工组织设计编制要点 + 附表)搭技术标大纲——目录与招标一致。

    施工方案主体按工程量清单分部分项展开并引用真实工程量(保证深度);招标规定的每张附表
    逐一补为"附表节",生成时渲染成表格(满足"有表格就要附表格")。
    """
    try:
        from services import boq_service

        boq = boq_service.build_boq(tender_text or "", boq_text=boq_text or "")
    except Exception:
        boq = None

    def sec(title: str, focus: str) -> BidSectionOutline:
        return BidSectionOutline(title=title, required=True, focus_points=[focus])

    sections: list[BidSectionOutline] = [
        sec("施工组织与现场布置", "施工管理目标、施工组织机构与职责分工、施工现场总体布置、临时设施(营地/料场/便道/供电供水/消防)规划、主要资源进场安排。"),
        sec("劳动力、机械设备、材料的供应及资金流量计划", "劳动力组织与进退场计划、主要机械设备配置与进场计划、主要材料供应来源与质量保证、月度资金流量安排。"),
    ]
    # 编制要点③ 技术措施:按工程量清单分部分项→工序章节(占比越大拆越多道工序、写得越多;工序按施工逻辑排)。
    disciplines = _discipline_sections(boq)
    if not disciplines:
        for t in (  # 无清单兜底,施工逻辑顺序:路基→路面→桥涵→交安
            "路基工程施工方案、方法与技术措施",
            "路面工程施工方案、方法与技术措施",
            "桥涵工程施工方案、方法与技术措施",
            "交通安全设施工程施工方案、方法与技术措施",
        ):
            disciplines.append(sec(t, "依据招标与现场条件编写施工工艺、方法、技术措施与质量验收标准。"))
    sections.extend(disciplines)
    sections.extend(
        [
            sec("保畅方案与交通组织措施", "养护施工期间的交通组织、半幅施工或导改、行车安全与保通措施、便道与标志标牌设置、夜间及交通高峰期施工安排。"),
            sec("工程质量保证体系及保证措施", "质量管理体系与质量目标、各分部分项质量控制要点、原材料与试验检测、质量通病防治、成品保护。"),
            sec("安全生产保证体系及保证措施", "安全管理体系与安全生产责任制、危险源辨识与管控、专项安全技术措施、安全教育与应急救援。"),
            sec("环境保护、水土保持保证措施", "环境保护目标、扬尘/噪声/废水/弃渣控制、绿色施工、水土保持。"),
            sec("其他应说明的事项", "投标人认为需说明的其他技术事项、对本工程的合理化建议等。"),
        ]
    )
    # 招标规定的附表:逐张补为附表节(标题=招标原名),生成时渲染成表格。
    for num, name in appendices:
        sections.append(
            sec(f"{num} {name}", f"按招标文件{num}格式的附表(表格),由投标人填写。")
        )
    return sections


# 该按工程量清单拆成工序子节的"方案主章":标题含"施工方案"且是**汇总性**方案章。
# 各家招标叫法不一("主要工程项目的施工方案""重点、关键和难点工程的施工方案"
# "主要分部分项工程施工方案"…),都指同一章;认这些标记即触发拆节。不含这些标记的
# "质量/安全保证措施"等章不含"施工方案"字样,天然不受影响,不会被误拆。
_PLAN_CHAPTER_MARKERS = (
    "主要工程", "工程项目", "分部分项", "重点", "难点", "关键工程", "关键工序",
)


def _enrich_confirmed_outline(
    real: list[BidSectionOutline],
    tender_text: str,
    boq_text: str,
) -> list[BidSectionOutline]:
    """确认大纲是"像样的多节"也不照单全收——两处只做加法的兜底:

    ① 光秃秃的"…工程的施工方案"**汇总单节** → 按工程量清单拆成工序子节
      (占比定详略的深度机制得以生效;已含"·"工序节的大纲不动);
    ② 大纲里**没有附表节** → 从招标原文扫"附表一~五"补成附表节
      (附表装配的数据源不再只信解析器)。
    其余章节(编制要点/保证体系)原样保留:用户确认的结构只增不改。
    """
    out: list[BidSectionOutline] = []
    has_discipline = any("·" in str(getattr(s, "title", "") or "") for s in real)
    expanded = False
    for s in real:
        title = str(getattr(s, "title", "") or "")
        if (
            not expanded
            and not has_discipline
            and "施工方案" in title
            and any(m in title for m in _PLAN_CHAPTER_MARKERS)
        ):
            try:
                from services import boq_service

                boq = boq_service.build_boq(tender_text or "", boq_text=boq_text or "")
            except Exception:
                boq = None
            disciplines = _discipline_sections(boq)
            if disciplines:
                logger.info(
                    "确认大纲的'%s'为单节:按工程量清单拆成 %d 道工序节",
                    title[:24], len(disciplines),
                )
                out.extend(disciplines)
                expanded = True
                continue
        out.append(s)
    if not any(str(getattr(s, "title", "") or "").strip().startswith("附表") for s in out):
        _, appendices = _extract_tender_format_structure(tender_text or "")
        for num, name in appendices:
            out.append(
                BidSectionOutline(
                    title=f"{num} {name}",
                    required=True,
                    focus_points=[f"按招标文件{num}格式的附表(表格),由投标人填写。"],
                )
            )
        if appendices:
            logger.info("确认大纲无附表节:从招标原文补 %d 张附表节", len(appendices))
    return out


def _boq_discipline_fallback(
    requirements: TenderRequirements, tender_text: str, boq_text: str
) -> list[BidSectionOutline]:
    """招标未写明技术标结构时的兜底:按工程量清单分部分项 + 标准施组章节展开。"""
    try:
        from services import boq_service

        boq = boq_service.build_boq(tender_text or "", boq_text=boq_text or "")
    except Exception:
        boq = None
    sections: list[BidSectionOutline] = [
        BidSectionOutline(
            title="总体施工组织布置及规划",
            required=True,
            focus_points=["工程概况、编制依据与原则、施工目标、总体施工部署、施工组织机构与职责分工、主要人材机资源配置、施工总平面布置。"],
        )
    ]
    disciplines = _discipline_sections(boq)
    if not disciplines:
        for t in ("路基工程施工方案", "排水工程施工方案", "路面工程施工方案", "桥涵工程施工方案", "交通安全设施工程施工方案"):
            disciplines.append(
                BidSectionOutline(title=t, required=True, focus_points=["依据招标要求与现场条件编写施工工艺、技术措施与质量验收标准。"])
            )
    sections.extend(disciplines)
    sections.extend(
        BidSectionOutline(title=t, required=True, focus_points=[f])
        for t, f in _CANONICAL_ASSURANCE_SECTIONS
    )
    return sections


def _expand_thin_outline(
    outline: list[BidSectionOutline],
    requirements: TenderRequirements,
    tender_text: str,
    boq_text: str,
) -> list[BidSectionOutline]:
    """大纲退化成 ≤1 节占位时,重建完整技术标大纲。

    **优先以招标"投标文件格式"为准**:招标写明了施工组织设计编制要点 + 附表的,目录照它搭、
    附表逐张补成附表节(生成时渲染成表格);招标没写明结构的,才按工程量清单分部分项 + 标准
    施组章节兜底。用户已确认 ≥2 节真实大纲则原样保留。
    """
    real = [s for s in (outline or []) if str(getattr(s, "title", "") or "").strip()]
    placeholder = any(
        "未能从招标文件自动识别" in str(p)
        for s in real
        for p in (getattr(s, "focus_points", None) or [])
    )
    if len(real) > 1 and not placeholder:
        # 像样的多节大纲:结构尊重原样,但做两处**兜底增补**(别赌解析器手气——实测#181:
        # 解析器抽到8条编制要点但漏了附表清单 → 技术卷0附表、施工方案不拆节、字数-60%)。
        return _enrich_confirmed_outline(real, tender_text, boq_text)

    points, appendices = _extract_tender_format_structure(tender_text)
    if points or appendices:
        logger.info(
            "技术卷大纲按招标'投标文件格式'重建:编制要点 %d 项 + 附表 %d 张",
            len(points), len(appendices),
        )
        return _tender_format_outline(appendices, requirements, tender_text, boq_text)
    logger.info("招标未写明技术标结构,按工程量清单分部分项 + 标准施组章节展开")
    return _boq_discipline_fallback(requirements, tender_text, boq_text)


def _apply_selected_project_manager(company_profile, project):
    """用本项目选派的项目经理覆盖档案里写死的单个默认项目经理。

    选派存在 ``projects.selected_personnel.project_manager``(名册里的一条)。覆盖
    ``project_manager_name``/``project_manager_cert``,下游商务卷填充(投标人基本情况表、
    项目管理机构人员组成表)即自动用选定人选。未选派则原样返回。
    """
    sel = project.get("selected_personnel") or {}
    selected = sel.get("project_manager")
    tech = sel.get("tech_director")
    perf = project.get("selected_performance") or []  # 选中的类似业绩(多选)
    pm_ok = bool(selected and selected.get("name"))
    tech_ok = bool(tech and tech.get("name"))
    if not pm_ok and not tech_ok and not perf:
        return company_profile
    profile = dict(company_profile or {})
    # 选中业绩按名字去重(用户可能勾重),原样带给填表逻辑(_fill_performance_table 用)
    if perf:
        seen_p: set[str] = set()
        uniq = []
        for it in perf:
            nm = str(it.get("name", "")).strip()
            if nm and nm not in seen_p:
                seen_p.add(nm)
                uniq.append(it)
        profile["selected_performance"] = uniq
    if pm_ok:
        profile["project_manager_name"] = selected["name"]
        if selected.get("title"):
            profile["project_manager_title"] = selected["title"]
        builder_certs = selected.get("builder_certs") or []
        if builder_certs:
            cert_no = str((builder_certs[0]).get("cert_no") or "").strip()
            if cert_no:
                profile["project_manager_cert"] = cert_no
    # 员工整理的《类似项目信息表》记录注入 → 商务卷"近年完成的类似项目"六种节填表
    # (similar_project_fill_service 消费):投标人节按 selected_performance 从 _all 按名补全;
    # 项目经理/总工节各按选派人名下的项目填。
    try:
        from services import similar_project_info_service

        # 全部信息表记录:供投标人节按选中业绩的项目名补全全字段(与经理是谁无关)
        profile["similar_projects_all"] = (
            similar_project_info_service.list_similar_project_records()
        )
        if pm_ok:
            profile["similar_projects_pm"] = (
                similar_project_info_service.records_for_manager(selected["name"])
            )
        if tech_ok:
            profile["similar_projects_td"] = (
                similar_project_info_service.records_for_tech_leader(tech["name"])
            )
    except Exception:
        logger.warning("读取业绩信息表失败,类似项目信息表将留白待人工", exc_info=True)
    # 总工(项目技术负责人)选派 → 覆盖档案默认,下游商务卷人员表 + 证件插图自动用选定人
    if tech_ok:
        profile["tech_director_name"] = tech["name"]
        if tech.get("title"):
            profile["tech_director_title"] = tech["title"]
        tech_certs = tech.get("builder_certs") or []
        if tech_certs:
            tcert = str((tech_certs[0]).get("cert_no") or "").strip()
            if tcert:
                profile["tech_director_cert"] = tcert
    return profile


def _retrieve_for_outline(
    requirements, outline, selected_chunk_ids=None, project_id=None
):
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

    # Bias retrieval toward what评委 actually scores and what causes废标, so the
    # evidence pack carries material for scored criteria, not just section titles.
    score_terms = " ".join(item.title for item in requirements.technical_score_items)
    invalid_terms = " ".join(item.title for item in requirements.invalid_bid_items)
    query = (
        "历史投标文件 施工组织设计 技术措施 正式标书措辞 素材参考 "
        f"{requirements.project_name} "
        f"{' '.join(section.title for section in outline)} "
        f"{' '.join(point for section in outline for point in section.focus_points)} "
        f"{score_terms} {invalid_terms}"
    )
    try:
        # project_id → 本项目专用技术材料 ∪ 全局库(M23 grounding)。
        shared_chunks = retriever.retrieve(query, top_k=16, project_id=project_id)
    except Exception:
        shared_chunks = []

    # ① 公司历史施工方案语料(公司级×接地):给技术卷"写法/深度"接地,按本项目专业优先。
    plan_chunks = _retrieve_construction_plans(requirements, query)
    if plan_chunks:
        plan_ids = {chunk.chunk_id for chunk in plan_chunks}
        general = [chunk for chunk in shared_chunks if chunk.chunk_id not in plan_ids]
        # 每节 = 同类施组写作语料(前4)+ 通用证据(前4)。
        merged = plan_chunks[:4] + general[:4]
        return {section.title: merged for section in outline}
    return {section.title: shared_chunks[:6] for section in outline}


# 本项目专业关键词 → 规范专业(与施组语料的 specialty 标签对齐),用于检索同专业施组。
_PROJECT_SPECIALTY_KEYWORDS = (
    (("公路", "路面", "路基", "沥青", "路桥", "国道", "省道", "县道"), "公路工程"),
    (("市政", "管网", "给排水", "污水", "雨水", "管线", "道路照明"), "市政公用工程"),
    (("桥", "涵", "梁"), "桥涵工程"),
    (("电力", "电缆", "配电", "供电"), "电力工程"),
    (("绿化", "园林", "景观"), "绿化工程"),
)


def _derive_project_specialty(requirements) -> str:
    """从招标(项目名/范围/资格条款)粗推本项目专业,用于优先检索同专业历史施组。"""
    text = (
        f"{getattr(requirements, 'project_name', '')} "
        f"{getattr(requirements, 'tender_scope', '')} "
        + " ".join(
            f"{getattr(item, 'title', '')}{getattr(item, 'description', '')}"
            for item in (getattr(requirements, "qualification_list", []) or [])
        )
    )
    for keywords, specialty in _PROJECT_SPECIALTY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return specialty
    return ""


def _retrieve_construction_plans(requirements, base_query):
    """检索公司历史施工方案语料(同专业优先,任意专业补足)。全局可复用,不带 project_id。"""
    specialty = _derive_project_specialty(requirements)
    plan_query = (
        f"{specialty} 施工方案 施工工艺 技术措施 质量保证措施 安全文明施工 "
        f"{base_query[:200]}"
    )
    chunks: list = []
    seen: set = set()
    try:
        # 先同专业,再任意专业补足 → 同专业排前(推不出专业时只取任意专业)。
        for spec in ([specialty, None] if specialty else [None]):
            for chunk in retriever.retrieve_filtered(
                plan_query,
                top_k=8,
                document_category="施工方案",
                specialty=spec or None,
            ):
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    chunks.append(chunk)
    except Exception:
        return []
    return chunks


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


_redis_pool: redis.ConnectionPool | None = None


def _redis_client() -> redis.Redis:
    """Return a Redis client backed by a shared connection pool.

    Creating a new ``redis.Redis`` on every call previously instantiated a
    fresh TCP connection (or at least a new Python object). The pool keeps
    connections alive across calls, reducing latency and socket churn.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(settings.redis_url)
    return redis.Redis(connection_pool=_redis_pool)


def _workflow_key(project_id: int) -> str:
    return f"workflow:{project_id}"
