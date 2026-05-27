"""Analysis agent LangGraph with case-documents fetch, OpenAI analysis, and DynamoDB persistence."""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from src.analysis_agent.langgraph.nodes import (
    Batch_dynamo_db_write,
    consumer_document_ingestion,
    creditor_document_ingestion,
    download_config_details,
    fetch_dispute_details_from_dynamo,
    download_creditor_documents,
    invoke_analysis_agent,
    route_after_creditor_documents,
    route_after_invoke_llm,
    route_after_mark_dispute_verified,
    route_on_workflow_error,
    update_status_dynamo_human_review,
    update_status_dynamo_verified,
    workflow_error_guard,
)
from src.analysis_agent.langgraph.state import AnalysisAgentState

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def build_analysis_agent_graph():
    g = StateGraph(AnalysisAgentState)
    g.add_node(
        "download_config_details",
        workflow_error_guard(download_config_details, node_name="download_config_details"),
    )
    g.add_node(
        "download_creditor_documents",
        workflow_error_guard(download_creditor_documents, node_name="download_creditor_documents"),
    )
    g.add_node(
        "process_consumer_documents",
        workflow_error_guard(consumer_document_ingestion, node_name="process_consumer_documents"),
    )
    g.add_node(
        "process_creditor_documents",
        workflow_error_guard(creditor_document_ingestion, node_name="process_creditor_documents"),
    )
    g.add_node(
        "invoke_llm",
        workflow_error_guard(invoke_analysis_agent, node_name="invoke_llm"),
    )
    g.add_node(
        "judgment_agent_bot_details_generation",
        workflow_error_guard(
            Batch_dynamo_db_write, node_name="judgment_agent_bot_details_generation"
        ),
    )
    g.add_node(
        "Human_review",
        workflow_error_guard(update_status_dynamo_human_review, node_name="Human_review"),
    )
    g.add_node(
        "mark_dispute_verified",
        workflow_error_guard(update_status_dynamo_verified, node_name="mark_dispute_verified"),
    )
    g.add_node(
        "fetch_dispute_details_from_dynamo",
        workflow_error_guard(
            fetch_dispute_details_from_dynamo, node_name="fetch_dispute_details_from_dynamo"
        ),
    )

    g.add_edge(START, "mark_dispute_verified")
    g.add_conditional_edges(
        "mark_dispute_verified",
        route_after_mark_dispute_verified,
        {
            "ERROR": "Human_review",
            "VALUES_PRESENT": "fetch_dispute_details_from_dynamo",
            "MISSING_VALUES": "Human_review",
        },
    )
    g.add_conditional_edges(
        "fetch_dispute_details_from_dynamo",
        route_on_workflow_error,
        {
            "ERROR": "Human_review",
            "CONTINUE": "download_config_details",
        },
    )
    g.add_conditional_edges(
        "download_config_details",
        route_on_workflow_error,
        {
            "ERROR": "Human_review",
            "CONTINUE": "download_creditor_documents",
        },
    )
    g.add_conditional_edges(
        "download_creditor_documents",
        route_after_creditor_documents,
        {
            "ERROR": "Human_review",
            "HUMAN_REVIEW": "Human_review",
            "PROCESS_CONSUMER": "process_consumer_documents",
            "PROCESS_CREDITOR": "process_creditor_documents",
        },
    )
    g.add_conditional_edges(
        "process_consumer_documents",
        route_on_workflow_error,
        {
            "ERROR": "Human_review",
            "CONTINUE": "process_creditor_documents",
        },
    )
    g.add_conditional_edges(
        "process_creditor_documents",
        route_on_workflow_error,
        {
            "ERROR": "Human_review",
            "CONTINUE": "invoke_llm",
        },
    )
    g.add_conditional_edges(
        "invoke_llm",
        route_on_workflow_error,
        {
            "ERROR": "Human_review",
            "CONTINUE": "judgment_agent_bot_details_generation",
        },
        #route_after_invoke_llm,
        #{
        #    "ERROR": "Human_review",
        #    "HIGH_CONFIDENCE": "judgment_agent_bot_details_generation",
        #    "LOW_CONFIDENCE": "Human_review",
        #},
    )
    g.add_conditional_edges(
        "judgment_agent_bot_details_generation",
        route_on_workflow_error,
        {
            "ERROR": "Human_review",
            "CONTINUE": END,
        },
    )
    g.add_edge("Human_review", END)
    return g.compile()


def build_invoke_graph(state: AnalysisAgentState):
    """Run the analysis workflow for one dispute (e.g. from a DynamoDB stream event)."""
    graph = build_analysis_agent_graph()
    logger.info("build_invoke_graph: account_id: %s, case_id: %s, dispute_id: %s, dispute_uuid: %s", state.get("account_id"), state.get("case_id"), state.get("dispute_id"), state.get("dispute_uuid"))
    return graph.invoke(state)
