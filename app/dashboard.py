"""Presentation only: measured evidence from disk, live decisions and recosting in Go."""
from pathlib import Path
import csv
import json
import math
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_config import configured_api_url, post_json

ROOT = Path(__file__).resolve().parents[1]
REPORTS = Path(os.environ.get("AEGIS_REPORTS_DIR", str(ROOT / "reports")))
STRATEGIES = ["ALWAYS_LEGITIMATE", "ML_ONLY", "RULES_ONLY", "SIMPLE_HYBRID", "CONFLICT_AWARE_HYBRID"]
NAMES = {"ALWAYS_LEGITIMATE": "Always legitimate", "ML_ONLY": "ML only", "RULES_ONLY": "Rules only", "SIMPLE_HYBRID": "Simple hybrid", "CONFLICT_AWARE_HYBRID": "Conflict-aware hybrid"}
COLORS = {"ALWAYS_LEGITIMATE": "#8995aa", "ML_ONLY": "#69a7ff", "RULES_ONLY": "#a5a7f5", "SIMPLE_HYBRID": "#51d0bc", "CONFLICT_AWARE_HYBRID": "#ff9d62"}
SCENARIOS = {
    "review_low_cost": {"missed_fraud_cost": 1000, "false_block_cost": 50, "review_cost": 2, "review_success_rate": .9, "capacity_per_1000": 10},
    "review_expensive": {"missed_fraud_cost": 1000, "false_block_cost": 200, "review_cost": 20, "review_success_rate": .7, "capacity_per_1000": 5},
    "missed_fraud_expensive": {"missed_fraud_cost": 5000, "false_block_cost": 50, "review_cost": 5, "review_success_rate": .9, "capacity_per_1000": 20},
}


def load_json(name):
    try:
        value = json.loads((REPORTS / name).read_text(encoding="utf8"))
        if not isinstance(value, dict):
            raise ValueError("report must be a JSON object")
        return value
    except FileNotFoundError:
        st.info(f"Measured report unavailable: {name}. Run the documented evaluation before showing evidence.")
    except (OSError, ValueError, TypeError):
        st.warning(f"Could not read {name}. The saved evidence needs inspection; no substitute numbers are displayed.")
    return None


def load_csv(name):
    try:
        with (REPORTS / name).open(encoding="utf8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            st.info(f"No measured rows in {name}.")
        return pd.DataFrame(rows)
    except (OSError, csv.Error, UnicodeError):
        st.info(f"Measured table unavailable: {name}.")
        return pd.DataFrame()


def api_post(base, route, payload):
    return post_json(base, route, payload)


def chart(figure, title, y_title="", x_title=""):
    figure.update_layout(title=dict(text=title, font=dict(size=17)), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#d7dfed", size=12), margin=dict(l=12, r=12, t=48, b=12), legend=dict(orientation="h", y=-.22), height=360, yaxis_title=y_title, xaxis_title=x_title)
    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})


def valid_metrics(value):
    if not isinstance(value.get("strategies"), dict) or set(value["strategies"]) != set(STRATEGIES):
        raise ValueError("missing strategy comparison")
    required = ["rows", "frauds", "tp", "fp", "tn", "fn", "precision", "recall", "f1", "average_precision", "false_alarms_per_1000", "alerts_per_1000"]
    for data in value["strategies"].values():
        if not isinstance(data, dict):
            raise ValueError("strategy metrics must be objects")
        if any(isinstance(data.get(key), bool) or not isinstance(data.get(key), (int, float)) or not math.isfinite(data[key]) for key in required):
            raise ValueError("invalid measured strategy table")
        if data["rows"] <= 0 or sum(data[key] for key in ("tp", "fp", "tn", "fn")) != data["rows"]:
            raise ValueError("inconsistent evidence denominator")
    if not isinstance(value.get("cost_scenarios"), dict):
        raise ValueError("missing cost scenarios")
    return value


def analyzer(api):
    st.subheader("One transaction. Two independent signals.")
    st.write("Enter a synthetic PaySim-style operation to inspect the frozen Go policy and its rule trace.")
    with st.form("analyzer"):
        left, middle, right = st.columns([1, 1.3, 1.5])
        step = left.number_input("Simulation step", min_value=1, max_value=1_000_000, value=550, help="Simulator hours, not a real calendar time.")
        kind = middle.selectbox("Transaction type", ["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"])
        amount = right.number_input("Amount · simulated units", min_value=0.0, max_value=1e12, value=10_000_000.0, format="%.2f")
        submitted = st.form_submit_button("Analyze transaction", type="primary")
    if submitted:
        st.session_state.pop("last_analysis", None)
        tx = {"step": int(step), "type": kind, "amount": float(amount)}
        try:
            response = api_post(api, "/v1/analyze", tx)
            for key in ("ml_score", "rule_score", "fusion_score"):
                if isinstance(response.get(key), bool) or not isinstance(response.get(key), (int, float)) or not math.isfinite(response[key]) or not 0 <= response[key] <= 1:
                    raise ValueError("Go API returned an invalid score")
            if response.get("recommended_action") not in ("APPROVE", "REVIEW", "FLAG") or not isinstance(response.get("fired_rules"), list):
                raise ValueError("Go API returned an invalid action or rule trace")
            if any(not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not isinstance(rule.get("explanation"), str) for rule in response["fired_rules"]):
                raise ValueError("Go API returned an invalid rule explanation")
            for key in ("model_version", "policy_version", "conflict_type"):
                if not isinstance(response.get(key), str) or not response[key]:
                    raise ValueError("Go API response is missing version or conflict metadata")
            st.session_state["last_analysis"] = (tx, response)
        except (ValueError, TypeError, KeyError):
            st.error("Analysis unavailable. Check the Go API, trained scorer and response contract; no fallback score is used.")
    if "last_analysis" not in st.session_state:
        st.info("Submit a synthetic transaction to see actual Go → Python ML → Go rules/fusion → recommendation.")
        return
    tx, response = st.session_state["last_analysis"]
    st.caption(f"Last analyzed input: step {tx['step']} · {tx['type']} · {tx['amount']:,.2f} simulated units")
    a, b, c = st.columns(3)
    a.metric("ML score", f"{response['ml_score']:.4f}")
    b.metric("Rule heuristic", f"{response['rule_score']:.4f}")
    c.metric("Fusion risk score", f"{response['fusion_score']:.4f}")
    action = response["recommended_action"]
    show = st.success if action == "APPROVE" else st.warning if action == "REVIEW" else st.error
    show(f"Recommendation: {action} · {response['conflict_type']}")
    st.caption("A recommendation for research only. No real payment is blocked. Rule and fusion scores are heuristic, not fraud probabilities; ML calibration is subject to temporal drift.")
    if response["fired_rules"]:
        st.dataframe(pd.DataFrame(response["fired_rules"]).rename(columns={"id": "Rule", "weight": "Heuristic weight", "explanation": "Reason", "priority": "Priority"}), hide_index=True, width="stretch")
    else:
        st.write("No declarative rule triggered for this input.")
    st.caption(f"Model {response['model_version']} · Policy {response['policy_version']}")
    with st.expander("Inspect the Go response"):
        st.json(response)


def evidence(metrics):
    if metrics is None:
        st.info("Evidence appears here after a valid measured evaluation report is available.")
        return
    data = metrics["strategies"]
    reference = data["CONFLICT_AWARE_HYBRID"]
    a, b, c, d = st.columns(4)
    a.metric("Held-out transactions", f"{reference['rows']:,}")
    b.metric("Fraud prevalence", f"{reference['frauds'] / reference['rows']:.2%}")
    c.metric("Conflict-aware F1", f"{reference['f1']:.3f}")
    d.metric("Conflict-aware recall", f"{reference['recall']:.1%}")
    st.caption(f"PaySim synthetic · final steps 551–743 · model {metrics.get('model_version', 'unavailable')} · trained 1–400, calibrated 401–470, selected 471–550.")
    simple, conflict = data["SIMPLE_HYBRID"], data["CONFLICT_AWARE_HYBRID"]
    st.info(f"Measured trade-off: simple hybrid F1 {simple['f1']:.3f}; conflict-aware F1 {conflict['f1']:.3f}. Conflict-aware AP {conflict['average_precision']:.3f}; simple hybrid AP {simple['average_precision']:.3f}. The conflict approach did not win every metric. Both retain substantial missed fraud.")
    rows = [{"Strategy": NAMES[name], "Precision": data[name]["precision"], "Recall": data[name]["recall"], "F1": data[name]["f1"], "AP": data[name]["average_precision"], "False alarms / 1,000": data[name]["false_alarms_per_1000"], "Alerts / 1,000": data[name]["alerts_per_1000"]} for name in STRATEGIES]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={key: st.column_config.NumberColumn(format="%.3f") for key in ["Precision", "Recall", "F1", "AP", "False alarms / 1,000", "Alerts / 1,000"]})
    st.caption("Classification thresholds were selected before the final test. AP means average precision on scores, not trapezoidal PR-AUC. Constant baseline AP equals prevalence.")
    performance, drift_tab, cost_tab, failures = st.tabs(["Ranking & errors", "Temporal drift", "Cost & capacity", "Failure cases"])
    with performance:
        curves = load_json("pr_curve.json")
        if curves:
            try:
                fig = go.Figure()
                for name in STRATEGIES:
                    points = curves[name]
                    fig.add_trace(go.Scatter(x=[p["recall"] for p in points], y=[p["precision"] for p in points], mode="lines", name=NAMES[name], line=dict(color=COLORS[name], dash="dash" if name == "ALWAYS_LEGITIMATE" else "solid")))
                chart(fig, "Precision–recall on the same final rows", "Precision", "Recall")
                st.caption("Curves sampled from measured predictions for display; AP uses every scored row.")
            except (KeyError, TypeError, ValueError):
                st.warning("PR curve report is incomplete or invalid.")
        chosen = st.selectbox("Inspect classification counts", STRATEGIES, index=4, format_func=NAMES.get)
        item = data[chosen]
        st.dataframe(pd.DataFrame({"Actual class": ["Legitimate", "Fraud"], "Predicted legitimate": [item["tn"], item["fn"]], "Predicted fraud": [item["fp"], item["tp"]]}), hide_index=True, width="stretch")
        st.caption("These binary detection counts differ from cost-policy recommendations below.")
        probability = metrics.get("ml_probability_diagnostics", {})
        if "brier_score" in probability:
            st.caption(f"ML-only Brier score: {probability['brier_score']:.6f}. Calibration on an earlier window does not guarantee accuracy on later periods.")
    with drift_tab:
        drift = load_json("drift_metrics.json")
        if drift:
            try:
                selected = st.selectbox("Drift strategy", STRATEGIES, index=4, format_func=NAMES.get)
                bands = drift["by_step"][selected]
                fig = go.Figure()
                fig.add_trace(go.Bar(x=list(bands), y=[v["fraud_prevalence"] for v in bands.values()], name="Observed fraud rate", marker_color="#ff9d62"))
                chart(fig, "Fraud prevalence across final time blocks", "Fraud fraction", "Simulator step interval")
                st.dataframe(pd.DataFrame([{"Step interval": k, **v} for k, v in bands.items()]), hide_index=True, width="stretch")
                with st.expander("Transaction types and independent signal conflicts"):
                    st.dataframe(pd.DataFrame([{"Type": k, **v} for k, v in drift["by_type"][selected].items()]), hide_index=True, width="stretch")
                    st.dataframe(pd.DataFrame([{"Conflict group": k, **v} for k, v in drift["conflicts"].items()]), hide_index=True, width="stretch")
                st.caption("PaySim time and type cohorts are simulator evidence, not real demographic or fairness analysis.")
            except (KeyError, TypeError, ValueError):
                st.warning("Drift report is incomplete or invalid.")
    with cost_tab:
        try:
            selected = st.selectbox("Measured cost scenario", list(metrics["cost_scenarios"]), key="evidence_scenario")
            costs = metrics["cost_scenarios"][selected]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=[NAMES[s] for s in STRATEGIES], y=[costs[s]["cost_per_1000"] for s in STRATEGIES], name="Selection-optimized cutoffs", marker_color="#ff9d62"))
            fig.add_trace(go.Bar(x=[NAMES[s] for s in STRATEGIES], y=[costs[s]["default_cost_per_1000"] for s in STRATEGIES], name="Fixed default cutoffs", marker_color="#536780"))
            chart(fig, "Hypothetical cost · optimizer ablation", "Arbitrary cost units / 1,000 transactions")
            st.caption("Same frozen scores, true labels and capacity. Fixed defaults REVIEW .35 / FLAG .8 are separate from classification thresholds. Costs include review failure assumptions; no real monetary savings are claimed.")
            st.dataframe(pd.DataFrame([{"Strategy": NAMES[s], "Reviews": costs[s]["review"], "Flags": costs[s]["flag"], "Fraud approved": costs[s]["fraud_approved_misses"], "Legitimate flagged": costs[s]["legitimate_flagged"], "Top-K precision": costs[s]["top_k_precision"], "Top-K recall": costs[s]["top_k_recall"]} for s in STRATEGIES]), hide_index=True, width="stretch")
            st.caption("Top-K ranks all rows within each simulator step using frozen scores and floor(step rows × budget / 1,000); labels do not select rows. Constant-score baseline ties follow source order. Online API recommendations have no batch capacity state.")
            with st.expander("Inspect full measured experiment table"):
                table = load_csv("decision_experiments.csv")
                if not table.empty:
                    st.dataframe(table, hide_index=True, width="stretch")
        except (KeyError, TypeError, ValueError):
            st.warning("Cost report is incomplete or invalid.")
    with failures:
        cases = load_csv("error_cases.csv")
        if not cases.empty:
            selected = st.selectbox("Failure-case strategy", STRATEGIES, index=4, format_func=NAMES.get)
            if "strategy" in cases:
                st.dataframe(cases[cases["strategy"] == selected], hide_index=True, width="stretch")
            else:
                st.warning("Failure-case table has an invalid schema.")
            st.caption("Actual false positives and false negatives, redacted to approved input fields. Error cases were inspected after policy freezing; no thresholds were retuned.")


def lab(api, metrics):
    st.subheader("Change the cost assumptions. Keep the actions frozen.")
    st.write("This lab asks Go to recost saved final-test action cohorts. It does not rescore transactions, select new thresholds or change the published experiment.")
    if metrics is None:
        st.info("A valid measured cost report is required for the scenario lab.")
        return
    try:
        base_id = st.selectbox("Frozen action cohort", [name for name in SCENARIOS if name in metrics["cost_scenarios"]], key="lab_cohort")
        default = SCENARIOS[base_id]
        st.caption(f"Review capacity stays fixed at {default['capacity_per_1000']} per 1,000 within each simulator step. Sliders recost these saved actions only.")
        with st.form("scenario_lab"):
            left, right = st.columns(2)
            missed = left.slider("Missed-fraud cost · arbitrary units", 100, 10000, default["missed_fraud_cost"], 100)
            blocked = right.slider("False-block cost · arbitrary units", 0, 1000, default["false_block_cost"], 10)
            review = left.slider("Review cost · arbitrary units", 0, 100, default["review_cost"], 1)
            success = right.slider("Assumed review catch rate", 0.0, 1.0, default["review_success_rate"], .05)
            submitted = st.form_submit_button("Recalculate scenario in Go", type="primary")
        if submitted:
            cohorts = []
            for strategy in STRATEGIES:
                saved = metrics["cost_scenarios"][base_id][strategy]
                cohorts.append({"strategy": strategy, "rows": metrics["strategies"][strategy]["rows"], "frauds": metrics["strategies"][strategy]["frauds"], **{key: saved[key] for key in ["review", "fraud_approved_misses", "fraud_sent_to_review", "fraud_flagged", "legitimate_flagged"]}})
            scenario = {"id": "interactive", "missed_fraud_cost": missed, "false_block_cost": blocked, "review_cost": review, "review_success_rate": success, "capacity_per_1000": default["capacity_per_1000"]}
            result = api_post(api, "/v1/simulate", {"scenario": scenario, "cohorts": cohorts})
            if result.get("scenario_only") is not True or not isinstance(result.get("cohorts"), list):
                raise ValueError("Go response does not identify an isolated scenario")
            rows = result["cohorts"]
            if len(rows) != len(STRATEGIES) or any(not isinstance(row, dict) or row.get("strategy") not in NAMES or isinstance(row.get("cost_per_1000"), bool) or not isinstance(row.get("cost_per_1000"), (int, float)) or not math.isfinite(row["cost_per_1000"]) or row["cost_per_1000"] < 0 for row in rows):
                raise ValueError("Go response has invalid scenario costs")
            if {row["strategy"] for row in rows} != set(STRATEGIES):
                raise ValueError("Go response has duplicate or missing strategies")
            fig = go.Figure(go.Bar(x=[NAMES[row["strategy"]] for row in rows], y=[row["cost_per_1000"] for row in rows], marker_color="#ff9d62"))
            chart(fig, "Scenario only · Go recosting of frozen actions", "Arbitrary cost units / 1,000 transactions")
            st.info("Hypothetical scenario only. Saved final-test actions, thresholds and reports remain unchanged.")
            st.caption(str(result.get("note", "Frozen actions; no new optimization.")))
    except (KeyError, TypeError, ValueError):
        st.error("Scenario unavailable. Check the measured cohorts and Go simulation endpoint; no local cost formula is substituted.")


def main():
    st.set_page_config(page_title="Aegis AI · Fraud Intelligence", page_icon="◇", layout="wide")
    try:
        api = configured_api_url()
    except ValueError:
        st.error("Application configuration is invalid. Ask the operator to check AEGIS_API_URL.")
        st.stop()
    st.markdown("""<style>
    .stApp {background:#0a1020;color:#e2e8f3;}
    .block-container {max-width:1280px;padding-top:2.2rem;padding-bottom:3rem;}
    h1,h2,h3 {letter-spacing:-.025em;}
    [data-testid="stMetric"] {background:#111c30;border:1px solid #26334b;border-radius:12px;padding:16px;}
    [data-testid="stSidebar"] {background:#0e1728;}
    </style>""", unsafe_allow_html=True)
    st.caption("AEGIS / RESEARCH PROTOTYPE / AI + FINANCE")
    st.title("See the signal. Inspect the disagreement.")
    st.write("Hybrid fraud intelligence on synthetic PaySim transactions, with transparent rules and measured trade-offs.")
    st.warning("This project is a prototype and is not financial advice.")
    st.sidebar.caption("Go owns rules and decisions. Python serves the trained model. This dashboard displays results.")
    st.sidebar.divider()
    st.sidebar.write("**Evidence discipline**")
    st.sidebar.caption("Chronological partitions. Frozen final test. No tuning in this dashboard.")
    metrics = load_json("model_metrics.json")
    if metrics is not None:
        try:
            metrics = valid_metrics(metrics)
        except (KeyError, TypeError, ValueError):
            st.warning("The measured report has an invalid schema. Evidence and scenario views are unavailable.")
            metrics = None
    analyze_tab, evidence_tab, lab_tab = st.tabs(["Transaction analyzer", "Measured evidence", "Conflict & cost lab"])
    with analyze_tab:
        analyzer(api)
    with evidence_tab:
        try:
            evidence(metrics)
        except (KeyError, TypeError, ValueError, AttributeError):
            st.warning("The saved evidence is incomplete or invalid. Inspect the report files before presenting results.")
    with lab_tab:
        lab(api, metrics)


if __name__ == "__main__":
    main()
