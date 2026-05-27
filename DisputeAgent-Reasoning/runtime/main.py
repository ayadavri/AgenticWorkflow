"""
AgentCore Runtime entrypoint for dispute analysis (LangGraph).

Exposes POST /invocations and GET /ping on port 8080 (BedrockAgentCoreApp contract).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from bedrock_agentcore import BedrockAgentCoreApp

from src.analysis_agent.langgraph.graph import build_invoke_graph
from src.analysis_agent.payload import prepare_initial_state_for_graph
from src.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


def _json_safe(value: Any) -> Any:
    """Best-effort conversion for AgentCore JSON responses."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


@app.entrypoint
def invoke(payload: dict) -> dict:
    """
    Handle AgentCore invocation payloads.

    Accepted shapes (same as Lambda):
    - Prepared workflow state with ``source_pk`` and ``source_sk``
    - DynamoDB stream: ``{ "PK", "SK", "NewImage": { ... } }``
    - EventBridge envelope: ``{ "detail": { "keys", "newImage", ... } }``
    """
    if not isinstance(payload, dict):
        payload = {}

    settings = get_settings()
    event_name = payload.get("eventName")
    if event_name is not None:
        event_name = str(event_name)

    try:
        initial_state, skip_response = prepare_initial_state_for_graph(
            payload,
            settings,
            event_name=event_name,
        )
    except ValueError as e:
        logger.warning("Invalid invocation payload: %s", e)
        return {"status": "error", "message": str(e)}

    if skip_response is not None:
        logger.info("Analysis skipped: %s", skip_response)
        return skip_response

    assert initial_state is not None
    result = build_invoke_graph(initial_state)
    return {"status": "success", "result": _json_safe(result)}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    logger.info("Starting AgentCore Runtime on port %s", port)
    app.run(port=port)
