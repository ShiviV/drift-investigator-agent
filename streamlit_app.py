#!/usr/bin/env python3
"""
Streamlit UI for the Drift Investigator agent.

Thin presentation layer only -- all logic (tools, guardrails, the graph
itself) lives in langgraph_investigator.py and is imported here, not
duplicated. Uses the unified agentic graph (real tool-calling: the model
decides which of drift/lineage/metadata to call), not the earlier fixed
fan-out graphs -- see planning/02-scope.md for why this one is primary.
"""
import os

import streamlit as st

from drift_investigator import AUDIENCE_INSTRUCTIONS
from langgraph_investigator import (
    build_agentic_graph,
    extract_tool_trace,
    VALID_FEATURES,
    VALID_MODEL_VERSIONS,
)
from langgraph.types import Command


def escape_dollars(text):
    """Streamlit's markdown renderer treats a pair of $ as LaTeX math delimiters,
    which silently eats literal dollar amounts like '$1000-$2500'. Escape them so
    currency renders as plain text."""
    return text.replace("$", "\\$")


st.set_page_config(page_title="Drift Investigator", page_icon="🔍", layout="wide")

st.title("🔍 Drift Investigator Agent")
st.caption(
    "A real tool-calling LangGraph agent: given a feature, it decides for "
    "itself which of drift / lineage / metadata to call, writes a root-cause "
    "report, and pauses for human approval. Two independent guardrail layers "
    "review the report before you see it."
)

with st.sidebar:
    st.header("Configuration")

    feature = st.selectbox("Feature", VALID_FEATURES)
    model_version = st.selectbox("Model version", VALID_MODEL_VERSIONS)
    audience = st.selectbox("Audience", list(AUDIENCE_INSTRUCTIONS.keys()), index=1)

    provider_choice = st.radio(
        "LLM provider",
        ["auto", "groq", "anthropic", "huggingface"],
        index=0,
        help="auto picks whichever API key is set below, preferring Groq, "
             "then Anthropic, then Hugging Face.",
    )

    st.divider()
    st.caption("API keys (kept in this session only, never written to disk)")
    groq_key_input = st.text_input(
        "GROQ_API_KEY", type="password", value=os.environ.get("GROQ_API_KEY", "")
    )
    anthropic_key_input = st.text_input(
        "ANTHROPIC_API_KEY", type="password", value=os.environ.get("ANTHROPIC_API_KEY", "")
    )
    hf_key_input = st.text_input(
        "HF_TOKEN", type="password", value=os.environ.get("HF_TOKEN", "")
    )

    run_button = st.button("🔎 Investigate", type="primary", use_container_width=True)

if run_button:
    if groq_key_input:
        os.environ["GROQ_API_KEY"] = groq_key_input
    if anthropic_key_input:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key_input
    if hf_key_input:
        os.environ["HF_TOKEN"] = hf_key_input

st.divider()
st.subheader("Investigation")

st.session_state.setdefault("sessions", {})
st.session_state.setdefault("graph", None)

session_key = f"{feature}::{model_version}::{audience}"

if run_button:
    chosen_provider = None if provider_choice == "auto" else provider_choice
    if st.session_state.graph is None:
        st.session_state.graph = build_agentic_graph(chosen_provider)
    try:
        with st.spinner("Agent is investigating (calling tools)..."):
            config = {"configurable": {"thread_id": session_key}}
            result = st.session_state.graph.invoke(
                {"feature": feature, "model_version": model_version, "audience": audience},
                config=config,
            )
        if "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            st.session_state.sessions[session_key] = {
                "status": "awaiting_approval",
                "narrative": payload["narrative"],
                "guardrail_flags": payload.get("guardrail_flags", []),
                "trace": extract_tool_trace(result.get("messages", [])),
            }
        else:
            st.session_state.sessions[session_key] = {
                "status": "resolved",
                "narrative": result["narrative"],
                "approved": None,
                "guardrail_flags": [],
                "trace": [],
            }
    except Exception as e:
        st.error(str(e))

session = st.session_state.sessions.get(session_key)

if session is None:
    st.info("Configure options in the sidebar and click Investigate.")
elif session["status"] == "awaiting_approval":
    st.markdown(escape_dollars(session["narrative"]))

    if session["guardrail_flags"]:
        st.warning("⚠ Guardrail flags — review before approving:")
        for f in session["guardrail_flags"]:
            st.write(f"- {escape_dollars(f)}")
    else:
        st.success("No guardrail flags on this report.")

    if session["trace"]:
        with st.expander("Agent tool-call trace"):
            st.caption("What the agent actually called, in order — not pre-scripted.")
            for i, step in enumerate(session["trace"], 1):
                st.markdown(f"**{i}. `{step['tool']}({step['input']})`**")
                st.code(str(step["output"]), language="yaml")

    st.info(
        "Awaiting human approval — the graph is genuinely paused (a real "
        "langgraph interrupt), not just a UI state."
    )
    c1, c2 = st.columns(2)
    config = {"configurable": {"thread_id": session_key}}
    if c1.button("✅ Approve", type="primary", use_container_width=True):
        result = st.session_state.graph.invoke(Command(resume={"approved": True}), config=config)
        st.session_state.sessions[session_key] = {
            "status": "resolved",
            "narrative": result["narrative"],
            "approved": True,
            "guardrail_flags": session["guardrail_flags"],
            "trace": session["trace"],
        }
        st.rerun()
    if c2.button("❌ Reject", use_container_width=True):
        result = st.session_state.graph.invoke(Command(resume={"approved": False}), config=config)
        st.session_state.sessions[session_key] = {
            "status": "resolved",
            "narrative": result["narrative"],
            "approved": False,
            "guardrail_flags": session["guardrail_flags"],
            "trace": session["trace"],
        }
        st.rerun()
else:
    narrative = session["narrative"]
    st.markdown(escape_dollars(narrative))
    if session.get("approved") is not None:
        st.caption(f"Human decision: {'✅ Approved' if session['approved'] else '❌ Rejected'}")

    if session["guardrail_flags"]:
        with st.expander("⚠ Guardrail flags raised during review"):
            for f in session["guardrail_flags"]:
                st.write(f"- {escape_dollars(f)}")

    if session["trace"]:
        with st.expander("Agent tool-call trace"):
            for i, step in enumerate(session["trace"], 1):
                st.markdown(f"**{i}. `{step['tool']}({step['input']})`**")
                st.code(str(step["output"]), language="yaml")

    st.download_button(
        "Download report",
        narrative,
        file_name=f"{feature}_{audience}_report.md",
    )
