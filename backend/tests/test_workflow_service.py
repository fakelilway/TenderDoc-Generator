from rag.retriever import RetrievalResult
from schemas.bid import BidPackage, BidSectionOutline
from schemas.tender import TenderRequirements
from schemas.workflow import WorkflowState, WorkflowTraceEvent
from services import workflow_service
from utils.docx_exporter import VOLUME_MARKERS, combine_delivery_volumes


PARSED_JSON = {
    "project_name": "测试项目",
    "bid_format_requirements": "- 投标文件包括商务文件、技术文件、报价文件\n- 投标文件正本一份，副本四份",
    "qualification_list": [
        {
            "title": "项目经理",
            "description": "项目经理须具备一级建造师",
            "source": {"source_text": "", "page_number": None},
        }
    ],
    "technical_score_items": [
        {
            "title": "施工组织设计",
            "description": "施工组织设计 30 分",
            "source": {"source_text": "", "page_number": None},
        }
    ],
    "invalid_bid_items": [
        {
            "title": "保证金",
            "description": "未提交投标保证金按无效投标处理",
            "source": {"source_text": "", "page_number": None},
        }
    ],
}


def test_start_bid_workflow_resets_state_before_background_thread(monkeypatch) -> None:
    reset_calls = []
    thread_calls = []
    saved_states = []
    persisted_states = []
    status_updates = []

    class FakeThread:
        def __init__(self, target, args, name, daemon):
            thread_calls.append(
                {"target": target, "args": args, "name": name, "daemon": daemon}
            )

        def start(self):
            thread_calls.append({"started": True})

    monkeypatch.setattr(
        workflow_service,
        "_reset_workflow_state",
        lambda *args: reset_calls.append(args),
    )
    monkeypatch.setattr(workflow_service, "save_workflow_state", saved_states.append)
    monkeypatch.setattr(
        workflow_service,
        "_persist_state",
        lambda project_id, state: persisted_states.append(state),
    )
    monkeypatch.setattr(
        workflow_service,
        "_set_project_status",
        lambda project_id, status: status_updates.append((project_id, status)),
    )
    monkeypatch.setattr(
        workflow_service,
        "_fetch_project",
        lambda project_id: {
            "id": project_id,
            "parsed_json": PARSED_JSON,
            "confirmed_parsed_json": PARSED_JSON,
            "bid_outline_json": [
                {
                    "title": "第一章、总体施工组织布置及规划",
                    "required": True,
                    "source_item": "",
                    "focus_points": [],
                }
            ],
            "selected_chunk_ids": [],
        },
    )
    monkeypatch.setattr(workflow_service, "Thread", FakeThread)

    task = workflow_service.start_bid_workflow(7)

    assert reset_calls == [(7, "processing")]
    assert task["status"] == "processing"
    assert saved_states[0].trace_events[0].stage == "generate"
    # Traces without a project status transition only update Redis.
    assert persisted_states == []
    assert thread_calls[0]["args"] == (7,)
    assert thread_calls[0]["daemon"] is True
    assert thread_calls[-1] == {"started": True}


def test_start_bid_workflow_waits_for_outline_confirmation(monkeypatch) -> None:
    saved_states = []
    persisted_states = []
    status_updates = []
    monkeypatch.setattr(
        workflow_service,
        "_fetch_project",
        lambda project_id: {
            "id": project_id,
            "parsed_json": PARSED_JSON,
            "confirmed_parsed_json": None,
            "bid_outline_json": None,
            "selected_chunk_ids": [],
        },
    )
    monkeypatch.setattr(
        workflow_service,
        "load_workflow_state",
        lambda project_id: None,
    )
    monkeypatch.setattr(workflow_service, "save_workflow_state", saved_states.append)
    monkeypatch.setattr(
        workflow_service,
        "_persist_state",
        lambda project_id, state: persisted_states.append(state),
    )
    monkeypatch.setattr(
        workflow_service,
        "_set_project_status",
        lambda project_id, status: status_updates.append((project_id, status)),
    )

    task = workflow_service.start_bid_workflow(7)

    assert task["status"] == "outline_review"
    assert task["awaiting_human"] is True
    assert saved_states[0].status == "outline_review"
    assert persisted_states[0].awaiting_human is True
    assert status_updates[-1] == (7, "outline_review")


def test_run_bid_workflow_corrects_failures_and_pauses_for_human(monkeypatch) -> None:
    saved_states = []
    persisted_states = []
    status_updates = []
    monkeypatch.setattr(
        workflow_service, "load_workflow_state", lambda project_id: None
    )
    monkeypatch.setattr(workflow_service, "save_workflow_state", saved_states.append)
    monkeypatch.setattr(
        workflow_service,
        "_persist_state",
        lambda project_id, state: persisted_states.append(state),
    )
    monkeypatch.setattr(
        workflow_service,
        "_set_project_status",
        lambda project_id, status: status_updates.append((project_id, status)),
    )
    monkeypatch.setattr(
        workflow_service,
        "_fetch_project",
        lambda project_id: {"id": project_id, "parsed_json": PARSED_JSON},
    )
    monkeypatch.setattr(
        "services.template_service.bid_template_for_project",
        lambda project_id: None,
    )
    monkeypatch.setattr(
        workflow_service.retriever,
        "retrieve",
        lambda query, top_k=3: [RetrievalResult(1, 1, "施工组织设计知识片段", {}, 0.1, 0.9)],
    )
    monkeypatch.setattr(
        workflow_service,
        "generate_bid_package",
        lambda requirements, chunks, bid_template=None, pricing_strategy=None, knowledge_images=None, bid_plan=None, tender_text="", company_profile=None: BidPackage(
            commercial_markdown="# 商务文件\n\n项目经理具备一级建造师。\n\n投标保证金已响应。",
            technical_markdown="# 技术文件\n\n## 施工组织设计\n\n项目经理具备一级建造师。",
            pricing_markdown="# 报价文件\n\n投标保证金已响应。",
            combined_markdown="# 标书\n\n## 施工组织设计\n\n项目经理具备一级建造师。\n\n投标保证金已响应。",
        ),
    )

    state = workflow_service.run_bid_workflow(7)

    assert state.status == "human_review"
    assert state.awaiting_human is True
    assert state.draft_volumes["commercial"].startswith("# 商务文件")
    assert 0 <= state.iteration_count <= workflow_service.MAX_CORRECTION_ITERATIONS
    assert state.review_report["fail_count"] == 0
    assert state.evidence_pack
    assert state.bid_plan
    event_stages = [event.stage for event in state.trace_events]
    assert event_stages[0] == "generate"
    assert "review" in event_stages
    assert event_stages[-1] == "confirm"
    assert any("RAG 检索完成" in event.message for event in state.trace_events)
    assert saved_states and persisted_states
    assert status_updates[0] == (7, "processing")


def test_retrieve_for_outline_treats_rag_as_material_not_structure(monkeypatch) -> None:
    captured = {}

    def fake_retrieve(query, top_k=9):
        captured["query"] = query
        captured["top_k"] = top_k
        return [RetrievalResult(1, 1, "历史施工措施片段", {}, 0.1, 0.9)]

    monkeypatch.setattr(workflow_service.retriever, "retrieve", fake_retrieve)

    chunks = workflow_service._retrieve_for_outline(
        TenderRequirements.model_validate(PARSED_JSON),
        [
            BidSectionOutline(
                title="第一章、总体施工组织布置及规划",
                focus_points=["施工组织设计 30 分"],
            )
        ],
    )

    assert captured["top_k"] == 9
    assert "安徽正奇" not in captured["query"]
    assert "技术文件格式" not in captured["query"]
    assert "素材参考" in captured["query"]
    assert chunks["第一章、总体施工组织布置及规划"][0].content == "历史施工措施片段"


def test_retrieve_for_outline_distributes_selected_chunks_by_overlap(
    monkeypatch,
) -> None:
    references = [
        {"chunk_id": 1, "document_id": 1, "content": "施工组织设计总体部署方案。", "metadata": {}},
        {"chunk_id": 2, "document_id": 1, "content": "施工进度计划与组织安排。", "metadata": {}},
        {"chunk_id": 3, "document_id": 1, "content": "施工现场平面布置方案。", "metadata": {}},
        {"chunk_id": 4, "document_id": 2, "content": "质量保证体系与质量控制措施。", "metadata": {}},
        {"chunk_id": 5, "document_id": 2, "content": "焊接质量检验控制要求。", "metadata": {}},
        {"chunk_id": 6, "document_id": 2, "content": "成品保护质量措施。", "metadata": {}},
        {"chunk_id": 7, "document_id": 3, "content": "项目联系电话名录。", "metadata": {}},
    ]
    monkeypatch.setattr(
        workflow_service,
        "get_knowledge_references",
        lambda chunk_ids: references,
    )
    outline = [
        BidSectionOutline(title="施工组织设计", focus_points=["总体部署"]),
        BidSectionOutline(title="质量保证措施", focus_points=["质量控制"]),
    ]

    result = workflow_service._retrieve_for_outline(
        TenderRequirements.model_validate(PARSED_JSON),
        outline,
        [1, 2, 3, 4, 5, 6, 7],
    )

    technical_ids = [chunk.chunk_id for chunk in result["施工组织设计"]]
    quality_ids = [chunk.chunk_id for chunk in result["质量保证措施"]]
    # Each section gets its own best-overlapping material, not the same first 3.
    assert technical_ids[:3] == [1, 2, 3]
    assert quality_ids[:3] == [4, 5, 6]
    # Every selected chunk lands in at least one section (no silent drops).
    assert set(technical_ids) | set(quality_ids) == {1, 2, 3, 4, 5, 6, 7}


def test_retrieve_for_outline_selected_chunks_fall_back_without_overlap(
    monkeypatch,
) -> None:
    references = [
        {"chunk_id": index, "document_id": 1, "content": "abc", "metadata": {}}
        for index in (1, 2, 3, 4)
    ]
    monkeypatch.setattr(
        workflow_service,
        "get_knowledge_references",
        lambda chunk_ids: references,
    )
    outline = [
        BidSectionOutline(title="施工组织设计", focus_points=[]),
        BidSectionOutline(title="质量保证措施", focus_points=[]),
    ]

    result = workflow_service._retrieve_for_outline(
        TenderRequirements.model_validate(PARSED_JSON),
        outline,
        [1, 2, 3, 4],
    )

    for section in outline:
        assert [chunk.chunk_id for chunk in result[section.title]] == [1, 2, 3]


def test_correct_markdown_keeps_volumes_clean_via_notes_marker() -> None:
    volumes = {
        "commercial": "# 商务文件\n\n## 资格审查资料\n\n营业执照与资质。",
        "technical": "# 技术文件\n\n## 施工组织设计\n\n施工部署。",
        "pricing": "# 报价文件\n\n## 投标报价说明\n\n报价构成。",
    }
    combined = combine_delivery_volumes("测试项目投标文件", volumes)
    report = {
        "findings": [
            {"rule": "missing_bond", "status": "fail", "suggestion": "补充投标保证金响应。"}
        ]
    }

    corrected = workflow_service.correct_markdown(combined, report)
    corrected = workflow_service._apply_human_corrections(
        corrected, {"note": "调整工期承诺。"}
    )
    recovered = workflow_service._volumes_from_combined_markdown(corrected)

    assert "## 审查修正说明" in corrected
    assert "## 人工修正意见" in corrected
    # Both meta blocks share one notes section instead of stacking markers.
    assert corrected.count(VOLUME_MARKERS["notes"]) == 1
    for label, body in volumes.items():
        assert recovered[label] == body
    for body in recovered.values():
        assert "审查修正说明" not in body
        assert "人工修正意见" not in body


def test_confirm_project_applies_human_corrections(monkeypatch) -> None:
    initial = WorkflowState(
        project_id=7,
        parsed=PARSED_JSON,
        draft_markdown="# 标书\n\n## 施工组织设计\n\n项目经理具备一级建造师。",
        review_report={"findings": [], "fail_count": 0},
        status="human_review",
        awaiting_human=True,
    )
    exported = []
    monkeypatch.setattr(
        workflow_service, "load_workflow_state", lambda project_id: initial
    )
    monkeypatch.setattr(workflow_service, "save_workflow_state", lambda state: None)
    monkeypatch.setattr(
        workflow_service, "_persist_state", lambda project_id, state: None
    )
    monkeypatch.setattr(
        workflow_service, "_set_project_status", lambda project_id, status: None
    )
    monkeypatch.setattr(
        workflow_service,
        "_fetch_project",
        lambda project_id: {"id": project_id, "parsed_json": PARSED_JSON},
    )
    monkeypatch.setattr(
        workflow_service.generation_service,
        "export_markdown_for_project",
        lambda project_id, markdown, quality: exported.append((markdown, quality)),
    )

    state = workflow_service.confirm_project(
        7,
        approved=True,
        corrections={"note": "补充投标保证金响应。"},
    )

    assert state.status == "approved"
    assert state.approved is True
    assert "补充投标保证金响应" in state.draft_markdown
    assert exported


def test_confirm_project_applies_corrections_on_top_of_edited_markdown(
    monkeypatch,
) -> None:
    initial = WorkflowState(
        project_id=7,
        parsed=PARSED_JSON,
        draft_markdown="# 标书\n\n## 施工组织设计\n\n旧草稿内容。",
        review_report={"findings": [], "fail_count": 0},
        status="human_review",
        awaiting_human=True,
    )
    edited = "# 标书\n\n## 施工组织设计\n\n人工编辑后的部署方案。"
    cleared = []
    exported = []
    monkeypatch.setattr(
        workflow_service, "load_workflow_state", lambda project_id: initial
    )
    monkeypatch.setattr(workflow_service, "save_workflow_state", lambda state: None)
    monkeypatch.setattr(
        workflow_service, "_persist_state", lambda project_id, state: None
    )
    monkeypatch.setattr(
        workflow_service, "_set_project_status", lambda project_id, status: None
    )
    monkeypatch.setattr(workflow_service, "_clear_edited_markdown", cleared.append)
    monkeypatch.setattr(
        workflow_service,
        "_fetch_project",
        lambda project_id: {
            "id": project_id,
            "parsed_json": PARSED_JSON,
            "edited_markdown": edited,
        },
    )
    monkeypatch.setattr(
        workflow_service.generation_service,
        "export_markdown_for_project",
        lambda project_id, markdown, quality: exported.append(markdown),
    )

    state = workflow_service.confirm_project(
        7,
        approved=True,
        corrections={"note": "补充投标保证金响应。"},
    )

    # The manual editor save is the base and this round's corrections are
    # applied on top of it instead of being overwritten.
    assert "人工编辑后的部署方案" in state.draft_markdown
    assert "补充投标保证金响应" in state.draft_markdown
    assert "旧草稿内容" not in state.draft_markdown
    # edited_markdown is consumed exactly once so it cannot go stale.
    assert cleared == [7]
    # The workflow draft keeps the meta notes for the review loop, while the
    # exported delivery markdown is stripped of notes and volume markers.
    assert "人工修正意见" in state.draft_markdown
    assert exported
    assert "人工修正意见" not in exported[0]
    assert "tdg:volume" not in exported[0]


def test_build_closure_test_report_calculates_detection_rate() -> None:
    report = {
        "findings": [
            {"rule": "a", "status": "fail"},
            {"rule": "b", "status": "pass"},
        ]
    }

    baseline = workflow_service.build_closure_test_report(report, ["a", "c"])

    assert baseline["detection_rate"] == 0.5
    assert baseline["detected_rules"] == ["a"]
    assert baseline["missed_rules"] == ["c"]


def test_persist_state_serializes_trace_event_datetimes(monkeypatch) -> None:
    dumped_payloads = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _sql, params):
            workflow_json = params[0]
            dumped_payloads.append(workflow_json.dumps(workflow_json.adapted))

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    state = WorkflowState(
        project_id=7,
        status="processing",
        trace_events=[
            WorkflowTraceEvent(
                stage="generate",
                status="running",
                message="测试 trace 序列化。",
            )
        ],
    )
    monkeypatch.setattr(workflow_service, "_connect", lambda: FakeConnection())

    workflow_service._persist_state(7, state)

    assert dumped_payloads
    assert "created_at" in dumped_payloads[0]
