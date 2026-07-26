# Drift Investigation Report: Feature `tenure` — Model `v14`

## Alert Summary
The `tenure` feature attached to `customer_churn_v14` has moved from a stable, non-drifting state in early June into confirmed drift by late July. PSI climbed steadily from 0.03 on 2026-06-01 to 0.31 on 2026-07-31, and the `drift_detected` flag flips to `True` starting 2026-07-24 (PSI 0.22) and remains true through 2026-07-31 (PSI 0.31). This is not a sudden spike — it's a monotonic, accelerating drift that was visible in the trend line for roughly seven weeks before crossing the alerting threshold.

## Root Cause Identified (Hypothesis)
I looked for an upstream pipeline change that could explain this, since `tenure` is a natural candidate for pipeline-driven shifts (e.g., a recompute logic change). However, the lineage record shows only a single pipeline version for this feature: **Customer Profile Pipeline v1**, deployed **2026-06-01**, status Active, with no `known_issue` or `incident_id` fields present in the record. Critically, this deployment predates the entire observation window — it was already in place on day one when PSI was a benign 0.03 — so it cannot be the trigger for drift that only becomes visible weeks later. There is no second pipeline version or redeployment event in the lineage data to point to.

Given the absence of any upstream code/version change coinciding with the drift onset, my working hypothesis is that this is **organic covariate drift** in the underlying customer population — i.e., the real-world distribution of customer tenure is genuinely shifting upward in production (average tenure climbing from 24.3 to 29.5 over two months), rather than a pipeline defect artificially altering the values. This should be treated as a hypothesis, not a confirmed root cause, since we have no direct evidence of *why* the population is aging in tenure (could be reduced new-customer acquisition, seasonal cohort effects, or a genuine business trend). It is not attributable to the pipeline deployment on record.

## Statistical Variance
- **PSI trend**: 0.03 → 0.04 → 0.05 → 0.06 → 0.08 → 0.10 → 0.13 → 0.17 → **0.22 (drift flagged 2026-07-24)** → **0.31 (2026-07-31)**. The commonly used PSI drift threshold (~0.2) was crossed on 2026-07-24, and the metric nearly grew another 40% relatively in the following week alone — the rate of drift is accelerating, not plateauing.
- **Mean shift**: training mean is fixed at 24.1; production mean rose from 24.3 (06-01) to 29.5 (07-31), a steady, monotonic increase week over week with no reversals — consistent with a real distributional shift rather than noise.
- **Model performance (from drift-monitor accuracy series)**: accuracy degraded from 0.922 (06-01) to 0.895 (07-31), a modest but continuous decline tracking the PSI trend.
- **Model performance (from model run history)**: over the same window, accuracy fell from 0.922 to 0.832 and AUC fell from 0.951 to 0.861 by 07-31 — a sharper decline than the drift-monitor's accuracy series shows. I want to flag this discrepancy explicitly: the two accuracy series (drift-metrics vs. model-metadata) don't fully agree in magnitude, which is worth reconciling since they may be computed on different samples or cadences.
- **Feature importance**: `tenure` carries an importance weight of 0.21 in `v14` — the second-highest of the four listed features (behind `total_charges` at 0.39). Given this weight, a drift of this magnitude in `tenure` is plausible as a meaningful contributor to the observed accuracy/AUC degradation, though `total_charges` should also be checked given its larger importance.

## Lineage Context
The lineage trail for `tenure` is thin: a single entry, `Customer Profile Pipeline v1`, owned by the Customer Data Team, deployed 2026-06-01 and marked Active with no incidents or known issues logged against it. This is a double-edged finding — it rules out a "bad deploy" narrative (there's simply no second version to blame), but it also means we lack visibility into whether anything changed in the upstream data source (e.g., a CRM system feeding tenure values, a change in how "tenure" is calculated, or new customer segments entering the population) that isn't captured in this pipeline's version history.

## Recommended Actions
1. Escalate to the Customer Data Team (pipeline owner) to check for any silent/unlogged changes to the tenure calculation logic or upstream data sources around late June, since the lineage record shows no incident despite the pipeline being the sole version in production.
2. Pull a raw production sample of `tenure` values from the past 8 weeks and compare cohort composition (e.g., new vs. long-tenured customers) to confirm whether this is genuine population drift versus a data quality artifact (nulls defaulting to a high value, unit conversion, etc.).
3. Reconcile the two divergent accuracy series (drift-monitor vs. model-metadata) to determine which is authoritative before using either to justify a retraining decision.
4. Given `tenure`'s 0.21 feature importance and the PSI trajectory still accelerating (not plateauing) as of 07-31, treat this as high-priority: consider a retraining or recalibration cycle for `v14`, prioritized alongside a similar drift check on `total_charges` given its even higher importance.
5. Add automated alerting at a lower PSI threshold (e.g., 0.1) for this feature going forward — the trend was visible five weeks before the alert fired at 0.22, and earlier intervention would have reduced the accuracy/AUC erosion window.
6. Since the pipeline's lineage record currently has no incident logging capability evidenced here, confirm with the Customer Data Team whether their change-management process reliably surfaces schema or logic changes to this monitoring system — the clean lineage record could reflect either genuine stability or a gap in tracking.

---

**Human approval:** Approved
