#!/usr/bin/env python3
"""
Simplistic LangGraph version of the drift investigator:

    START -> planner -> [drift, metadata, lineage] (parallel)
                              -> evidence -> reasoning -> human_approval -> END
                                                       \\-> END (if nothing flagged)

This is a DIFFERENT agentic pattern from drift_investigator.py's tool-calling loop:
there, the model itself decides which tools to call and when. Here, the graph
structure fixes the orchestration (fan out to 3 sources, aggregate, reason, pause
for a human) and the LLM is used for one reasoning step, not for choosing what to
fetch. Both are legitimate; this file exists to demonstrate the graph-orchestration
pattern specifically. See planning/06-future-vision.md for how this maps (and
doesn't) to the full multi-agent vision.

Honesty notes:
- "Lineage" here is the same pipeline_changelog.yaml used elsewhere -- a changelog
  of business/pipeline events, not a real lineage graph (no DataHub/OpenLineage).
- Human Approval is real: langgraph's interrupt()/Command(resume=...) mechanism,
  backed by a checkpointer, genuinely pauses graph execution until a human responds
  (CLI: a y/n prompt; Streamlit: Approve/Reject buttons). Nothing about the pause
  itself is simulated.
"""
import argparse
import os
import re
from datetime import datetime
from typing import Optional

# pydantic (used by LangGraph Studio to build the input form) can't generate a
# JSON schema from typing.TypedDict on Python < 3.12 -- it silently fails and
# Studio shows no input fields. typing_extensions.TypedDict carries the
# metadata pydantic needs and works the same otherwise.
from typing_extensions import TypedDict

import yaml
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from drift_investigator import (
    BASE_DIR,
    FIXTURE_DIR,
    AUDIENCE_INSTRUCTIONS,
    GROQ_MODEL,
    ANTHROPIC_MODEL,
    load_yaml,
    load_json,
    flag_checks,
    any_flagged,
    resolve_provider,
    tool_get_drift_report,
    tool_get_training_run_metadata,
    tool_get_pipeline_changelog,
    tool_get_drift_metrics,
    tool_get_lineage,
    tool_get_model_metadata,
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class InvestigationState(TypedDict, total=False):
    job_id: str
    audience: str
    drift_report: dict
    run_metadata: dict
    changelog: list
    flagged_checks: dict
    flagged: bool
    relevant_changelog: list
    narrative: str
    approved: Optional[bool]
    decision_notes: str


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def planner(state: InvestigationState) -> dict:
    # Deliberately minimal -- decides nothing on its own here (there's nothing to
    # decide yet, no data has been fetched). It exists as the graph's entry point,
    # matching the requested shape; a fuller version could route based on alert
    # metadata (severity, model) before fanning out.
    return {}


def drift_node(state: InvestigationState) -> dict:
    return {"drift_report": tool_get_drift_report(state["job_id"])}


def metadata_node(state: InvestigationState) -> dict:
    # Runs in parallel with drift_node, so it can't read drift_report's
    # model_version yet (parallel branches don't see each other's writes until
    # they converge). This project has exactly one deployed model version across
    # all fixtures, so it's passed as a constant; tool_get_training_run_metadata
    # already degrades gracefully (returns its one snapshot with a warning) if
    # this ever doesn't match.
    return {"run_metadata": tool_get_training_run_metadata("xgb_churn_v3")}


def lineage_node(state: InvestigationState) -> dict:
    return {"changelog": tool_get_pipeline_changelog()}


def evidence_node(state: InvestigationState) -> dict:
    """Fan-in point: this is where deterministic aggregation/filtering happens,
    since the parallel fetch nodes above can't see each other's results."""
    report = state["drift_report"]
    flagged_checks = flag_checks(report)
    flagged = any_flagged(flagged_checks)

    flagged_features = set()
    for fd in flagged_checks["feature_drift"]:
        flagged_features.add(fd["feature"])
    for cd in flagged_checks["concept_drift"]:
        flagged_features.add(cd["feature"])

    relevant_changelog = [
        entry for entry in state["changelog"]
        if flagged_features.intersection(entry.get("affected_features", []))
    ]

    return {
        "flagged_checks": flagged_checks,
        "flagged": flagged,
        "relevant_changelog": relevant_changelog,
    }


def _get_chat_model(provider):
    resolved = resolve_provider(provider)
    if resolved == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=GROQ_MODEL, api_key=os.environ["GROQ_API_KEY"])
    if resolved == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=ANTHROPIC_MODEL, api_key=os.environ["ANTHROPIC_API_KEY"])
    raise ValueError(f"Unknown provider: {resolved}")


REASONING_SYSTEM_PROMPT = """You are a Churn Model Drift Investigator. You have \
already been given aggregated evidence -- you do not have tools, just reason over \
what's provided.

Write like a thoughtful analyst explaining their thinking to a colleague, not a \
terse checklist. Construct a multi-tiered stakeholder summary: Alert Summary, Root \
Cause Identified, Statistical Variance, Lineage Context, Recommended Actions. The \
analysis sections should be a few full sentences of connected prose each. Bullet \
points are fine for Recommended Actions only.

CRITICAL: a changelog entry can only explain a drift if its date is BEFORE the \
drift report's run_date -- check this explicitly for every candidate entry before \
citing it, no matter how thematically relevant it sounds.

Label the root cause as a hypothesis unless the correlation is very strong. Do not \
invent data, dates, or events beyond what's provided below."""


def reasoning_node(state: InvestigationState, provider=None) -> dict:
    if not state["flagged"]:
        return {
            "narrative": (
                f"Alert Summary: No action needed.\n\n"
                f"Run `{state['job_id']}` ({state['drift_report']['run_date']}) passed "
                f"all configured drift and performance thresholds. No root-cause "
                f"investigation triggered."
            )
        }

    audience = state.get("audience", "mlops")
    model = _get_chat_model(provider)
    user_prompt = f"""AUDIENCE: {audience}
{AUDIENCE_INSTRUCTIONS[audience]}

DRIFT REPORT (job_id: {state['job_id']}, run_date: {state['drift_report']['run_date']}):
{yaml.dump(state['drift_report'], sort_keys=False)}

FLAGGED CHECKS:
{yaml.dump(state['flagged_checks'], sort_keys=False)}

TRAINING-RUN METADATA (baseline for comparison):
{yaml.dump(state['run_metadata'], sort_keys=False)}

FULL PIPELINE CHANGELOG (check dates against run_date yourself):
{yaml.dump(state['changelog'], sort_keys=False)}

DETERMINISTICALLY PRE-FILTERED CHANGELOG (feature-name + lookback-window match --
a starting point, not the final word; the full changelog above is also available
to you):
{yaml.dump(state['relevant_changelog'], sort_keys=False)}
"""
    response = model.invoke([
        {"role": "system", "content": REASONING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return {"narrative": response.content}


def human_approval_node(state) -> dict:
    # Shared by both scenarios -- the snapshot scenario keys on job_id, the
    # billing/time-series scenario keys on feature. Whichever is present wins.
    identifier = state.get("job_id") or state.get("feature")
    decision = interrupt({
        "identifier": identifier,
        "narrative": state.get("narrative", "(no narrative in state)"),
        "guardrail_flags": state.get("guardrail_flags", []),
    })
    if isinstance(decision, dict):
        approved = bool(decision.get("approved"))
        notes = decision.get("notes", "")
    else:
        approved = bool(decision)
        notes = ""
    return {"approved": approved, "decision_notes": notes}


def route_after_reasoning(state: InvestigationState) -> str:
    return "human_approval" if state["flagged"] else END


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _build_graph(provider=None):
    graph = StateGraph(InvestigationState)
    graph.add_node("planner", planner)
    graph.add_node("drift", drift_node)
    graph.add_node("metadata", metadata_node)
    graph.add_node("lineage", lineage_node)
    graph.add_node("evidence", evidence_node)
    graph.add_node("reasoning", lambda state: reasoning_node(state, provider))
    graph.add_node("human_approval", human_approval_node)

    graph.add_edge(START, "planner")
    for fan_out_node in ("drift", "metadata", "lineage"):
        graph.add_edge("planner", fan_out_node)
        graph.add_edge(fan_out_node, "evidence")
    graph.add_edge("evidence", "reasoning")
    graph.add_conditional_edges("reasoning", route_after_reasoning, {
        "human_approval": "human_approval",
        END: END,
    })
    graph.add_edge("human_approval", END)
    return graph


def build_graph(provider=None):
    """Used by our CLI and Streamlit app -- has its own checkpointer so we
    control pause/resume ourselves."""
    return _build_graph(provider).compile(checkpointer=MemorySaver())


def build_graph_for_studio():
    """Used by LangGraph Studio -- no checkpointer here; the dev server
    provides its own persistence and will error if we attach one too."""
    return _build_graph(provider=None).compile()


# ---------------------------------------------------------------------------
# Billing/time-series scenario: same shape (planner -> fan-out -> evidence ->
# reasoning -> human_approval), different data source (drift_metrics.json /
# lineage.json / model_metadata.json instead of the snapshot YAML fixtures).
# Unlike the snapshot scenario, model_version is given directly rather than
# derived from another node's output, so all three fan-out nodes here are
# fully independent -- no "can't see it yet, it's parallel" constraint.
# ---------------------------------------------------------------------------

class BillingInvestigationState(TypedDict, total=False):
    feature: str
    model_version: str
    audience: str
    drift_metrics: list
    lineage: list
    model_metadata: list
    flagged: bool
    narrative: str
    approved: Optional[bool]
    decision_notes: str


def planner_billing(state: BillingInvestigationState) -> dict:
    return {}


def drift_node_billing(state: BillingInvestigationState) -> dict:
    return {"drift_metrics": tool_get_drift_metrics(state["feature"])}


def lineage_node_billing(state: BillingInvestigationState) -> dict:
    return {"lineage": tool_get_lineage(state["feature"])}


def model_metadata_node_billing(state: BillingInvestigationState) -> dict:
    return {"model_metadata": tool_get_model_metadata(state["model_version"])}


def evidence_node_billing(state: BillingInvestigationState) -> dict:
    """Fan-in point. Unlike the snapshot scenario there's no threshold to
    re-derive -- drift_detected is already computed in the fixture, we just
    read the latest point in the series."""
    latest = state["drift_metrics"][-1]
    return {"flagged": bool(latest.get("drift_detected"))}


BILLING_REASONING_SYSTEM_PROMPT = """You are a Drift Investigator. You have already \
been given aggregated evidence -- you do not have tools, just reason over what's \
provided.

Write like a thoughtful analyst explaining their thinking to a colleague, not a \
terse checklist. Construct a multi-tiered stakeholder summary: Alert Summary, Root \
Cause Identified, Statistical Variance, Lineage Context, Recommended Actions. The \
analysis sections should be a few full sentences of connected prose each. Bullet \
points are fine for Recommended Actions only.

CRITICAL: a pipeline deployment or change can only explain a drift if its date is \
BEFORE the drift was first observed (drift_detected first became true in the time \
series) -- check this explicitly before citing it, no matter how thematically \
relevant it sounds.

Label the root cause as a hypothesis unless the correlation is very strong. Do not \
invent data, dates, or events beyond what's provided below."""


def reasoning_node_billing(state: BillingInvestigationState, provider=None) -> dict:
    if not state["flagged"]:
        latest = state["drift_metrics"][-1]
        return {
            "narrative": (
                f"Alert Summary: No action needed.\n\n"
                f"Feature `{state['feature']}` ({latest['timestamp']}) shows no "
                f"drift (PSI={latest['psi']}). No root-cause investigation triggered."
            )
        }

    audience = state.get("audience", "mlops")
    model = _get_chat_model(provider)
    user_prompt = f"""AUDIENCE: {audience}
{AUDIENCE_INSTRUCTIONS[audience]}

DRIFT METRICS TIME SERIES for feature "{state['feature']}" (look at the whole
trend, not just the latest point):
{yaml.dump(state['drift_metrics'], sort_keys=False)}

PIPELINE LINEAGE for feature "{state['feature']}":
{yaml.dump(state['lineage'], sort_keys=False)}

MODEL METADATA for model_version "{state['model_version']}":
{yaml.dump(state['model_metadata'], sort_keys=False)}
"""
    response = model.invoke([
        {"role": "system", "content": BILLING_REASONING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return {"narrative": response.content}


def _build_graph_billing(provider=None):
    graph = StateGraph(BillingInvestigationState)
    graph.add_node("planner", planner_billing)
    graph.add_node("drift", drift_node_billing)
    graph.add_node("lineage", lineage_node_billing)
    graph.add_node("model_metadata", model_metadata_node_billing)
    graph.add_node("evidence", evidence_node_billing)
    graph.add_node("reasoning", lambda state: reasoning_node_billing(state, provider))
    graph.add_node("human_approval", human_approval_node)

    graph.add_edge(START, "planner")
    for fan_out_node in ("drift", "lineage", "model_metadata"):
        graph.add_edge("planner", fan_out_node)
        graph.add_edge(fan_out_node, "evidence")
    graph.add_edge("evidence", "reasoning")
    graph.add_conditional_edges("reasoning", route_after_reasoning, {
        "human_approval": "human_approval",
        END: END,
    })
    graph.add_edge("human_approval", END)
    return graph


def build_graph_billing(provider=None):
    return _build_graph_billing(provider).compile(checkpointer=MemorySaver())


def build_graph_billing_for_studio():
    return _build_graph_billing(provider=None).compile()


# ---------------------------------------------------------------------------
# Unified agentic graph: real LangGraph tool-calling, billing scenario only.
#
#     START -> check_drift -> (nothing flagged? -> END)
#                           -> agent -> [drift, lineage, metadata] (whichever
#                                        the agent actually requested this turn,
#                                        possibly more than one in parallel)
#                                     -> back to agent, loop until no more
#                                        tool calls
#                           -> human_approval -> END
#
# Unlike the graphs above, the LLM itself chooses which tools to call and when.
# drift/lineage/metadata are three separate, always-visible nodes (matching
# the diagram you wanted), each wrapping exactly one tool -- this is NOT the
# standard LangGraph pattern (normally all tools share one ToolNode dispatcher)
# but real agent-driven routing: after "agent", a conditional edge inspects
# which tool(s) the model just asked for and fans out to the matching node(s).
# ---------------------------------------------------------------------------

from typing import Annotated, Literal
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages

# Valid values, read from the actual fixture files rather than hardcoded --
# if you add more features/model_versions to the JSON fixtures, these pick
# them up automatically instead of silently going stale.
def _valid_features():
    return sorted({d["feature"] for d in load_json(os.path.join(FIXTURE_DIR, "drift_metrics.json"))})


def _valid_model_versions():
    return sorted({d["model_version"] for d in load_json(os.path.join(FIXTURE_DIR, "model_metadata.json"))})


VALID_FEATURES = _valid_features()
VALID_MODEL_VERSIONS = _valid_model_versions()


class AgentInput(TypedDict):
    """The only fields a caller should actually provide. Passed to StateGraph
    as input_schema so Studio renders a clean 3-field form (as dropdowns,
    since these are Literal types) instead of trying (and failing) to build a
    widget for the full internal state, which includes a reducer-annotated
    messages list it can't represent."""
    feature: Literal[tuple(VALID_FEATURES)]
    model_version: Literal[tuple(VALID_MODEL_VERSIONS)]
    audience: Literal["exec", "mlops", "datascientist"]


MAX_AGENTIC_TURNS = 6


class AgentState(TypedDict, total=False):
    feature: str
    model_version: str
    audience: str
    flagged: bool
    messages: Annotated[list, add_messages]
    turn_count: int
    narrative: str
    guardrail_flags: list
    approved: Optional[bool]
    decision_notes: str


@tool
def get_drift_metrics(feature: str) -> list:
    """Fetch the weekly drift-metric time series for a feature: accuracy,
    training vs. production mean, PSI, and a drift_detected flag per week.
    Look at the whole trend, not just the latest point."""
    return tool_get_drift_metrics(feature)


@tool
def get_lineage(feature: str) -> list:
    """Fetch the pipeline version history for a feature -- which pipeline
    produced it, version, deployment date, and any known issues or open
    incidents. Use this to find what changed upstream and when."""
    return tool_get_lineage(feature)


@tool
def get_model_metadata(model_version: str) -> list:
    """Fetch the model's run history: accuracy, AUC, and feature importance
    over time for a given model version."""
    return tool_get_model_metadata(model_version)


AGENTIC_TOOLS = [get_drift_metrics, get_lineage, get_model_metadata]

AGENTIC_SYSTEM_PROMPT = """You are a Drift Investigator Agent. You are told a \
feature and a model_version that have been flagged for drift -- use your tools \
to investigate yourself, you are not handed any pre-gathered evidence.

Typical investigation:
1. Call get_drift_metrics for the feature and look at the whole trend, not just \
the latest point -- when did PSI/accuracy start moving, and how fast?
2. Call get_lineage for the feature to see what pipeline produced it and whether \
a new version was deployed around when the trend changed. Pay attention to any \
known_issue or open incident_id -- strong hypothesis material.
3. Call get_model_metadata for the model version, to see how much this feature \
actually matters to the model (feature importance) and how accuracy/AUC moved \
over the same period.

CRITICAL: a pipeline deployment can only explain a drift if its date is BEFORE \
the drift was first observed -- check this explicitly before citing it, no \
matter how thematically relevant it sounds.

When you have enough evidence, stop calling tools and write a multi-tiered \
stakeholder summary: Alert Summary, Root Cause Identified, Statistical Variance, \
Lineage Context, Recommended Actions. Write like a thoughtful analyst explaining \
their thinking, not a terse checklist -- a few full sentences of connected prose \
per section, bullets only for Recommended Actions.

Label the root cause as a hypothesis unless the correlation is very strong. Do \
not invent data, dates, or events beyond what your tools return."""


def check_drift_node(state: AgentState) -> dict:
    """Deterministic pre-check: skip the agent loop entirely if nothing's
    actually flagged, same cost-control pattern as the other graphs."""
    if "feature" not in state or "model_version" not in state:
        raise ValueError(
            "Missing required input. This graph needs feature, model_version, "
            "and audience, e.g.: "
            '{"feature": "total_charges", "model_version": "v14", "audience": "mlops"} '
            f"-- got keys: {sorted(state.keys())}"
        )
    if state["feature"] not in VALID_FEATURES:
        raise ValueError(
            f"Unknown feature {state['feature']!r}. Valid features: {VALID_FEATURES}"
        )
    if state["model_version"] not in VALID_MODEL_VERSIONS:
        raise ValueError(
            f"Unknown model_version {state['model_version']!r}. "
            f"Valid model versions: {VALID_MODEL_VERSIONS}"
        )
    metrics = tool_get_drift_metrics(state["feature"])
    latest = metrics[-1]
    if not latest.get("drift_detected"):
        return {
            "flagged": False,
            "narrative": (
                f"Alert Summary: No action needed.\n\n"
                f"Feature `{state['feature']}` ({latest['timestamp']}) shows no "
                f"drift (PSI={latest['psi']}). No root-cause investigation triggered."
            ),
        }
    audience = state.get("audience", "mlops")
    kickoff = (
        f'Investigate feature "{state["feature"]}" for model_version '
        f'"{state["model_version"]}".\n\nAUDIENCE: {audience}\n{AUDIENCE_INSTRUCTIONS[audience]}'
    )
    return {"flagged": True, "messages": [HumanMessage(content=kickoff)]}


def route_after_check(state: AgentState) -> str:
    # .get() rather than state["flagged"]: if state was manually edited/resumed
    # from partway through in Studio's UI (skipping check_drift_node, which is
    # what normally sets this key), missing it should mean "we don't have
    # evidence of a flag" -- safely route to END instead of crashing.
    return "agent" if state.get("flagged") else END


def agent_node(state: AgentState, provider=None) -> dict:
    model = _get_chat_model(provider).bind_tools(AGENTIC_TOOLS)
    messages = state.get("messages") or []
    if not any(getattr(m, "type", None) == "system" for m in messages):
        messages = [SystemMessage(content=AGENTIC_SYSTEM_PROMPT)] + messages
    response = model.invoke(messages)
    return {"messages": [response], "turn_count": state.get("turn_count", 0) + 1}


# Maps a tool's registered name to the graph node that owns it.
TOOL_NAME_TO_NODE = {
    "get_drift_metrics": "drift",
    "get_lineage": "lineage",
    "get_model_metadata": "metadata",
}


def _make_single_tool_node(tool_fn):
    """Wrap exactly one tool as its own node. Only executes tool_calls in the
    last message that match this tool's name -- if the agent requested
    multiple different tools in one turn, each node ignores calls that aren't
    its own, and all matching nodes run in parallel (see route_tool_calls)."""
    def node(state: AgentState) -> dict:
        msgs = state.get("messages") or []
        if not msgs:
            return {"messages": []}
        last = msgs[-1]
        results = []
        for tc in getattr(last, "tool_calls", None) or []:
            if tc["name"] != tool_fn.name:
                continue
            output = tool_fn.invoke(tc["args"])
            results.append(ToolMessage(content=str(output), tool_call_id=tc["id"], name=tc["name"]))
        return {"messages": results}
    return node


drift_tool_node = _make_single_tool_node(get_drift_metrics)
lineage_tool_node = _make_single_tool_node(get_lineage)
metadata_tool_node = _make_single_tool_node(get_model_metadata)


def route_tool_calls(state: AgentState):
    """After the agent speaks: if it asked for tools, fan out to exactly the
    node(s) matching what it asked for (possibly more than one in parallel).
    If it didn't ask for any tools, it's done -- move to finalize.

    Guardrail: hard-capped at MAX_AGENTIC_TURNS agent turns, regardless of
    whether the model still wants to call more tools -- protects against a
    runaway loop (e.g. the model repeatedly re-calling the same tool) burning
    tokens indefinitely."""
    if state.get("turn_count", 0) >= MAX_AGENTIC_TURNS:
        return "finalize"
    msgs = state.get("messages") or []
    if not msgs:
        return "finalize"
    last = msgs[-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return "finalize"
    requested_nodes = {TOOL_NAME_TO_NODE[tc["name"]] for tc in tool_calls if tc["name"] in TOOL_NAME_TO_NODE}
    return list(requested_nodes) if requested_nodes else "finalize"


def finalize_narrative_node(state: AgentState) -> dict:
    """The agent's last message (once it stops calling tools) is the report."""
    msgs = state.get("messages") or []
    if not msgs:
        return {"narrative": "Alert Summary: No agent output was produced (empty message history)."}
    return {"narrative": msgs[-1].content}


REQUIRED_NARRATIVE_SECTIONS = [
    "Alert Summary", "Root Cause", "Statistical Variance",
    "Lineage Context", "Recommended Actions",
]


def _extract_decimal_numbers(text):
    return set(re.findall(r"\d+\.\d+", text or ""))


def verify_narrative_node(state: AgentState) -> dict:
    """Guardrail: cross-check every decimal number in the narrative against
    numbers that actually appeared in tool output during this investigation,
    and confirm the expected report sections are present. This is what caught
    the model inventing 'a threshold of 0.9' in testing -- that number never
    appeared in any tool's output, only in the model's prose. Flags are
    surfaced to the human at approval time, not silently dropped or blocked;
    this is a defense-in-depth check, not a hard gate."""
    narrative = state.get("narrative", "")
    flags = []

    narrative_numbers = _extract_decimal_numbers(narrative)
    tool_output_text = " ".join(
        str(getattr(m, "content", ""))
        for m in (state.get("messages") or [])
        if getattr(m, "type", None) == "tool"
    )
    source_numbers = _extract_decimal_numbers(tool_output_text)
    invented = narrative_numbers - source_numbers
    if invented:
        flags.append(
            f"Possible fabricated number(s) -- not found in any tool output this run: {sorted(invented)}"
        )

    missing_sections = [s for s in REQUIRED_NARRATIVE_SECTIONS if s.lower() not in narrative.lower()]
    if missing_sections:
        flags.append(f"Missing expected report section(s): {missing_sections}")

    return {"guardrail_flags": flags}


def _build_agentic_graph(provider=None):
    graph = StateGraph(AgentState, input_schema=AgentInput)
    graph.add_node("check_drift", check_drift_node)
    graph.add_node("agent", lambda state: agent_node(state, provider))
    graph.add_node("drift", drift_tool_node)
    graph.add_node("lineage", lineage_tool_node)
    graph.add_node("metadata", metadata_tool_node)
    graph.add_node("finalize", finalize_narrative_node)
    graph.add_node("verify", verify_narrative_node)
    graph.add_node("human_approval", human_approval_node)

    graph.add_edge(START, "check_drift")
    graph.add_conditional_edges("check_drift", route_after_check, {"agent": "agent", END: END})
    graph.add_conditional_edges("agent", route_tool_calls, {
        "drift": "drift", "lineage": "lineage", "metadata": "metadata", "finalize": "finalize",
    })
    graph.add_edge("drift", "agent")
    graph.add_edge("lineage", "agent")
    graph.add_edge("metadata", "agent")
    graph.add_edge("finalize", "verify")
    graph.add_edge("verify", "human_approval")
    graph.add_edge("human_approval", END)
    return graph


def build_agentic_graph(provider=None):
    return _build_agentic_graph(provider).compile(checkpointer=MemorySaver())


def build_agentic_graph_for_studio():
    return _build_agentic_graph(provider=None).compile()


def extract_tool_trace(messages):
    """Rebuild a {tool, input, output} trace from the message history, for
    display -- ToolNode doesn't hand us this directly like our hand-rolled
    loop in drift_investigator.py does."""
    trace = []
    pending = {}
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            pending[tc["id"]] = {"tool": tc["name"], "input": tc["args"]}
        if getattr(m, "type", None) == "tool":
            call_id = getattr(m, "tool_call_id", None)
            if call_id in pending:
                trace.append({**pending[call_id], "output": m.content})
    return trace


# ---------------------------------------------------------------------------
# CLI (real interrupt/resume via a terminal y/n prompt)
# ---------------------------------------------------------------------------

def run_cli(job_id, audience, provider, output_dir):
    compiled = build_graph(provider)
    config = {"configurable": {"thread_id": job_id}}

    result = compiled.invoke({"job_id": job_id, "audience": audience}, config=config)
    was_interrupted = "__interrupt__" in result

    if was_interrupted:
        payload = result["__interrupt__"][0].value
        print(payload["narrative"])
        print()
        ans = input("Approve this report? [y/n]: ").strip().lower()
        result = compiled.invoke(Command(resume={"approved": ans == "y"}), config=config)
    else:
        print(result["narrative"])

    narrative = result["narrative"]
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{job_id}_{audience}_langgraph_report.md")
    with open(out_path, "w") as f:
        f.write(narrative)
        if result.get("approved") is not None:
            f.write(f"\n\n---\n\n**Human approval:** {'Approved' if result['approved'] else 'Rejected'}\n")

    if result.get("approved") is not None:
        print(f"\n[Human approval: {'Approved' if result['approved'] else 'Rejected'}]")
    print(f"\n[INFO] Report written to {out_path}")
    return result


def run_cli_billing(feature, model_version, audience, provider, output_dir):
    compiled = build_graph_billing(provider)
    config = {"configurable": {"thread_id": feature}}

    result = compiled.invoke(
        {"feature": feature, "model_version": model_version, "audience": audience},
        config=config,
    )
    was_interrupted = "__interrupt__" in result

    if was_interrupted:
        payload = result["__interrupt__"][0].value
        print(payload["narrative"])
        print()
        ans = input("Approve this report? [y/n]: ").strip().lower()
        result = compiled.invoke(Command(resume={"approved": ans == "y"}), config=config)
    else:
        print(result["narrative"])

    narrative = result["narrative"]
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{feature}_{audience}_billing_langgraph_report.md")
    with open(out_path, "w") as f:
        f.write(narrative)
        if result.get("approved") is not None:
            f.write(f"\n\n---\n\n**Human approval:** {'Approved' if result['approved'] else 'Rejected'}\n")

    if result.get("approved") is not None:
        print(f"\n[Human approval: {'Approved' if result['approved'] else 'Rejected'}]")
    print(f"\n[INFO] Report written to {out_path}")
    return result


def run_cli_agentic(feature, model_version, audience, provider, output_dir):
    compiled = build_agentic_graph(provider)
    config = {"configurable": {"thread_id": feature}}

    result = compiled.invoke(
        {"feature": feature, "model_version": model_version, "audience": audience},
        config=config,
    )
    was_interrupted = "__interrupt__" in result

    if was_interrupted:
        payload = result["__interrupt__"][0].value
        print(payload["narrative"])
        print()
        trace = extract_tool_trace(result["messages"])
        if trace:
            print("Tool calls made:")
            for i, step in enumerate(trace, 1):
                print(f"  {i}. {step['tool']}({step['input']})")
            print()
        flags = payload.get("guardrail_flags") or []
        if flags:
            print("⚠ Guardrail flags (review before approving):")
            for f in flags:
                print(f"  - {f}")
            print()
        ans = input("Approve this report? [y/n]: ").strip().lower()
        result = compiled.invoke(Command(resume={"approved": ans == "y"}), config=config)
    else:
        print(result["narrative"])

    narrative = result["narrative"]
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{feature}_{audience}_agentic_report.md")
    with open(out_path, "w") as f:
        f.write(narrative)
        if result.get("approved") is not None:
            f.write(f"\n\n---\n\n**Human approval:** {'Approved' if result['approved'] else 'Rejected'}\n")

    if result.get("approved") is not None:
        print(f"\n[Human approval: {'Approved' if result['approved'] else 'Rejected'}]")
    print(f"\n[INFO] Report written to {out_path}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Simplistic LangGraph drift investigator")
    parser.add_argument("--report", help="Path to a drift_report_*.yaml (snapshot scenario)")
    parser.add_argument("--feature", help="Feature name, e.g. total_charges (billing/time-series scenario)")
    parser.add_argument("--model-version", default="v14", help="Model version for the billing scenario")
    parser.add_argument("--agentic", action="store_true",
                         help="Use the unified tool-calling graph instead of the fixed fan-out graph (--feature only)")
    parser.add_argument("--audience", choices=list(AUDIENCE_INSTRUCTIONS.keys()), default="mlops")
    parser.add_argument("--output-dir", default=os.path.join(BASE_DIR, "agent_reports"))
    parser.add_argument("--provider", choices=["groq", "anthropic"], default=None)
    args = parser.parse_args()

    if args.feature and args.agentic:
        run_cli_agentic(args.feature, args.model_version, args.audience, args.provider, args.output_dir)
    elif args.feature:
        run_cli_billing(args.feature, args.model_version, args.audience, args.provider, args.output_dir)
    elif args.report:
        job_id = load_yaml(args.report)["job_id"]
        run_cli(job_id, args.audience, args.provider, args.output_dir)
    else:
        parser.error("Provide either --report (snapshot scenario) or --feature (billing scenario)")


if __name__ == "__main__":
    main()
