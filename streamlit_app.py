#!/usr/bin/env python3
"""
Streamlit UI for the Drift Investigator agent.

Thin presentation layer only -- all logic (flagging, correlation, the LLM
call) lives in drift_investigator.py and is imported here, not duplicated.
"""
import os

import streamlit as st
import yaml

from drift_investigator import (
    FIXTURE_DIR,
    AUDIENCE_INSTRUCTIONS,
    load_yaml,
    flag_checks,
    any_flagged,
    correlate_changelog,
    run_agent,
    build_kickoff_message,
)
from langgraph_investigator import build_graph
from langgraph.types import Command

def escape_dollars(text):
    """Streamlit's markdown renderer treats a pair of $ as LaTeX math delimiters,
    which silently eats literal dollar amounts like '$1000-$2500'. Escape them so
    currency in changelog entries and LLM narratives renders as plain text."""
    return text.replace("$", "\\$")


st.set_page_config(page_title="Drift Investigator", page_icon="🔍", layout="wide")

st.title("🔍 Churn Model Drift Investigator")
st.caption(
    "Reads the churn pipeline's drift-check output and explains it in plain "
    "English instead of a multi-megabyte Deepchecks HTML report."
)

with st.sidebar:
    st.header("Configuration")

    report_files = sorted(
        f for f in os.listdir(FIXTURE_DIR) if f.startswith("drift_report")
    )
    report_choice = st.selectbox("Drift report", report_files)

    audience = st.selectbox(
        "Audience", list(AUDIENCE_INSTRUCTIONS.keys()), index=1
    )

    architecture = st.radio(
        "Architecture",
        ["Tool-calling agent", "LangGraph (with approval)"],
        index=0,
        help="Tool-calling agent: the model decides which tools to call. "
             "LangGraph: fixed fan-out/fan-in graph with a real human-approval pause.",
    )

    st.divider()
    st.caption("API keys (kept in this session only, never written to disk)")
    groq_key_input = st.text_input(
        "GROQ_API_KEY", type="password", value=os.environ.get("GROQ_API_KEY", "")
    )
    anthropic_key_input = st.text_input(
        "ANTHROPIC_API_KEY", type="password", value=os.environ.get("ANTHROPIC_API_KEY", "")
    )

    run_button = st.button("🔎 Investigate", type="primary", use_container_width=True)

report_path = os.path.join(FIXTURE_DIR, report_choice)
report = load_yaml(report_path)
changelog = load_yaml(os.path.join(FIXTURE_DIR, "pipeline_changelog.yaml"))

flagged = flag_checks(report)
flagged_any = any_flagged(flagged)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Job")
    st.metric("Job ID", report["job_id"])
    st.metric("Run date", report["run_date"])
    st.metric(
        "Status",
        "🔴 Retrain recommended" if report.get("retrain_recommended") else "🟢 Healthy",
    )

with col2:
    st.subheader("Flagged checks")
    st.caption("Preview only — the agent below re-discovers this itself via tool calls, it isn't handed this.")
    if not flagged_any:
        st.success("No checks flagged — all thresholds passed.")
    else:
        wdd = flagged["whole_dataset_drift"]
        if wdd:
            st.warning(f"Whole dataset drift: {wdd['score']} > threshold {wdd['threshold']}")
        for fd in flagged["feature_drift"]:
            st.warning(
                f"Feature drift — **{fd['feature']}**: {fd['score']} > "
                f"threshold {fd['threshold']} ({fd['test']})"
            )
        for cd in flagged["concept_drift"]:
            st.warning(
                f"Concept drift — **{cd['feature']}**: PPS diff {cd['diff']} > "
                f"threshold {cd['threshold']} (train {cd['pps_train']} → "
                f"inference {cd['pps_inference']})"
            )
        ld = flagged["label_drift"]
        if ld:
            st.warning(f"Label drift: {ld['score']} > threshold {ld['threshold']}")
        mp = flagged["model_performance"]
        if mp:
            st.error(
                f"Model performance — recall {mp['recall']} "
                f"(threshold {mp['recall_threshold']}), f1 {mp['f1']} "
                f"(threshold {mp['f1_threshold']})"
            )

correlated = correlate_changelog(report, changelog) if flagged_any else []

if flagged_any:
    st.divider()
    st.subheader("Time-correlated changelog entries")
    st.caption("Preview only — computed here for the human viewer; the agent calls get_pipeline_changelog itself and reasons about relevance independently.")
    if correlated:
        for entry in correlated:
            st.info(
                f"**{entry['date']}** — {escape_dollars(entry['change'])}  \n"
                f"Affected features: {', '.join(entry['affected_features'])}"
            )
    else:
        st.write("No changelog entries within the lookback window.")

st.divider()
st.subheader("Root-cause report")

if run_button:
    if groq_key_input:
        os.environ["GROQ_API_KEY"] = groq_key_input
    if anthropic_key_input:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key_input

if architecture == "Tool-calling agent":
    if run_button:
        trace = []
        if not flagged_any:
            narrative = (
                f"Alert Summary: No action needed.\n\n"
                f"Run `{report['job_id']}` ({report['run_date']}) passed all configured "
                f"drift and performance thresholds. No root-cause investigation triggered."
            )
        else:
            narrative = None
            try:
                with st.spinner("Agent is investigating (calling tools)..."):
                    # The agent gets only the job_id -- it decides itself which
                    # tools to call and when. See drift_investigator.run_agent.
                    # Provider is auto-detected from whichever API key is set.
                    narrative, trace = run_agent(None, build_kickoff_message(report["job_id"], audience))
            except Exception as e:
                st.error(str(e))

        if narrative:
            st.markdown(escape_dollars(narrative))
            st.download_button(
                "Download report",
                narrative,  # unescaped -- the downloaded .md file isn't run through
                # Streamlit's renderer, so it should keep the original $ signs.
                file_name=f"{report['job_id']}_{audience}_report.md",
            )
            if trace:
                st.divider()
                st.subheader("Agent tool-call trace")
                st.caption("What the agent actually called, in order — not pre-scripted.")
                for i, step in enumerate(trace, 1):
                    with st.expander(f"{i}. `{step['tool']}({step['input']})`"):
                        st.code(yaml.dump(step["output"], sort_keys=False), language="yaml")
    else:
        st.info("Configure options in the sidebar and click Investigate.")

else:  # LangGraph (with approval)
    st.caption(
        "Planner → [Drift, Metadata, Lineage, Docs] (parallel) → Evidence → "
        "Reasoning → Human Approval. See planning/06-future-vision.md for how "
        "this differs from the tool-calling agent above."
    )
    st.session_state.setdefault("lg_sessions", {})
    st.session_state.setdefault("lg_graph", None)

    job_id = report["job_id"]

    if run_button:
        if st.session_state.lg_graph is None:
            st.session_state.lg_graph = build_graph()
        try:
            with st.spinner("Running the graph (planner → fan-out → evidence → reasoning)..."):
                config = {"configurable": {"thread_id": job_id}}
                result = st.session_state.lg_graph.invoke(
                    {"job_id": job_id, "audience": audience}, config=config
                )
            if "__interrupt__" in result:
                payload = result["__interrupt__"][0].value
                st.session_state.lg_sessions[job_id] = {
                    "status": "awaiting_approval",
                    "narrative": payload["narrative"],
                    "audience": audience,
                }
            else:
                st.session_state.lg_sessions[job_id] = {
                    "status": "resolved",
                    "narrative": result["narrative"],
                    "approved": None,
                    "audience": audience,
                }
        except Exception as e:
            st.error(str(e))

    session = st.session_state.lg_sessions.get(job_id)
    if session is None:
        st.info("Configure options in the sidebar and click Investigate.")
    elif session["status"] == "awaiting_approval":
        st.markdown(escape_dollars(session["narrative"]))
        st.warning("Awaiting human approval — the graph is genuinely paused (langgraph interrupt), not just a UI state.")
        c1, c2 = st.columns(2)
        config = {"configurable": {"thread_id": job_id}}
        if c1.button("✅ Approve", type="primary", use_container_width=True):
            result = st.session_state.lg_graph.invoke(Command(resume={"approved": True}), config=config)
            st.session_state.lg_sessions[job_id] = {
                "status": "resolved", "narrative": result["narrative"],
                "approved": True, "audience": session["audience"],
            }
            st.rerun()
        if c2.button("❌ Reject", use_container_width=True):
            result = st.session_state.lg_graph.invoke(Command(resume={"approved": False}), config=config)
            st.session_state.lg_sessions[job_id] = {
                "status": "resolved", "narrative": result["narrative"],
                "approved": False, "audience": session["audience"],
            }
            st.rerun()
    else:
        narrative = session["narrative"]
        st.markdown(escape_dollars(narrative))
        if session.get("approved") is not None:
            st.caption(f"Human decision: {'✅ Approved' if session['approved'] else '❌ Rejected'}")
        st.download_button(
            "Download report",
            narrative,
            file_name=f"{job_id}_{session['audience']}_langgraph_report.md",
        )
