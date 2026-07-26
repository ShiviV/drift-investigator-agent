# Demo Video Script

Target length: **6-7 minutes**. The assessment asks for a short demo covering: what it
does, which AI tools you used, how the agent helped (plan/implement/debug/refactor),
what you built/fixed, what you cut to stay scoped, and the weakest part + what you'd
improve next. Every beat below maps to one of those, so nothing required gets missed
and nothing extra bloats the runtime.

All talking points below are pulled directly from [`07-demo-qa.md`](07-demo-qa.md) —
paraphrase them in your own words on camera, don't read verbatim, but the facts and
numbers are exact and verified, so don't improvise different ones live.

---

## Before you hit record

**Have these open in separate tabs/windows, in this order, so you can alt-tab instead of hunting:**

1. Finder window on `Code+Folder/` (for the planning-folder flash)
2. LangGraph Studio running (`langgraph dev` from `.venv_studio`) with the graph loaded
3. Streamlit app — local (`streamlit run streamlit_app.py`) and/or your deployed Community Cloud URL if it's live
4. `langgraph_investigator.py` open in an editor, scrolled to `verify_narrative_node` / `fact_check_node`
5. `planning/04-trade-offs.md` open in an editor (for the bugs-found beat)
6. Your GitHub repo page open in a browser tab

**Recording setup (macOS):** `Cmd+Shift+5` for screen recording, select a window or region (not the whole desktop — keeps focus tight), external mic or AirPods over the built-in laptop mic if possible. Record in one take if you can; it's fine to do 2-3 short segments and note where you'd cut if you want to edit later, but a single continuous take is honestly enough for this.

---

## Script

### 1. Hook (0:00–0:20)

**Show:** Your face or a title card, then straight to the Streamlit UI landing screen.

**Say:** One sentence on what it is — "This is a Drift Investigator agent I built on top of a real telecom churn-prediction ML pipeline. Given just a feature name and a model version, it autonomously investigates why the data drifted, decides which tools to call itself, and writes a report for a human to approve."

### 2. Planning + AI tools used (0:20–0:50)

**Show:** Quick Finder flash of the `planning/` folder (01 through 08 + `agent_logs/`), then back to the app.

**Say:** "Everything here was built with Claude Code as the primary coding agent — architecture, implementation, live debugging, deployment. The agent itself runs on three swappable LLM backends: Groq, Anthropic, and Hugging Face's free tier, and I used LangGraph Studio for visual debugging of the graph." Point at the planning folder as you say it — this is your proof you kept real planning artifacts, not just code.

**Add this one line before moving on:** "One assumption worth flagging up front — the agent doesn't detect drift itself, it assumes drift detection already happened elsewhere and a `drift_detected` flag is already set; it only starts investigating once that flag is true, it never decides on its own when to run. In the real world, that flag would come from a listener — a scheduled monitoring job or an alerting hook watching the pipeline — that invokes the agent automatically the moment drift is detected; here I'm triggering it manually by picking a feature in the UI instead of wiring up that listener."

### 3. Architecture walkthrough (0:50–2:00) — the highest-impact visual beat

**Show:** LangGraph Studio, the compiled graph.

**Say, tracing the graph with your cursor as you talk:**
- "It's not a fixed pipeline — it's a real agent. `check_drift` is a deterministic gate: if nothing's actually flagged, it skips the LLM entirely."
- "Once flagged, the model itself decides which of these three tools to call — drift metrics, lineage, or model metadata — in whatever order it wants, looping until it has enough evidence." (trace the agent↔tools loop)
- "Then two independent guardrail layers review the report before a human ever sees it — one deterministic, checking every number and version against real tool output, and one that's a second LLM call acting as a fact-checker."
- "And this last node is a real pause — `interrupt()` — execution genuinely halts until someone approves or rejects it."

### 4. Live run #1 — clear cause (2:00–3:20)

**Show:** Streamlit app. Select `total_charges` / a recent model version / any audience. Run it.

**Say while it runs:** "Watch the tool trace build live — it's calling drift metrics first, then lineage, then metadata, its own choice." When it finishes: point at the Root Cause section ("Billing Pipeline V2, deployed right before the drift, labeled a hypothesis, not a fact") and the guardrail flags panel. Click Approve.

### 5. Live run #2 — honest "no answer" (3:20–4:15)

**Show:** Same app, select `tenure` this time.

**Say:** "I deliberately built a scenario with no recorded cause, to see if the agent would fabricate one rather than admit it doesn't know." Let it run, point at the report saying the lineage trail is thin / inconclusive. "It didn't force a citation — this is the guardrail design working as intended, not a lucky output."

### 6. Real bugs found and fixed (4:15–5:00)

**Show:** `planning/04-trade-offs.md`, scrolled to the "-0.06 AUC swing" writeup, and/or `verify_narrative_node` in the editor.

**Full script — read this close to verbatim if it helps:**

> "Now, I want to show you this wasn't just an AI agent generating code that looked plausible — it caught and helped me fix real, live bugs. I'll give you three examples.
>
> First — Claude, running as the agent itself, once did the arithmetic wrong on two completely real numbers. It wrote about a negative-zero-point-oh-six AUC swing, but the actual gap between those two numbers was zero-point-oh-four-one. My fact-checker node — a second, independent model call whose only job is to check the report against the raw data — caught that mismatch and named the exact error.
>
> Second — while testing with Groq, I found it returns the literal string 'null' for tool calls that take zero arguments. My code was parsing that as JSON, which gives you Python's None instead of an empty dictionary, and that crashed argument unpacking until I explicitly handled it.
>
> And third — I actually found a bug in my own guardrail logic. A case-sensitivity issue meant 'v1' and 'V1' were being compared as different strings, so a completely real pipeline version was getting flagged as fabricated. All of this — every bug, what caused it, and how I fixed it — is written up in my trade-offs document, which is part of the planning folder."

### 7. What was cut, and the weakest part (5:00–5:45)

**Show:** Back to camera or the planning folder.

**Full script:**

> "Let me be direct about what I left out, and where this is weakest.
>
> I considered three other agent ideas before landing on this one. A compliance-and-audit reporting agent, and a smart retraining-cost optimizer — both needed infrastructure, like a real model registry or historical run-cost data, that simply doesn't exist in this project, and I didn't want to fake it just to check a box. I also looked at a GitOps pull-request reviewer — that one was actually buildable, but it felt generic. It wouldn't have extended this specific codebase the way a drift investigator does, so I dropped it.
>
> Now, the honest answer on the weakest part. There's a function called export_drift_summary, and its job is to pull structured results out of a live Deepchecks run. I wrote it against Deepchecks' documented API, but I never actually ran it end-to-end against a real, live Deepchecks execution to confirm the output shape is exactly right. It's wrapped in a try-except, so it fails gracefully instead of crashing anything — but 'doesn't crash' is not the same as 'verified correct.' If I kept working on this, running that function against a real pipeline and asserting its output schema is the very next thing I'd do."

### 8. Multi-provider + close (5:45–6:30)

**Show:** The provider dropdown in Streamlit, then your deployed live URL if you have one, then the GitHub repo page.

**Full script:**

> "One last thing worth showing — this agent isn't locked to one model provider. It runs interchangeably on Groq, on Anthropic's Claude, or on Hugging Face's free inference tier, and it auto-detects whichever one is configured. This wasn't a nice-to-have — I genuinely hit rate limits and a billing issue testing this, so having real fallbacks was necessary to keep working.
>
> [If deployed] And here's the live version, running on Streamlit Community Cloud — you don't need to run anything locally to try it yourself.
>
> That's the project. The code, the full planning folder, and my actual coding-agent session logs are all in the GitHub repo linked below. Thanks for watching."

**Say:** "It runs on Groq, Anthropic, or Hugging Face interchangeably — I needed that because I hit real rate limits and billing issues testing this. Repo's linked below, planning folder's in there, thanks for watching."

---

## Segment timing at a glance

| Segment | Time | Screen |
|---|---|---|
| Hook | 0:00-0:20 | Streamlit landing |
| Planning + AI tools | 0:20-0:50 | Finder: `planning/` |
| Architecture | 0:50-2:00 | LangGraph Studio |
| Live run: clear cause | 2:00-3:20 | Streamlit, `total_charges` |
| Live run: honest no-cause | 3:20-4:15 | Streamlit, `tenure` |
| Bugs found & fixed | 4:15-5:00 | `04-trade-offs.md` / editor |
| Cut + weakest part | 5:00-5:45 | Camera / planning folder |
| Multi-provider + close | 5:45-6:30 | Streamlit + GitHub |

## Required-content checklist (don't submit until every box is checked)

- [ ] What the project does
- [ ] Which AI tools/coding agents you used
- [ ] How the agent helped plan/implement/debug/refactor (name specific bugs)
- [ ] What features you added / bugs you fixed
- [ ] What you cut or simplified to stay scoped
- [ ] The weakest part, and what you'd improve next

## Tips

- Don't script word-for-word — bullet points only, talk naturally. A read-aloud script sounds worse than a slightly rougher natural take.
- If a live run misbehaves on camera (a provider rate limit, a slow response), don't panic-cut — say what's happening ("this is Groq's rate limit, let me switch to Anthropic") and keep going. That's more convincing than a suspiciously perfect take, and it's genuinely part of the story you already have documented.
- Cut dead air in editing (QuickTime's trim is enough) but don't over-edit — a demo that's clearly one continuous session is more credible than one that's obviously stitched from 20 clips.
