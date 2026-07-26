# Drift Investigator Agent

**This is the AI-Native Builder Technical Assessment submission.** Everything below the next horizontal rule is the pre-existing base project (a ProjectPro-sourced telecom churn model) this agent was built on top of — worth being upfront that the churn model itself predates this assessment; the agent is the new work.

## What this is

An agent that investigates model-drift alerts and explains the likely root cause in plain English — instead of a human opening a multi-megabyte Deepchecks HTML report or a raw JSON drift dump. Given a `feature` and `model_version`, it calls its own tools to fetch drift metrics, pipeline lineage, and model metadata, decides for itself what it needs and in what order, then writes a stakeholder report and pauses for human approval before finishing.

## Primary entry point

```bash
cd Code+Folder
python3 -m venv .venv_agent && source .venv_agent/bin/activate
pip install -r requirements-drift-investigator.txt
cp .env.example .env   # fill in GROQ_API_KEY or ANTHROPIC_API_KEY

python3 langgraph_investigator.py --feature total_charges --model-version v14 --agentic
```

Or the Streamlit UI (`streamlit run streamlit_app.py`), or LangGraph Studio (`langgraph dev` from a separate Python 3.11+ venv — see `planning/` for setup).

## Start here

- [`planning/01-problem-statement.md`](planning/01-problem-statement.md) — what problem this solves and what's real vs. synthetic
- [`planning/02-scope.md`](planning/02-scope.md) — **the finalized scope**: what's the primary deliverable vs. exploratory
- [`planning/03-architecture.md`](planning/03-architecture.md) — how the graph is built
- [`planning/04-trade-offs.md`](planning/04-trade-offs.md) — real bugs found and fixed live, guardrails added, and their limitations
- [`planning/agent-system-prompt.md`](planning/agent-system-prompt.md) — the agent's system prompt and a worked example
- [`planning/06-future-vision.md`](planning/06-future-vision.md) — what's aspirational, clearly separated from what shipped
- [`planning/07-demo-qa.md`](planning/07-demo-qa.md) — detailed demo Q&A (also as PDF)
- [`planning/08-demo-script.md`](planning/08-demo-script.md) — the demo video script

## Recordings & traces

- **LangGraph Studio architecture walkthrough** — [Loom video](https://www.loom.com/share/4b03ff1bf8504350a6cc320303dc7e12) tracing the compiled graph node by node, paired with a real [LangSmith trace](https://smith.langchain.com/public/6083ec6a-2169-4ad3-aea4-e6e7ac0642d7/r/019f9ebc-29c3-7631-839e-fe2ca144e0ed?start_time=2026-07-26T14%3A02%3A40.279583Z) of a live run.
- **Streamlit UI running locally** — [Loom video](https://www.loom.com/share/4b03ff1bf8504350a6cc320303dc7e12)
- **Guardrail catch in action** — [Loom video](https://www.loom.com/share/69db2736123b44238b455cb02927c49f) — the agent declining to fabricate a root cause when none exists in the data.

## Weakest part (asked directly, per the assessment's demo expectations)

The numeric-fabrication guardrail (see `04-trade-offs.md`) catches the model inventing numbers that don't exist anywhere in tool output, but missed a subtler case: the model borrowed a real number from an unrelated field and presented it as something else. A naive "does this number exist anywhere" check isn't enough to catch recontextualization — that's the next thing worth fixing.

---

# Telecom Machine Learning Project to Predict Customer Churn

*Pre-existing base project (ProjectPro-sourced), included for context only — trimmed to the essentials needed to understand and run it.*

## Business overview

Churn prediction — identifying customers likely to discontinue a subscription service — is a core problem for telecom operators. This project builds a churn prediction model, but its primary emphasis is on monitoring and adapting to changes in the underlying data over time (data drift) rather than a single model's point-in-time accuracy.

## Running the modular code

```bash
pip install -r requirements-churn-model.txt   # renamed from requirements.txt --
                                                # root requirements.txt is reserved
                                                # for the Drift Investigator agent
cd src
python Engine.py
```

Data is read from a local CSV. For the full original write-up — Colab/Jupyter setup, database/ODBC ingestion options, and the exploratory-data-analysis notebook — see the [ProjectPro course page](https://www.projectpro.io/data-science-use-cases/telecom-data-analysis-project) this project is sourced from.
