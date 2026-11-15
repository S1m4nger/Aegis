#!/usr/bin/env python3
"""Verify live local inference and graceful shutdown; no fake scoring service."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:18080" + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as response:
        return response.code, json.load(response)


def stop(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def verify_batch_parity(temporary, env):
    """Synthetic contract probes use selection-window steps, never held-out rows."""
    bundle_path = ROOT / "reports/selection_bundle.json"
    if not bundle_path.exists():
        return {"status": "not run; selection bundle missing"}
    bundle = json.loads(bundle_path.read_text())
    primary = json.loads((ROOT / "configs/policy.json").read_text())
    strategy = primary["strategy"]
    parameters = lambda policy: {key: value for key, value in policy.items() if key != "note"}
    scenario = next(key for key, policy in bundle["cost_policies"][strategy].items()
                    if parameters(policy) == parameters(primary))
    samples = [("TRANSFER", 0), ("TRANSFER", 125000), ("TRANSFER", 2000000),
               ("TRANSFER", 10000000), ("CASH_OUT", 200000), ("CASH_OUT", 2000000),
               ("PAYMENT", 100), ("CASH_IN", 1000000), ("DEBIT", 1)]
    online = []
    source = Path(temporary) / "parity-input.jsonl"
    output = Path(temporary) / "parity-output.jsonl"
    with source.open("w") as stream:
        for kind, amount in samples:
            tx = {"step": 500, "type": kind, "amount": amount}
            status, result = request("/v1/analyze", tx)
            assert status == 200, result
            online.append(result)
            stream.write(json.dumps({**tx, "fraud": False, "ml_score": result["ml_score"]}) + "\n")
    subprocess.run(["go", "run", "-buildvcs=false", "./cmd/evaluate", "score", "--window", "selection",
                    "--input", str(source), "--output", str(output)],
                   cwd=ROOT / "services/orchestrator", env=env, check=True)
    offline = [json.loads(line)[strategy] for line in output.read_text().splitlines()]
    assert len(offline) == len(online)
    for live, batch in zip(online, offline):
        assert math.isclose(live["rule_score"], batch["rule_score"], abs_tol=1e-12)
        assert math.isclose(live["fusion_score"], batch["score"], abs_tol=1e-12)
        assert live["conflict_type"] == batch["conflict"]
        assert live["recommended_action"] == batch["unbounded_actions"][scenario]
    return {"status": "passed", "synthetic_samples": len(samples), "strategy": strategy,
            "scenario": scenario, "comparison": "score, rules, conflict, unbounded action"}


def verify_scenarios_and_dashboard():
    from streamlit.testing.v1 import AppTest

    report_path = ROOT / "reports/model_metrics.json"
    if not report_path.exists():
        return {"status": "not run; final report missing"}
    before = report_path.read_bytes()
    metrics = json.loads(before)
    scenario_document = json.loads((ROOT / "configs/scenarios.json").read_text())
    comparisons = 0
    for scenario in scenario_document["scenarios"]:
        cohorts = []
        for strategy, values in metrics["cost_scenarios"][scenario["id"]].items():
            cohorts.append({"strategy": strategy, "rows": metrics["strategies"][strategy]["rows"],
                            "frauds": metrics["strategies"][strategy]["frauds"],
                            **{key: values[key] for key in ("review", "fraud_approved_misses",
                               "fraud_sent_to_review", "fraud_flagged", "legitimate_flagged")}})
        status, result = request("/v1/simulate", {"scenario": scenario, "cohorts": cohorts})
        assert status == 200 and result["scenario_only"] is True
        for row in result["cohorts"]:
            measured = metrics["cost_scenarios"][scenario["id"]][row["strategy"]]
            assert math.isclose(row["total_simulated_cost"], measured["total_simulated_cost"], rel_tol=1e-9, abs_tol=1e-5)
            comparisons += 1
    with patch.dict(os.environ, {"AEGIS_API_URL": "http://127.0.0.1:18080",
                                 "AEGIS_REPORTS_DIR": str(ROOT / "reports")}):
        ui = AppTest.from_file(str(ROOT / "app/dashboard.py"), default_timeout=20).run()
        assert not ui.exception
        assert not ui.text_input, "API origin must remain server-owned"
        next(button for button in ui.button if button.label == "Analyze transaction").click().run()
        assert not ui.exception
        assert ui.session_state["last_analysis"][1]["model_version"] == metrics["model_version"]
        next(button for button in ui.button if button.label == "Recalculate scenario in Go").click().run()
        assert not ui.exception
        assert any("Hypothetical scenario only." in item.value for item in ui.info)
    assert report_path.read_bytes() == before
    return {"status": "passed", "scenario_strategy_comparisons": comparisons,
            "live_ui_analyzer": True, "live_ui_cost_lab": True, "final_report_unchanged": True}


def main():
    generated = ROOT / "reports/generated"
    generated.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GOMODCACHE="/tmp/aegis-go-mod", GOCACHE="/tmp/aegis-go-build",
               AEGIS_HTTP_ADDR="127.0.0.1:18080", AEGIS_ML_URL="http://127.0.0.1:18091",
               AEGIS_RULES_PATH=str(ROOT / "configs/rules.json"),
               AEGIS_POLICY_PATH=str(ROOT / "configs/policy.json"))
    processes = []
    outcome = {"timestamp": datetime.now(timezone.utc).isoformat(), "status": "failed"}
    try:
        with tempfile.TemporaryDirectory(prefix="aegis-demo-") as temporary, (generated / "demo-ml.log").open("w") as ml_log, (generated / "demo-go.log").open("w") as go_log:
            binary = str(Path(temporary) / "aegis")
            subprocess.run(["go", "build", "-buildvcs=false", "-o", binary, "./cmd/aegis"], cwd=ROOT / "services/orchestrator", env=env, check=True)
            ml = subprocess.Popen([str(ROOT / ".venv/bin/uvicorn"), "services.ml.app:app", "--host", "127.0.0.1", "--port", "18091"], cwd=ROOT, env=env, stdout=ml_log, stderr=ml_log)
            processes.append(ml)
            go = subprocess.Popen([binary], cwd=ROOT, env=env, stdout=go_log, stderr=go_log)
            processes.append(go)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if ml.poll() is not None or go.poll() is not None:
                    raise RuntimeError("service exited before ready; inspect reports/generated/demo-*.log")
                try:
                    if request("/health/ready")[0] == 200:
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError("local services did not become ready")
            assert request("/health/live")[0] == 200
            tx = {"step": 550, "type": "TRANSFER", "amount": 125000}
            status, analysis = request("/v1/analyze", tx)
            assert status == 200 and analysis["model_version"].startswith("paysim-lr-")
            assert analysis["disclaimer"] == "This project is a prototype and is not financial advice."
            assert request("/v1/analyze", {"step": 1, "type": "TRANSFER"})[0] == 400
            parity = verify_batch_parity(temporary, env)
            dashboard = verify_scenarios_and_dashboard()
            stop(ml)
            assert request("/health/ready")[0] == 503
            assert request("/v1/analyze", tx)[0] == 503
            stop(go)
            assert go.returncode == 0, f"Go graceful stop exit {go.returncode}"
            outcome.update(status="passed", transaction=tx, analysis=analysis,
                           batch_api_parity=parity,
                           dashboard_and_scenario_checks=dashboard,
                           missing_scorer_status=503, missing_amount_status=400,
                           go_graceful_shutdown_exit=go.returncode)
            print(json.dumps(outcome, indent=2))
    finally:
        for process in reversed(processes):
            stop(process)
        (ROOT / "reports/demo.json").write_text(json.dumps(outcome, indent=2) + "\n")
        with (ROOT / "docs/verification-log.md").open("a") as log:
            log.write(f"\n## {outcome['timestamp']} live demo\n`.venv/bin/python scripts/demo_check.py`: {outcome['status']}. Real trained model; see `reports/demo.json`. No final-test metrics computed.\n")


if __name__ == "__main__":
    main()
