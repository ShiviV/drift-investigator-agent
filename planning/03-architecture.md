# Architecture

```
existing pipeline (unchanged)
   └─ drift.py: check_data_drift_with_label / check_model_drift
        └─ export_drift_summary() → drift_report_{job_id}.yaml (structured, not HTML)
                                            │
                                    (fixture files on disk,
                                     not pre-fetched into a prompt)
                                            │
                                    ┌───────┴────────────────────────┐
                                    │   drift_investigator agent      │
                                    │   given only: job_id, audience  │
                                    │                                 │
                                    │   model decides, turn by turn:  │
                                    │   → get_drift_report(job_id)    │
                                    │   → get_training_run_metadata() │
                                    │   → get_pipeline_changelog()    │
                                    │   → reasons about relevance     │
                                    │   → writes final report         │
                                    └───────┬────────────────────────┘
                                            ▼
                              agent_reports/{job_id}_{audience}_report.md
                              (+ tool-call trace appended)
```

This is a genuine tool-calling agent loop (real function-calling against Claude/Groq,
multi-turn), not a single prompt pre-stuffed with pre-gathered context. Earlier drafts
of this tool did the latter — see the note below on that revision.

A separate, deterministic "preview" path (`flag_checks`/`correlate_changelog`) still
exists and powers the Streamlit UI's preview panel, so a human can see what's in the
data before running the agent. The agent does not receive this precomputed result —
it re-discovers it itself via tool calls, which the UI's trace view makes visible.

## Task breakdown (as executed)

1. Added `export_drift_summary()` to `drift.py` — additive only, no existing function
   touched.
2. Authored `sample_data/pipeline_changelog.yaml` and
   `sample_data/training_run_metadata.yaml` with realistic entries tied to the real
   feature names and a real-looking incident (see `agent-system-prompt.md`).
3. Built `drift_investigator.py`: load → flag against real thresholds → correlate
   (deterministic) → single LLM call → `--audience` variants → markdown output.
4. Built 2 fixture drift reports (flagged: feature+concept drift+model drift; clean:
   nothing flagged) for demo contrast.
5. This `planning/` folder + `README.md` updates with trade-offs.
6. Remaining: install `requirements-drift-investigator.txt`, set `ANTHROPIC_API_KEY`,
   run against both fixtures, record demo.

## Agent design

See `agent-system-prompt.md` for the full system prompt and a worked example output.
The agent's two inputs beyond the flagged drift report are `training_run_metadata.yaml`
(explicitly *not* a live MLflow integration — see trade-offs) and
`pipeline_changelog.yaml`, used for deterministic time-correlation before the single LLM
call synthesizes the narrative.
