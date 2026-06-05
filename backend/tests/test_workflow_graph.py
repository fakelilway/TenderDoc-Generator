from services import workflow_graph


def test_langgraph_workflow_runs_to_human_review(monkeypatch) -> None:
    parsed = {
        "project_name": "测试项目",
        "qualification_list": [],
        "technical_score_items": [
            {
                "title": "施工组织设计",
                "description": "施工组织设计 30 分",
                "source": {"source_text": "", "page_number": None},
            }
        ],
        "invalid_bid_items": [],
    }
    monkeypatch.setattr(
        workflow_graph.retriever,
        "retrieve",
        lambda query, top_k=3: [],
    )
    monkeypatch.setattr(
        workflow_graph,
        "generate_bid_document",
        lambda requirements, chunks, bid_template=None: "# 标书\n\n## 施工组织设计\n\n完整段落说明施工部署。",
    )

    graph = workflow_graph.build_bid_workflow_graph()
    state = graph.invoke({"parsed": parsed, "iteration_count": 0})

    assert state["awaiting_human"] is True
    assert state["review_report"]["findings"]
