from rag.retriever import RetrievalResult
from schemas.bid import BidPackage, BidSectionOutline
from schemas.tender import TenderRequirements
from schemas.workflow import WorkflowState, WorkflowTraceEvent
from services import workflow_service


PARSED_JSON = {
    "project_name": "测试项目",
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
    assert persisted_states[0].trace_events[0].message
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
        lambda requirements, chunks, bid_template=None, pricing_strategy=None: BidPackage(
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
