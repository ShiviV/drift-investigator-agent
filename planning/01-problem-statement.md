# Problem Statement

This pipeline already computes real drift and model-degradation checks via Deepchecks
(`src/ml_pipeline/drift.py`) — `WholeDatasetDrift`, `TrainTestFeatureDrift`,
`FeatureLabelCorrelationChange` (PPS), `TrainTestLabelDrift`, and `check_model_drift`
(recall/f1). Today the output of a run is just a boolean `retrain` flag plus a
multi-megabyte static HTML report (`reports/*_data_drift_report.html`, ~7-8MB,
minified) — there's no plain-English explanation of *why* a retrain fired, no
connection to what changed upstream that might explain it, and no way to communicate
the result to a non-technical stakeholder without them opening a huge HTML dump.

## Aim

Build a "Drift Investigator" agent (`drift_investigator.py`, project root) that
consumes this pipeline's drift-check output, correlates any flagged signal against a
lightweight record of recent pipeline/data changes, and uses an LLM to generate a
plain-English root-cause narrative — renderable for different audiences (exec / MLOps
engineer / data scientist) from the same underlying analysis.

## What's new work vs. pre-existing

Pre-existing (not built during this assessment window): `src/engine.py`,
`src/ml_pipeline/{processing,utils,train,evaluate,drift}.py`, the trained models, the
notebook, and the original README (this is a ProjectPro-sourced churn-modeling
project — worth being upfront about that lineage rather than presenting it as built
from scratch).

New work this session: `export_drift_summary()` appended to `drift.py` (additive only
— no existing function was modified), `drift_investigator.py`, `sample_data/`,
`planning/`, and `requirements-drift-investigator.txt`.

## Note on scope of "real" vs "synthetic"

The drift-check *inputs* consumed by the investigator in this demo are synthetic YAML
files (`sample_data/`), constructed to match the pipeline's real schema and real
thresholds exactly. Running the pinned `deepchecks==0.12.0` + old sklearn/xgboost stack
end-to-end wasn't completed in this environment, so `export_drift_summary()` is
untested against a live `SuiteResult` object — see [[04-trade-offs]] for what to verify
before relying on it against real data.
