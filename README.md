# Dispute Analysis (LangGraph + OpenAI)

Structured compliance analysis for credit-reported disputes, with **HITL** (`interrupt()` + resume), routing for human queue / BBB-CFPB / delete `03`, and automation stubs for e-Oscar vs VOD.

## Setup

```bash
cd Dispute-Analysis
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Optional: `OPENAI_MODEL` (defaults to `gpt-4o-mini`).

## Run

With `PYTHONPATH=src` from the repo root:

```bash
$env:PYTHONPATH="src"
python src/run.py --source written --narrative "Not my debt"
```

For **human-in-the-loop** (blocks on stdin after each interrupt):

```bash
python src/run.py --source bbb --hitl-stdin
```

When the API returns a dict containing `__interrupt__`, notify your user (see `common/notifications.notify_hitl_pending`), then call `resume_dispute(human_input, checkpointer=same_saver, thread_id=same_id)` from `dispute_graph.graph`.

## Project layout

- `src/dispute_graph/graph.py` — LangGraph compile (checkpointer), routing, `run_dispute`, `resume_dispute`, `INTERRUPT_KEY`
- `src/dispute_graph/nodes.py` — LLM analyze, `interrupt()` HITL nodes, finalize / DynamoDB
- `src/common/workflow_persistence.py` — Pydantic shape + builder for DynamoDB workflow columns
- `src/common/prompts.py` — System + user prompt templates

Replace the `record_auto_*` stubs with your e-Oscar and VOD integrations.
