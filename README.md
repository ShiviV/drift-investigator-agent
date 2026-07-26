Drift Investigator Agent
This is the AI-Native Builder Technical Assessment submission. Everything below the next horizontal rule is the pre-existing base project (a ProjectPro-sourced telecom churn model) this agent was built on top of — worth being upfront that the churn model itself predates this assessment; the agent is the new work.

What this is
An agent that investigates model-drift alerts and explains the likely root cause in plain English — instead of a human opening a multi-megabyte Deepchecks HTML report or a raw JSON drift dump. Given a feature and model_version, it calls its own tools to fetch drift metrics, pipeline lineage, and model metadata, decides for itself what it needs and in what order, then writes a stakeholder report and pauses for human approval before finishing.

Primary entry point
Or the Streamlit UI (streamlit run streamlit_app.py), or LangGraph Studio (langgraph dev from a separate Python 3.11+ venv — see planning/ for setup).

Start here
Code+Folder/planning/01-problem-statement.md — what problem this solves and what's real vs. synthetic
Code+Folder/planning/02-scope.md — the finalized scope: what's the primary deliverable vs. exploratory
Code+Folder/planning/03-architecture.md — how the graph is built
Code+Folder/planning/04-trade-offs.md — real bugs found and fixed live, guardrails added, and their limitations
Code+Folder/planning/agent-system-prompt.md — the agent's system prompt and a worked example
Code+Folder/planning/06-future-vision.md — what's aspirational, clearly separated from what shipped
Code+Folder/planning/07-demo-qa.md — detailed demo Q&A (also as PDF)
Code+Folder/planning/08-demo-script.md — the demo video script
Weakest part (asked directly, per the assessment's demo expectations)
The numeric-fabrication guardrail (see 04-trade-offs.md) catches the model inventing numbers that don't exist anywhere in tool output, but missed a subtler case: the model borrowed a real number from an unrelated field and presented it as something else. A naive "does this number exist anywhere" check isn't enough to catch recontextualization — that's the next thing worth fixing.

