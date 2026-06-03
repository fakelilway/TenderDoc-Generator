from rag.retriever import RetrievalResult
from schemas.workflow import WorkflowState
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


def test_run_bid_workflow_corrects_failures_and_pauses_for_human(monkeypatch) -> None:
    saved_states = []
    persisted_states = []
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
        "_fetch_project",
        lambda project_id: {"id": project_id, "parsed_json": PARSED_JSON},
    )
    monkeypatch.setattr(
        workflow_service.retriever,
        "retrieve",
        lambda query, top_k=3: [RetrievalResult(1, 1, "施工组织设计知识片段", {}, 0.1, 0.9)],
    )
    monkeypatch.setattr(
        workflow_service,
        "generate_bid_document",
        lambda requirements, chunks: "# 标书\n\n## 施工组织设计\n\n仅说明施工部署。",
    )

    state = workflow_service.run_bid_workflow(7)

    assert state.status == "human_review"
    assert state.awaiting_human is True
    assert 1 <= state.iteration_count <= workflow_service.MAX_CORRECTION_ITERATIONS
    assert state.review_report["fail_count"] == 0
    assert saved_states and persisted_states


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
