# Agent System Prompt

```
You are a Churn Model Drift Investigator Agent for the customer retention team.
You are given a structured drift-check summary (already flagged against the
pipeline's real thresholds), the deployed model's training-run metadata (baseline
dataset version, training date, baseline feature stats), and any pipeline changelog
entries that were time-correlated with the flagged features.

Construct a multi-tiered stakeholder summary: Alert Summary, Root Cause Identified,
Statistical Variance, Lineage Context, Recommended Actions.

Label the root cause as a hypothesis unless the correlation is very strong: you have
been given correlated timing, not verified causation. Do not invent data, dates, or
events that were not provided to you.
```

Note: the "lineage" tool is deliberately **not** named/framed as MLflow. This pipeline
doesn't use MLflow — models are saved via `.save_model()`/pickle with no run tracking.
The agent reads a static YAML snapshot instead. Say so explicitly in the demo video
rather than implying live MLflow integration.

## Worked example output (target format)

Given `sample_data/drift_report_infer_2026q3_001.yaml` +
`sample_data/training_run_metadata.yaml` + `sample_data/pipeline_changelog.yaml`:

```
Alert Summary: Production Churn Model Performance Degradation

- Root Cause Identified (Hypothesis): Feature `total_rech_amt` (total recharge
  amount) has undergone significant numerical distribution drift, and its
  relationship to churn outcomes has also shifted — a compound signal of both
  data drift and concept drift.

- Statistical Variance: Deepchecks reported an Earth Mover's (Wasserstein)
  Distance of 0.34 for `total_rech_amt`, violating the pipeline's stability
  threshold (< 0.2). Its Predictive Power Score against churn dropped from
  0.45 (training) to 0.18 (production) — a difference of 0.27, exceeding the
  concept-drift threshold (< 0.2).

- Model Impact: Recall on production data fell to 0.71 (threshold 0.80), and
  F1 fell to 0.58 (threshold 0.5) — both below the pipeline's retrain trigger.

- Lineage Context: The currently deployed model (xgb_churn_v3, run 1njkwna)
  was trained on dataset version telecom_churn_2026Q1 (2026-04-02), when
  recharge denominations capped typical top-ups near $500 (p95: $410). On
  2026-07-15 — 5 days before this alert — Marketing launched "MegaPack 2000,"
  a new $1000-$2500 recharge denomination. A competitor loyalty promotion
  targeting high-ARPU customers also launched 2026-06-30, which may explain
  why high recharge amounts no longer predict retention as strongly as before.

Recommended Actions:
1. Investigate whether MegaPack 2000 purchasers are a behaviorally distinct
   segment (e.g. bulk/reseller accounts) that should be modeled separately,
   or whether the raw feature needs capping/log-scaling before it reaches
   the model.
2. Trigger a retrain using a dataset window that includes post-MegaPack-2000
   data so the model relearns the current relationship between recharge
   amount and churn.
3. Flag the competitor promotion as a business event to monitor — if
   attributable, this is a market-driven concept shift, not a data quality
   issue, and retraining alone won't fix it without new features capturing
   competitive context.
```

This reuses this project's own `total_rech_amt` PPS-flip observation (the original
slide walkthrough's illustration of concept drift) combined with a numeric-drift story
parallel to a cap-limited-value pattern, so the fixture is grounded in the actual
project rather than generic.

## Stakeholder-tailored variants (`--audience`)

- **exec**: one-line health status + business impact, no drift-score jargon —
  e.g. "Churn model reliability dropped this week due to a new high-value recharge
  pack changing customer behavior. Retraining recommended before next campaign cycle."
- **mlops**: the full report above, focused on thresholds, pipeline state, and the
  retrain trigger.
- **datascientist**: the full report above, plus the raw PPS/drift numbers and a note
  on which check caught it and which one would have missed it (this pipeline's own
  observation: `TrainTestFeatureDrift` alone misses concept drift — only
  `FeatureLabelCorrelationChange` catches it).
