# Trade-offs

- **Lineage is a hand-authored YAML, not a real metadata/lineage store.** This pipeline
  doesn't use MLflow or any model registry today — models are saved via
  `.save_model()`/pickle with no run tracking. A production version of this agent would
  query something like MLflow or ML Metadata; here it reads a static snapshot. The
  agent's tool/prompt is named honestly around this
  (`training_run_metadata`, not `mlflow_run`) — don't imply live MLflow integration in
  the demo or video.
- **Correlation is simple time-window + feature-name matching, not causal inference.**
  The LLM's root-cause narrative is a hypothesis based on correlated timing, not
  verified causation. The report format labels it "(Hypothesis)" for this reason.
- **`export_drift_summary()` is untested against a live Deepchecks `SuiteResult`.** It's
  written against the same public API the rest of `drift.py` already relies on
  (`get_not_passed_checks()`/`get_not_ran_checks()`), and wrapped in try/except so a
  version mismatch degrades gracefully rather than crashing — but running the pinned
  `deepchecks==0.12.0` stack end-to-end wasn't done in this session. Verify the exported
  YAML shape against a real run before trusting it for anything beyond the demo.
- **Drift-check inputs used for the demo are synthetic**, built to match the real
  schema and real thresholds exactly, for the reason above.
- **Single LLM call per run, no retry/caching robustness.**
- **This tool doesn't reduce or replace the actual Deepchecks computation** — it's a
  consumer of that output, not a replacement for it.

## Revision: the first version wasn't actually agentic

The first working version single-shot everything: Python code deterministically loaded
the drift report, flagged failing checks, correlated the changelog, then stuffed all of
that pre-computed context into one prompt for one LLM call. That's a **workflow** (a
fixed code path with an LLM call at the end), not an **agent** — the model never decided
anything.

The current version is a real tool-calling loop: the model is given only a `job_id` and
three tools (`get_drift_report`, `get_training_run_metadata`, `get_pipeline_changelog`),
and it decides which to call, in what order, and when it has enough to write the report.
The deterministic flagging/correlation functions still exist, but only to power a
"preview" panel in the UI for a human — the agent doesn't receive their output and
re-discovers everything itself. This is worth stating plainly in the demo: it's a
real example of catching an overclaim (calling something an "agent" when it wasn't
one) and correcting it, which is exactly the kind of self-correction their rubric asks
about.

## Real bugs hit and fixed while wiring up Groq (Llama-3.3-70B)

While testing the agent loop live against the label-drift fixture, three real issues
surfaced:

1. **Groq returns the literal string `"null"`** (not an empty string) as a tool call's
   arguments for zero-parameter tools. `json.loads("null")` is Python `None`, not `{}`,
   which crashed `**args` unpacking. Fixed by coercing `None` back to `{}` after parsing.
2. **Groq occasionally rejects its own model's tool-call output** as malformed
   (`tool_use_failed`) — Llama-3.3 sometimes emits a non-JSON tool-call format. This is
   transient generation noise, not a request bug; added a 3-attempt retry around the
   `chat.completions.create` call.
3. **The agent cited a chronologically impossible root cause.** Given the label-drift
   fixture (run_date 2026-02-10), it initially picked the "MegaPack 2000" changelog
   entry — dated 2026-07-15, five months *after* the alert — over the correct
   "TechCorp layoffs" entry (2026-02-02, 8 days before). It picked the thematically
   closer-sounding entry over the chronologically possible one. Fixed by adding an
   explicit instruction to the system prompt: check every candidate changelog entry's
   date against run_date and discard anything dated after it, no matter how relevant it
   sounds. Re-running the same fixture after the fix produced correct, self-checking
   reasoning ("...since this change occurred after the run_date... it cannot be the
   cause... a more plausible hypothesis is the regional layoffs").

All three are genuine, verified-live "where the AI-assisted approach failed and how it
was corrected" material — good to walk through directly in the demo rather than only
mentioning the more abstract trade-offs above.

## Guardrails added to the unified LangGraph agent, and a real limitation found testing them

`langgraph_investigator.py`'s unified 3-tool agent (`drift`/`lineage`/`metadata` as separate
nodes) got four guardrails, each catching a real failure mode observed in this session:

1. **Input validation** (`check_drift_node`) — unknown `feature`/`model_version` values
   raise a clear error listing valid options, instead of crashing on `metrics[-1]` against
   an `{"error": ...}` dict.
2. **Turn cap** (`MAX_AGENTIC_TURNS = 6`, enforced in `route_tool_calls`) — forces the agent
   to finalize after 6 turns regardless of whether it still wants to call tools, so a
   pathological loop can't burn tokens indefinitely.
3. **Structural check** (`verify_narrative_node`) — confirms all five required report
   sections are present before the report reaches a human for approval.
4. **Numeric-fabrication check** (`verify_narrative_node`) — cross-references every decimal
   number in the generated narrative against numbers that actually appeared in tool output
   this run, flagging anything that doesn't. This is what originally caught the model
   inventing "a threshold of 0.9" that appeared nowhere in the data.

**A real limitation found while testing guardrail #4:** on a later run, the model wrote
*"exceeding the threshold of 0.1"* — a PSI threshold that doesn't exist anywhere in
`drift_metrics.json`. The guardrail didn't flag it, because `0.1` genuinely *does* appear
in the tool output that run — as `support_tickets`' feature importance in
`model_metadata.json`, a completely unrelated number for a different feature. The model
borrowed a real number from an unrelated context and presented it as something else. A
naive "does this number appear anywhere in tool output" check catches wholesale invention
but not recontextualization — a more sophisticated check (tying the number to a *specific
claim* about a *specific field*, not just checking it exists somewhere in the tool output
text) would be needed to catch this class of hallucination. Documented here rather than
"fixed" given the remaining time — a real, verified-live guardrail gap is more honest
demo material than a guardrail that appears to catch everything but wasn't actually
stress-tested.

## Guardrails hardened further, and two more real bugs found running on Claude

Went back to fix the recontextualization gap above rather than just document it. Added:

5. **Prompt injection defense** (system prompt) — explicit instruction that tool output is
   data to analyze, never instructions to follow, even if it contains text that looks like
   a command or role change.
6. **Pipeline version / incident ID citation checks** (`verify_narrative_node`) — same
   presence-check pattern as the numeric check, extended to `V\d+` version tags and
   incident IDs.
7. **`fact_check_node`** — a second, independent LLM call that reviews the narrative
   against raw tool output and can catch a real value being *misapplied* to the wrong
   claim, not just wholesale invention. This directly targets the recontextualization gap
   guardrail #4 couldn't catch.

**Switching providers to test guardrail #7 surfaced two more real bugs, both fixed:**

- `langchain_anthropic`'s `.content` can be a list of content blocks instead of a plain
  string, even with no tool calls involved — crashed `verify_narrative_node`'s regex checks
  the first time this ran against Claude (`TypeError: expected string or bytes-like
  object`). Fixed with a `_message_text()` normalizer used everywhere a message's content
  is read.
- No `max_tokens` was set at all, so Claude used `langchain_anthropic`'s default (1024).
  Claude's reports run substantially longer than Llama's — the structural-completeness
  guardrail (#3) correctly caught the resulting truncation twice (once at the 1024 default,
  again at 2048) before landing on 4096 as sufficient.

**Guardrail #7 then caught a genuine arithmetic hallucination on the first clean run:**
Claude wrote "a -0.06 AUC swing (0.902 → 0.861)" — the two source numbers were both real,
but 0.902 − 0.861 = 0.041, not 0.06. The deterministic check flagged `0.06` as absent from
tool output; `fact_check_node` independently named the specific arithmetic error and stated
the correct value. That's real semantic verification catching a class of error presence-
checking alone can't — the model didn't invent an unrelated number, it did math wrong on
two real ones.

**The injection defense showed a positive signal too:** with no actual injected content in
the fixtures, the model's own report included an unprompted line — *"no anomalous embedded
instructions were found in the data returned by any tool during this investigation"* —
indicating it's actively following the instruction to scrutinize tool output rather than
just trusting it by default. Worth stress-testing with an actual injected payload in
`lineage.json` before claiming this defense is proven, not just present.

## A third provider: Hugging Face (free tier)

Added `huggingface` as a third `_get_chat_model()` branch (`langchain-huggingface`,
`meta-llama/Llama-3.3-70B-Instruct` via HF's Inference Providers routing,
`provider="auto"`). Confirmed real tool-calling works on the free tier — this wasn't
guaranteed going in; not every model HF hosts supports `bind_tools()` reliably, and this
was verified with an isolated test before wiring it into the graph, not assumed. Full
end-to-end run completed cleanly through all 9 nodes including both guardrail layers,
which caught two more real, distinct issues on the first try: a correctly-computed but
not-directly-quoted derived number (0.47 − 0.02 = 0.45, real math, just not literally
present in any single tool output), and the fact-checker flagging a hypothesis that was
worded with more certainty than the evidence supports. All three providers (Groq,
Anthropic, Hugging Face) now produce genuinely different failure/success patterns worth
mentioning in the demo: Llama-3.3 (Groq and HF both) writes tersely and occasionally
mishandles date arithmetic; Claude writes thoroughly (needed higher `max_tokens`) and
had an infrastructure-level quirk (extended-thinking blocks not surviving Studio's state
serialization) rather than a reasoning error.

## What was cut and why (for the demo's "weakest part" question)

Four agent-use-case directions were considered before landing on root-cause
investigation: compliance/audit reporting, smart retraining-cost optimization, a
GitOps/CI PR reviewer, and root-cause drift investigation. The first two were cut
because they need infrastructure (a model registry, historical run-cost data) that
doesn't exist in this project and can't be faked convincingly in the time available.
The PR-reviewer idea was buildable but generic — it doesn't extend this codebase the
way the root-cause investigator does. Root-cause investigation was chosen because it's
the tightest scope that still does meaningful new work on top of the real `drift.py`.

The weakest part of what shipped: `export_drift_summary()`'s per-feature extraction
was written from documented Deepchecks API knowledge but never run against a live
`SuiteResult` in this environment, so its exact output shape for `TrainTestFeatureDrift`
/`FeatureLabelCorrelationChange` values should be verified, not assumed correct.
