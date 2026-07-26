#!/usr/bin/env python3
"""
Drift Investigator: a tool-calling agent that investigates a churn-model drift
alert. Given only a job_id, the model decides which tools to call (drift
report, training-run metadata, pipeline changelog), in what order, and when
it has enough to write the final stakeholder report -- this is genuine
agentic tool use, not a single prompt stuffed with pre-gathered context.

See planning/ for scope, architecture, and trade-offs.
"""
import argparse
import json
import os
from datetime import datetime

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads .env in this directory into os.environ, if present
except ImportError:
    pass

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from groq import Groq
except ImportError:
    Groq = None

GROQ_MODEL = "llama-3.3-70b-versatile"
ANTHROPIC_MODEL = "claude-sonnet-5"
MAX_AGENT_TURNS = 6

LOOKBACK_DAYS = 30
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(BASE_DIR, "sample_data")


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Deterministic helpers. These are NOT part of the agent's reasoning -- they
# power the Streamlit "preview" panel (showing a human what's in the data
# before the agent investigates) and a cheap pre-check that skips the LLM
# entirely when nothing is flagged. The agent path below re-discovers all of
# this itself via tool calls; it doesn't receive these precomputed results.
# ---------------------------------------------------------------------------

def flag_checks(report):
    checks = report.get("checks", {})
    flagged = {
        "whole_dataset_drift": None,
        "feature_drift": [],
        "concept_drift": [],
        "label_drift": None,
        "model_performance": None,
    }

    wdd = checks.get("whole_dataset_drift")
    if wdd and not wdd.get("passed", True):
        flagged["whole_dataset_drift"] = wdd

    for fd in checks.get("feature_drift", []):
        if not fd.get("passed", True):
            flagged["feature_drift"].append(fd)

    for cd in checks.get("concept_drift", []):
        if not cd.get("passed", True):
            flagged["concept_drift"].append(cd)

    ld = checks.get("label_drift")
    if ld and not ld.get("passed", True):
        flagged["label_drift"] = ld

    mp = checks.get("model_performance")
    if mp and mp.get("model_retrain"):
        flagged["model_performance"] = mp

    return flagged


def any_flagged(flagged):
    return any([
        flagged["whole_dataset_drift"],
        flagged["feature_drift"],
        flagged["concept_drift"],
        flagged["label_drift"],
        flagged["model_performance"],
    ])


def correlate_changelog(report, changelog, lookback_days=LOOKBACK_DAYS):
    """Deterministic preview only -- see module docstring. The agent does its
    own timing/relevance reasoning via the get_pipeline_changelog tool."""
    run_date = datetime.strptime(report["run_date"], "%Y-%m-%d")
    checks = report.get("checks", {})
    flagged_features = set()
    for fd in checks.get("feature_drift", []):
        if not fd.get("passed", True):
            flagged_features.add(fd["feature"])
    for cd in checks.get("concept_drift", []):
        if not cd.get("passed", True):
            flagged_features.add(cd["feature"])

    relevant = []
    for entry in changelog:
        entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
        days_before = (run_date - entry_date).days
        if not (0 <= days_before <= lookback_days):
            continue
        if flagged_features.intersection(entry.get("affected_features", [])):
            relevant.append(entry)
    return relevant


AUDIENCE_INSTRUCTIONS = {
    "exec": (
        "Write for a non-technical executive. One short paragraph: plain-English "
        "health status, business impact, and a single recommended next step. No "
        "drift-score jargon, no thresholds, no feature-level detail."
    ),
    "mlops": (
        "Write for an MLOps engineer. Include the Alert Summary, Root Cause "
        "Identified, Statistical Variance (with actual scores and thresholds), "
        "Lineage Context, and numbered Recommended Actions. This is the primary, "
        "full-detail report format."
    ),
    "datascientist": (
        "Write for a data scientist. Same structure as the MLOps report, but add "
        "a closing note on which specific check caught this (and which check type "
        "would have missed it, if relevant) so they understand the detection "
        "mechanism, not just the result."
    ),
}


# ---------------------------------------------------------------------------
# Agent: tools + system prompt + a real tool-calling loop. The model decides
# which of these to call and when -- nothing here pre-fetches data for it.
# ---------------------------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "get_drift_report",
        "description": (
            "Fetch the structured drift-check summary for a job_id. Returns all "
            "checks run (whole-dataset drift, per-feature drift, concept drift, "
            "label drift, model performance), each already labeled passed=true/false "
            "against the pipeline's configured thresholds, plus the deployed "
            "model_version and run_date."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The job_id to investigate, e.g. 'infer_2026q3_001'",
                }
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "get_training_run_metadata",
        "description": (
            "Fetch the currently deployed model's training-run metadata: dataset "
            "version, training date, and baseline statistics for key features. "
            "This is a static YAML snapshot, not a live model registry or MLflow "
            "integration -- see planning/04-trade-offs.md."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "model_version": {
                    "type": "string",
                    "description": "The deployed model version, e.g. 'xgb_churn_v3' -- from get_drift_report's output.",
                }
            },
            "required": ["model_version"],
        },
    },
    {
        "name": "get_pipeline_changelog",
        "description": (
            "Fetch the full list of recent pipeline/business changes (dates, "
            "descriptions, affected features). Use this to check whether any "
            "recent change might explain a flagged drift signal -- you need to "
            "reason about timing (relative to the drift report's run_date) and "
            "feature overlap yourself; this tool does no filtering for you."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_drift_metrics",
        "description": (
            "Fetch the weekly drift-metric time series for a feature: accuracy, "
            "training vs. production mean, PSI (Population Stability Index), and "
            "a drift_detected flag per week. Unlike get_drift_report, this is a "
            "history over time, not a single snapshot -- look at the trend, not "
            "just the latest point."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feature": {
                    "type": "string",
                    "description": "The feature to fetch drift history for, e.g. 'total_charges'",
                }
            },
            "required": ["feature"],
        },
    },
    {
        "name": "get_lineage",
        "description": (
            "Fetch the pipeline version history for a feature -- which pipeline "
            "produced it, version, deployment date, and any known issues or open "
            "incidents. Use this to find what changed upstream and when."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feature": {
                    "type": "string",
                    "description": "The feature to fetch pipeline lineage for, e.g. 'total_charges'",
                }
            },
            "required": ["feature"],
        },
    },
    {
        "name": "get_model_metadata",
        "description": (
            "Fetch the model's run history: accuracy, AUC, and feature importance "
            "over time for a given model version. Use feature importance to judge "
            "how much a drifting feature actually matters to the model's predictions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "model_version": {
                    "type": "string",
                    "description": "The model version, e.g. 'v14'",
                }
            },
            "required": ["model_version"],
        },
    },
]


def tool_get_drift_report(job_id):
    path = os.path.join(FIXTURE_DIR, f"drift_report_{job_id}.yaml")
    if not os.path.exists(path):
        return {"error": f"No drift report found for job_id={job_id}"}
    return load_yaml(path)


def tool_get_training_run_metadata(model_version):
    data = load_yaml(os.path.join(FIXTURE_DIR, "training_run_metadata.yaml"))
    if data.get("model_version") != model_version:
        return {
            "warning": (
                f"No metadata on file for model_version={model_version!r}; "
                f"returning the only snapshot available."
            ),
            **data,
        }
    return data


def tool_get_pipeline_changelog(**_ignored):
    return load_yaml(os.path.join(FIXTURE_DIR, "pipeline_changelog.yaml"))


def tool_get_drift_metrics(feature):
    data = load_json(os.path.join(FIXTURE_DIR, "drift_metrics.json"))
    series = sorted(
        (d for d in data if d["feature"] == feature),
        key=lambda d: d["timestamp"],
    )
    if not series:
        return {"error": f"No drift metrics found for feature={feature}"}
    return series


def tool_get_lineage(feature):
    data = load_json(os.path.join(FIXTURE_DIR, "lineage.json"))
    series = sorted(
        (d for d in data if d["feature"] == feature),
        key=lambda d: d["timestamp"],
    )
    if not series:
        return {"error": f"No lineage found for feature={feature}"}
    return series


def tool_get_model_metadata(model_version):
    data = load_json(os.path.join(FIXTURE_DIR, "model_metadata.json"))
    series = sorted(
        (d for d in data if d["model_version"] == model_version),
        key=lambda d: d["timestamp"],
    )
    if not series:
        return {"error": f"No model metadata found for model_version={model_version}"}
    return series


TOOL_IMPL = {
    "get_drift_report": lambda args: tool_get_drift_report(args["job_id"]),
    "get_training_run_metadata": lambda args: tool_get_training_run_metadata(args["model_version"]),
    "get_pipeline_changelog": lambda args: tool_get_pipeline_changelog(**args),
    "get_drift_metrics": lambda args: tool_get_drift_metrics(args["feature"]),
    "get_lineage": lambda args: tool_get_lineage(args["feature"]),
    "get_model_metadata": lambda args: tool_get_model_metadata(args["model_version"]),
}


AGENT_SYSTEM_PROMPT = """You are a Drift Investigator Agent for the ML platform \
team. You'll be asked to investigate either (a) a job_id from a snapshot-style \
drift check, or (b) a feature name from a time-series-style drift monitor. Use \
your tools to investigate yourself -- you are not handed any pre-gathered evidence.

If given a job_id (snapshot scenario):
1. Call get_drift_report to see which checks failed and for which features.
2. If anything failed, call get_training_run_metadata (using the model_version \
from the drift report) to get baseline stats for the implicated features.
3. Call get_pipeline_changelog and reason yourself about which entries are \
timing- and feature-relevant to what failed (don't assume every entry matters).

If given a feature name (time-series scenario):
1. Call get_drift_metrics for that feature and look at the whole trend over time, \
not just the latest point -- when did PSI/accuracy start moving, and how fast?
2. Call get_lineage for that feature to see what pipeline produced it and whether \
a new version was deployed around when the trend changed -- pay attention to any \
known_issue or open incident_id, those are strong hypothesis material.
3. Call get_model_metadata for the model version involved, to see how much this \
feature actually matters to the model (feature importance) and how accuracy/AUC \
moved over the same period.

In both scenarios:
CRITICAL: an event (changelog entry or pipeline deployment) can only explain a \
drift if its date is BEFORE the drift was first observed -- explicitly check this \
for every candidate before citing it. An event dated after cannot be the cause and \
must be discarded, no matter how thematically relevant it sounds. When picking \
between multiple candidate events, prefer the one closest in time over one that \
merely sounds topically related.

Construct a multi-tiered stakeholder summary: Alert Summary, Root Cause Identified, \
Statistical Variance, Lineage Context, Recommended Actions.

Write like a thoughtful analyst explaining their thinking to a colleague, not a \
terse checklist. The analysis sections (Root Cause, Statistical Variance, Lineage \
Context) should be a few full sentences of connected prose each -- state the \
finding, then explain what it means and why it's plausible (or isn't). Bullet \
points are fine for Recommended Actions, but don't reduce the analysis itself to \
clipped one-line fragments. Be specific about uncertainty: if the evidence gives \
you a strong match, say so and say why; if nothing correlates well, say that \
plainly instead of forcing a weak connection.

If nothing is actually flagged/drifting, say so plainly and stop -- don't call \
tools unnecessarily.

Label the root cause as a hypothesis unless the correlation is very strong: you \
have tools for correlated timing, not verified causation. Do not invent data, \
dates, or events beyond what your tools return."""


def build_kickoff_message(job_id, audience):
    return (
        f'Investigate job_id "{job_id}".\n\n'
        f"AUDIENCE: {audience}\n{AUDIENCE_INSTRUCTIONS[audience]}"
    )


def build_kickoff_message_billing(feature, model_version, audience):
    return (
        f'Investigate feature "{feature}" for model_version "{model_version}".\n\n'
        f"AUDIENCE: {audience}\n{AUDIENCE_INSTRUCTIONS[audience]}"
    )


def _run_tool(name, args, trace):
    result = TOOL_IMPL[name](args)
    trace.append({"tool": name, "input": args, "output": result})
    return result


def run_agent_anthropic(kickoff_message, max_turns=MAX_AGENT_TURNS):
    if anthropic is None:
        raise RuntimeError(
            "The 'anthropic' package isn't installed. Run: pip install -r requirements-drift-investigator.txt"
        )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY before running.")

    client = anthropic.Anthropic(api_key=api_key)
    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in TOOL_SPECS
    ]
    messages = [{"role": "user", "content": kickoff_message}]
    trace = []

    for _ in range(max_turns):
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            system=AGENT_SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return text, trace

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _run_tool(block.name, block.input, trace)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": yaml.dump(result, sort_keys=False),
                })
        messages.append({"role": "user", "content": tool_results})

    return "[Agent did not converge within max turns]", trace


def run_agent_groq(kickoff_message, max_turns=MAX_AGENT_TURNS):
    if Groq is None:
        raise RuntimeError(
            "The 'groq' package isn't installed. Run: pip install -r requirements-drift-investigator.txt"
        )
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Set GROQ_API_KEY before running.")

    client = Groq(api_key=api_key)
    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in TOOL_SPECS
    ]
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": kickoff_message},
    ]
    trace = []

    for _ in range(max_turns):
        # Llama-3.3 on Groq occasionally emits a malformed tool-call payload
        # that Groq's parser rejects (tool_use_failed) -- transient generation
        # noise, not a bug in our request. Retry a couple of times before
        # giving up.
        last_error = None
        response = None
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    max_tokens=1500,
                    tools=tools,
                    messages=messages,
                )
                break
            except Exception as e:
                last_error = e
        if response is None:
            raise last_error

        msg = response.choices[0].message
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": msg.tool_calls,
        })

        if not msg.tool_calls:
            return msg.content, trace

        for tc in msg.tool_calls:
            # Groq can return the literal string "null" (not "") for zero-arg
            # tool calls, and json.loads("null") is Python None, not {} --
            # guard against both.
            args = json.loads(tc.function.arguments or "{}") or {}
            result = _run_tool(tc.function.name, args, trace)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": yaml.dump(result, sort_keys=False),
            })

    return "[Agent did not converge within max turns]", trace


def resolve_provider(provider):
    """Pick which LLM backend to call. Explicit --provider wins; otherwise auto-detect
    from whichever API key is set, preferring Groq since that's what's on hand."""
    if provider:
        return provider
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise RuntimeError(
        "No LLM API key found. Set GROQ_API_KEY or ANTHROPIC_API_KEY before running."
    )


def run_agent(provider, kickoff_message, max_turns=MAX_AGENT_TURNS):
    resolved = resolve_provider(provider)
    if resolved == "groq":
        return run_agent_groq(kickoff_message, max_turns)
    if resolved == "anthropic":
        return run_agent_anthropic(kickoff_message, max_turns)
    raise ValueError(f"Unknown provider: {resolved}")


def format_trace(trace):
    if not trace:
        return "_No tool calls were made._"
    lines = []
    for i, step in enumerate(trace, 1):
        lines.append(f"{i}. `{step['tool']}({step['input']})`")
    return "\n".join(lines)


def investigate(report_path, changelog_path, run_metadata_path, audience, output_dir, provider=None):
    # Cheap deterministic pre-check only -- see the note above flag_checks().
    # If genuinely nothing is flagged, skip the LLM/agent entirely rather than
    # spending tool calls confirming a clean run.
    report = load_yaml(report_path)
    job_id = report["job_id"]
    flagged = flag_checks(report)

    if not any_flagged(flagged):
        narrative = (
            f"Alert Summary: No action needed.\n\n"
            f"Run `{job_id}` ({report['run_date']}) passed all configured "
            f"drift and performance thresholds. No root-cause investigation triggered."
        )
        trace = []
    else:
        narrative, trace = run_agent(provider, build_kickoff_message(job_id, audience))

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{job_id}_{audience}_report.md")
    with open(out_path, "w") as f:
        f.write(narrative)
        if trace:
            f.write("\n\n---\n\n**Agent tool-call trace:**\n\n" + format_trace(trace) + "\n")

    print(narrative)
    if trace:
        print("\nTool calls made:\n" + format_trace(trace))
    print(f"\n[INFO] Report written to {out_path}")
    return narrative, trace


def investigate_billing(feature, model_version, audience, output_dir, provider=None):
    """Billing/time-series scenario: uses drift_metrics.json / lineage.json /
    model_metadata.json instead of the snapshot YAML fixtures. The deterministic
    pre-check here just reads the latest drift_detected flag already computed in
    the fixture -- there's no re-derivation of thresholds, unlike flag_checks()."""
    metrics = tool_get_drift_metrics(feature)
    if isinstance(metrics, dict) and "error" in metrics:
        raise RuntimeError(metrics["error"])

    latest = metrics[-1]
    if not latest.get("drift_detected"):
        narrative = (
            f"Alert Summary: No action needed.\n\n"
            f"Feature `{feature}` ({latest['timestamp']}) shows no drift "
            f"(PSI={latest['psi']}). No root-cause investigation triggered."
        )
        trace = []
    else:
        kickoff = build_kickoff_message_billing(feature, model_version, audience)
        narrative, trace = run_agent(provider, kickoff)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{feature}_{audience}_billing_report.md")
    with open(out_path, "w") as f:
        f.write(narrative)
        if trace:
            f.write("\n\n---\n\n**Agent tool-call trace:**\n\n" + format_trace(trace) + "\n")

    print(narrative)
    if trace:
        print("\nTool calls made:\n" + format_trace(trace))
    print(f"\n[INFO] Report written to {out_path}")
    return narrative, trace


def main():
    parser = argparse.ArgumentParser(description="Drift Investigator agent")
    parser.add_argument("--report", help="Path to a drift_report_*.yaml (snapshot scenario)")
    parser.add_argument("--feature", help="Feature name, e.g. total_charges (billing/time-series scenario)")
    parser.add_argument("--model-version", default="v14", help="Model version for the billing scenario")
    parser.add_argument("--changelog", default=os.path.join(FIXTURE_DIR, "pipeline_changelog.yaml"))
    parser.add_argument("--run-metadata", default=os.path.join(FIXTURE_DIR, "training_run_metadata.yaml"))
    parser.add_argument("--audience", choices=list(AUDIENCE_INSTRUCTIONS.keys()), default="mlops")
    parser.add_argument("--output-dir", default=os.path.join(BASE_DIR, "agent_reports"))
    parser.add_argument("--provider", choices=["groq", "anthropic"], default=None,
                         help="LLM backend. Defaults to auto-detect from GROQ_API_KEY / ANTHROPIC_API_KEY.")
    args = parser.parse_args()

    if args.feature:
        investigate_billing(args.feature, args.model_version, args.audience, args.output_dir, args.provider)
    elif args.report:
        investigate(args.report, args.changelog, args.run_metadata, args.audience, args.output_dir, args.provider)
    else:
        parser.error("Provide either --report (snapshot scenario) or --feature (billing scenario)")


if __name__ == "__main__":
    main()
