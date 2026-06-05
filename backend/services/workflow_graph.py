from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agents.generator_agent import build_bid_outline, generate_bid_document, load_bid_template
from agents.parser_agent import parse_tender
from agents.reviewer_agent import review
from rag import retriever
from schemas.tender import TenderRequirements
from services.workflow_service import MAX_CORRECTION_ITERATIONS, correct_markdown


class BidGraphState(TypedDict, total=False):
    tender_text: str
    parsed: dict[str, Any]
    retrieved_chunks: dict[str, list[str]]
    draft_markdown: str
    review_report: dict[str, Any]
    iteration_count: int
    awaiting_human: bool


def build_bid_workflow_graph():
    graph = StateGraph(BidGraphState)
    graph.add_node("parse", parse_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("review", review_node)
    graph.add_node("correct", correct_node)
    graph.add_node("human_review", human_review_node)

    graph.set_entry_point("parse")
    graph.add_edge("parse", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "review")
    graph.add_conditional_edges(
        "review",
        should_correct,
        {
            "correct": "correct",
            "human_review": "human_review",
        },
    )
    graph.add_edge("correct", "review")
    graph.add_edge("human_review", END)
    return graph.compile()


def parse_node(state: BidGraphState) -> BidGraphState:
    if state.get("parsed"):
        return state
    tender_text = state.get("tender_text", "")
    parsed = parse_tender(tender_text)
    return {**state, "parsed": parsed.model_dump()}


def retrieve_node(state: BidGraphState) -> BidGraphState:
    requirements = TenderRequirements.model_validate(state["parsed"])
    bid_template = load_bid_template()
    retrieved: dict[str, list[str]] = {}
    for section in build_bid_outline(requirements, bid_template):
        query = (
            f"{requirements.project_name} "
            f"{section.title} "
            f"{' '.join(section.focus_points)}"
        )
        retrieved[section.title] = [
            result.content for result in retriever.retrieve(query, top_k=3)
        ]
    return {**state, "retrieved_chunks": retrieved}


def generate_node(state: BidGraphState) -> BidGraphState:
    requirements = TenderRequirements.model_validate(state["parsed"])
    markdown = generate_bid_document(
        requirements,
        state.get("retrieved_chunks", {}),
        load_bid_template(),
    )
    return {**state, "draft_markdown": markdown}


def review_node(state: BidGraphState) -> BidGraphState:
    requirements = TenderRequirements.model_validate(state["parsed"])
    report = review(requirements, state.get("draft_markdown", ""))
    return {**state, "review_report": report.model_dump()}


def correct_node(state: BidGraphState) -> BidGraphState:
    iteration_count = state.get("iteration_count", 0) + 1
    markdown = correct_markdown(
        state.get("draft_markdown", ""),
        state.get("review_report", {}),
    )
    return {**state, "draft_markdown": markdown, "iteration_count": iteration_count}


def human_review_node(state: BidGraphState) -> BidGraphState:
    return {**state, "awaiting_human": True}


def should_correct(state: BidGraphState) -> str:
    report = state.get("review_report", {})
    has_failures = bool(report.get("has_failures") or report.get("fail_count", 0) > 0)
    if has_failures and state.get("iteration_count", 0) < MAX_CORRECTION_ITERATIONS:
        return "correct"
    return "human_review"
