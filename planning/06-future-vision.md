# Future vision (roadmap, not current state)

**This document is aspirational.** Everything below describes a direction this project
could grow toward with a real team, real infrastructure, and far more than a 2-3 hour
build window. None of it is implemented. It exists here to answer the demo's "what
would you improve next" question concretely, and to separate "what shipped" from
"what's next" so neither gets misrepresented as the other. For what actually shipped,
see `01-problem-statement.md` through `04-trade-offs.md` and the code in this repo.

## The gap, plainly

| Vision | Shipped |
|---|---|
| Multi-agent system (Planner, Drift, Metadata, Lineage, Documentation, Root Cause, Notification agents) orchestrated via LangGraph | One agent, three tools, either a raw SDK tool-calling loop (`drift_investigator.py`) or a simplistic LangGraph ReAct agent (`langgraph_investigator.py`) |
| Real MLflow, Feast, DataHub/OpenLineage, Kafka, Postgres incident DB, vector DB (pgvector/Pinecone) | Three hand-authored YAML fixture files |
| Long-term + episodic memory, historical incident search | No memory across runs |
| Human-in-the-loop approval portal with Slack/Jira/PagerDuty escalation | Agent writes a markdown file; no approval workflow |
| 13-category enterprise guardrail system (RBAC, audit log, rate limits, PII redaction, schema validation) | A handful of prompt-level rules + a turn cap |
| Confidence-scored conditional branching, parallel tool execution | Sequential tool calls, no confidence score |

## What would actually be worth building next, in order

1. **A second, specialized agent for lineage/metadata retrieval**, separate from the
   root-cause reasoning agent — this is the smallest real step toward the "multi-agent"
   vision, and would let the metadata-lookup logic evolve independently (e.g. swapping
   the YAML stand-in for a real MLflow client) without touching the reasoning agent.
2. **Persistent memory**: a simple SQLite table of past investigations (job_id, root
   cause, resolution, outcome) that the agent can query — the smallest real step toward
   "episodic memory," well short of a vector DB.
3. **A real lineage/metadata source**: swap `training_run_metadata.yaml` for an actual
   MLflow tracking server once the pipeline adopts one (it doesn't today).
4. **Output validation guardrail**: check the LLM's final report actually contains all
   five required sections before showing it to a user, rather than trusting the model's
   formatting every time.
5. **Human-in-the-loop approval step**: even a minimal "approve / request more analysis"
   button in the Streamlit UI, before anything downstream (retraining, ticket creation)
   would be a meaningful step — full Slack/Jira/PagerDuty integration is much further out.

Multi-agent orchestration via LangGraph, a full vector-DB-backed documentation RAG
layer, and enterprise-grade guardrails (RBAC, audit logging, rate limits) are real
patterns worth adopting at production scale, but they assume infrastructure (a
lineage graph, an incident database, a documentation corpus) this project doesn't
have and that building convincingly in a few hours would mean faking — which is worse
than not building it at all.
