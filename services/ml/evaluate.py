"""Selection and one-shot, frozen final evaluation for Aegis PaySim.

Python loads the trained scorer and produces raw scores. All rules, fusion,
actions, capacity limits and hypothetical losses come from the Go evaluator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve
from threadpoolctl import threadpool_limits

from .data import EXPECTED_COLUMNS, READ_COLUMNS, SEED, sha256_file
from .features import FEATURE_NAMES
from .inference import predict_scores

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data/raw/paysim.csv"
ARTIFACTS = ROOT / "services/ml/artifacts"
REPORTS = ROOT / "reports"
ORCHESTRATOR = ROOT / "services/orchestrator"
STRATEGIES = ("ALWAYS_LEGITIMATE", "ML_ONLY", "RULES_ONLY", "SIMPLE_HYBRID", "CONFLICT_AWARE_HYBRID")
PARTITION_BOUNDS = {"train": (1, 400), "calibration": (401, 470), "selection": (471, 550), "test": (551, 743)}


def _json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _training_context() -> tuple[dict, dict]:
    report = _json(REPORTS / "training.json")
    audit = _json(REPORTS / "data_audit.json")
    source_hash = report.get("dataset", {}).get("sha256")
    if not source_hash or report.get("source_sha256") != source_hash:
        raise ValueError("training report source hash is missing or inconsistent")
    if sha256_file(DATA_PATH) != source_hash:
        raise ValueError("current PaySim CSV differs from the data used for training")
    return report, audit


def _load_artifacts(training: dict):
    metadata = _json(ARTIFACTS / "metadata.json")
    model_path, calibrator_path = ARTIFACTS / "model.joblib", ARTIFACTS / "calibrator.joblib"
    if metadata.get("model_version") != training.get("model_version"):
        raise ValueError("model version differs from training report")
    model_bytes, calibrator_bytes = model_path.read_bytes(), calibrator_path.read_bytes()
    for key, payload in (("model_sha256", model_bytes), ("calibrator_sha256", calibrator_bytes)):
        if hashlib.sha256(payload).hexdigest() != metadata.get(key) or metadata.get(key) != training.get(key):
            raise ValueError(f"{key} does not match the trained artifact")
    if metadata.get("source_sha256") != training.get("source_sha256"):
        raise ValueError("model was trained from a different data source")
    if metadata.get("feature_names") != FEATURE_NAMES:
        raise ValueError("model artifact feature schema differs from the current allowlist")
    return joblib.load(io.BytesIO(model_bytes)), joblib.load(io.BytesIO(calibrator_bytes)), metadata


def _read_window(path: Path, window: str, expected_rows: int) -> pd.DataFrame:
    """Read only a single time window; final labels are never parsed in selection mode."""
    lower, upper = PARTITION_BOUNDS[window]
    selected = []
    previous_step = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError("PaySim source header changed after training")
        for row in reader:
            step = int(row["step"])
            if step < previous_step:
                raise ValueError("PaySim rows are not in chronological step order")
            previous_step = step
            if step < lower:
                continue
            if step > upper:
                break
            selected.append({"step": step, "type": row["type"], "amount": float(row["amount"]), "isFraud": int(row["isFraud"])})
    frame = pd.DataFrame(selected, columns=READ_COLUMNS)
    if len(frame) != expected_rows:
        raise ValueError(f"{window} rows differ from audited count: got {len(frame)}, expected {expected_rows}")
    if frame.empty or set(frame["isFraud"].unique()) != {0, 1}:
        raise ValueError(f"{window} must contain both fraud and legitimate rows")
    return frame


def _predict(model, calibrator, frame: pd.DataFrame) -> np.ndarray:
    parts = []
    with threadpool_limits(limits=1):
        for start in range(0, len(frame), 20_000):
            batch = frame.iloc[start : start + 20_000]
            parts.append(predict_scores(model, calibrator, batch))
    scores = np.concatenate(parts)
    if len(scores) != len(frame) or not np.isfinite(scores).all():
        raise ValueError("model score count or values are invalid")
    return scores


def _write_go_input(frame: pd.DataFrame, scores: np.ndarray) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", prefix="aegis-eval-", delete=False)
    path = Path(handle.name)
    try:
        for row, score in zip(frame.itertuples(index=False), scores):
            item = {"step": int(row.step), "type": str(row.type), "amount": float(row.amount), "fraud": bool(row.isFraud), "ml_score": float(score)}
            handle.write(json.dumps(item, separators=(",", ":"), allow_nan=False) + "\n")
    finally:
        handle.close()
    return path


def _go(args: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("GOMODCACHE", "/tmp/aegis-go-mod")
    env.setdefault("GOCACHE", "/tmp/aegis-go-build")
    subprocess.run(["go", "run", "./cmd/evaluate", *args], cwd=ORCHESTRATOR, env=env, check=True)


def _go_score(frame: pd.DataFrame, scores: np.ndarray, window: str, output: Path) -> None:
    source = _write_go_input(frame, scores)
    try:
        _go(["score", "--window", window, "--input", str(source), "--output", str(output)])
    finally:
        source.unlink(missing_ok=True)


def _selection() -> dict:
    lock = REPORTS / "final-evaluation.lock"
    bundle = REPORTS / "selection_bundle.json"
    if lock.exists():
        raise SystemExit("final evaluation lock already exists; selection is frozen")
    if bundle.exists():
        raise SystemExit("selection bundle already exists; refusing to overwrite a frozen selection")
    training, audit = _training_context()
    model, calibrator, metadata = _load_artifacts(training)
    frame = _read_window(DATA_PATH, "selection", audit["partitions"]["selection"]["rows"])
    scores = _predict(model, calibrator, frame)
    input_path = _write_go_input(frame, scores)
    try:
        _go(["select", "--input", str(input_path)])
    finally:
        input_path.unlink(missing_ok=True)

    predictions_path = REPORTS / "selection_predictions.jsonl"
    _go_score(frame, scores, "selection", predictions_path)
    selection_metrics = _summarize(predictions_path, expected_rows=len(frame), include_rows=False)
    selection_metrics.update({"window": "selection", "steps": [471, 550], "used_to_choose_policies": True})
    _atomic_json(REPORTS / "selection_metrics.json", selection_metrics)
    manifest = _frozen_manifest(training, audit, metadata)
    manifest["selection_created_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["selection_predictions_sha256"] = sha256_file(predictions_path)
    manifest["primary_policy"] = _json(ROOT / "configs/policy.json")
    _atomic_json(REPORTS / "selection_manifest.json", manifest)
    return {"status": "selection complete; final test not read or scored", "rows": len(frame), "model_version": metadata["model_version"], "primary_policy": manifest["primary_policy"], "metrics": selection_metrics["strategies"]}


def _hashes() -> dict[str, str]:
    paths = {
        "source_data": DATA_PATH,
        "model": ARTIFACTS / "model.joblib",
        "calibrator": ARTIFACTS / "calibrator.joblib",
        "metadata": ARTIFACTS / "metadata.json",
        "features": ROOT / "services/ml/features.py",
        "inference": ROOT / "services/ml/inference.py",
        "evaluator_python": ROOT / "services/ml/evaluate.py",
        "evaluator_go": ORCHESTRATOR / "cmd/evaluate/main.go",
        "policy_go": ORCHESTRATOR / "internal/policy/policy.go",
        "selection_go": ORCHESTRATOR / "internal/policy/selection.go",
        "rules_go": ORCHESTRATOR / "internal/rules/rules.go",
        "policy_config": ROOT / "configs/policy.json",
        "rules_config": ROOT / "configs/rules.json",
        "scenarios_config": ROOT / "configs/scenarios.json",
        "selection_bundle": REPORTS / "selection_bundle.json",
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def _frozen_manifest(training: dict, audit: dict, metadata: dict) -> dict:
    return {
        "schema_version": "1.0",
        "source_sha256": training["source_sha256"],
        "model_version": metadata["model_version"],
        "model_sha256": metadata["model_sha256"],
        "calibrator_sha256": metadata["calibrator_sha256"],
        "partition_counts": audit["partitions"],
        "frozen_hashes": _hashes(),
    }


def _reserve_final_lock(manifest: dict) -> Path:
    path = REPORTS / "final-evaluation.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**manifest, "status": "started; final labels may now be read once", "started_at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SystemExit("final evaluation was already started; lock prevents a second run") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _final(confirm_final: bool) -> dict:
    if not confirm_final:
        raise SystemExit("refusing to open final test; pass --confirm-final only after selection review")
    lock_path = REPORTS / "final-evaluation.lock"
    final_report = REPORTS / "model_metrics.json"
    if lock_path.exists() or final_report.exists():
        raise SystemExit("final test lock or report already exists; refusing to score again")
    training, audit = _training_context()
    model, calibrator, metadata = _load_artifacts(training)
    recorded = _json(REPORTS / "selection_manifest.json")
    current = _frozen_manifest(training, audit, metadata)
    if recorded.get("frozen_hashes") != current["frozen_hashes"]:
        raise SystemExit("frozen code, data, artifact or policy changed after selection; final test remains unopened")
    if recorded.get("source_sha256") != training["source_sha256"]:
        raise SystemExit("selection manifest source hash mismatch")
    # Lock is durably written before opening/reading final-window labels.
    _reserve_final_lock(recorded)
    frame = _read_window(DATA_PATH, "test", audit["partitions"]["test"]["rows"])
    scores = _predict(model, calibrator, frame)
    predictions_path = REPORTS / "final_predictions.jsonl"
    _go_score(frame, scores, "final", predictions_path)
    metrics = _summarize(predictions_path, expected_rows=len(frame), include_rows=True)
    metrics.update({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {"name": "PaySim synthetic", "sha256": training["source_sha256"]},
        "model_version": metadata["model_version"],
        "frozen_hashes": recorded["frozen_hashes"],
        "split": {"selection": "471-550", "final_test": "551-743"},
        "final_test_read_once": True,
        "seed": SEED,
        "versions": training.get("versions", {}),
        "partition_counts": audit["partitions"],
        "feature_names": FEATURE_NAMES,
        "disclaimer": "This project is a prototype and is not financial advice.",
    })
    errors = metrics.pop("_error_rows")
    pr_curve = metrics.pop("_pr_curve")
    drift = metrics.pop("_drift")
    _write_experiments(metrics)
    _write_errors(errors)
    _write_pr_curve(pr_curve)
    _write_drift(drift)
    _write_limitations(metrics)
    _atomic_json(final_report, metrics)
    lock = _json(lock_path)
    lock.update({"status": "completed", "completed_at_utc": datetime.now(timezone.utc).isoformat(), "final_predictions_sha256": sha256_file(predictions_path)})
    _atomic_json(lock_path, lock)
    return {"status": "final test scored once", "rows": len(frame), "model_version": metadata["model_version"], "strategies": metrics["strategies"]}


def _summarize(path: Path, expected_rows: int, include_rows: bool) -> dict:
    """Stream Go rows; retain only bounded numeric arrays for ranking metrics."""
    if expected_rows <= 0:
        raise ValueError("evaluation partition is empty")
    scenario_ids = {item["id"] for item in _json(ROOT / "configs/scenarios.json")["scenarios"]}
    bundle = _json(REPORTS / "selection_bundle.json")
    scores = {strategy: np.empty(expected_rows, dtype=np.float64) for strategy in STRATEGIES}
    predictions = {strategy: np.empty(expected_rows, dtype=np.bool_) for strategy in STRATEGIES}
    labels = np.empty(expected_rows, dtype=np.bool_)
    ml_scores = np.empty(expected_rows, dtype=np.float64)
    groups = {strategy: {"by_step": {}, "by_type": {}, "conflicts": {}} for strategy in STRATEGIES}
    errors = {strategy: {"false_positive": [], "false_negative": []} for strategy in STRATEGIES}
    scenarios = {scenario: {} for scenario in scenario_ids}
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if set(item) != set(STRATEGIES) or count >= expected_rows:
                raise ValueError("Go evaluator strategy set or row count differs from source partition")
            reference = item[STRATEGIES[0]]
            if not isinstance(reference["fraud"], bool):
                raise ValueError("Go evaluator label is not boolean")
            labels[count] = reference["fraud"]
            ml_scores[count] = float(reference["ml_score"])
            for strategy in STRATEGIES:
                row = item[strategy]
                for field in ("step", "type", "amount", "fraud", "ml_score", "rule_score"):
                    if row[field] != reference[field]:
                        raise ValueError("strategies do not refer to the same transaction and label")
                value = float(row["score"])
                if not np.isfinite(value) or not 0 <= value <= 1 or not isinstance(row["predicted_fraud"], bool):
                    raise ValueError("invalid Go score or classification")
                scores[strategy][count] = value
                predictions[strategy][count] = row["predicted_fraud"]
                step = int(row["step"])
                start = 471 if step <= 550 else 551
                band_start = start + ((step - start) // 50) * 50
                band = f"{band_start}-{min(550 if step <= 550 else 743, band_start + 49)}"
                _group_update(groups[strategy]["by_step"], band, row)
                _group_update(groups[strategy]["by_type"], row["type"], row)
                _group_update(groups[strategy]["conflicts"], row["conflict"], row)
                if include_rows:
                    predicted, fraud = row["predicted_fraud"], row["fraud"]
                    kind = "false_positive" if predicted and not fraud else "false_negative" if fraud and not predicted else None
                    if kind and len(errors[strategy][kind]) < 5:
                        errors[strategy][kind].append({
                            "strategy": strategy, "error_type": kind, "step": step, "type": row["type"],
                            "amount": row["amount"], "label": int(fraud), "predicted_fraud": predicted,
                            "ml_score": row["ml_score"], "rule_score": row["rule_score"], "conflict": row["conflict"],
                        })
                for field in ("actions", "unbounded_actions", "simulated_losses", "default_actions_without_cost_optimizer", "default_simulated_losses", "top_k_selected"):
                    if set(row[field]) != scenario_ids:
                        raise ValueError(f"incomplete Go scenario field {field}")
                for scenario in scenario_ids:
                    cost = scenarios[scenario].setdefault(strategy, {
                        "approve": 0, "review": 0, "flag": 0, "unbounded_review": 0, "unbounded_flag": 0,
                        "capacity_downgraded_reviews": 0, "total_simulated_cost": 0.0,
                        "fraud_approved_misses": 0, "fraud_sent_to_review": 0, "fraud_flagged": 0,
                        "legitimate_flagged": 0, "default_total_simulated_cost": 0.0,
                        "default_approve": 0, "default_review": 0, "default_flag": 0,
                        "top_k_selected_rows": 0, "top_k_selected_frauds": 0,
                    })
                    action, unbounded = row["actions"][scenario], row["unbounded_actions"][scenario]
                    default_action = row["default_actions_without_cost_optimizer"][scenario]
                    if any(action_name not in ("APPROVE", "REVIEW", "FLAG") for action_name in (action, unbounded, default_action)):
                        raise ValueError("unknown Go policy action")
                    loss, default_loss = float(row["simulated_losses"][scenario]), float(row["default_simulated_losses"][scenario])
                    if not np.isfinite(loss) or not np.isfinite(default_loss) or min(loss, default_loss) < 0:
                        raise ValueError("invalid Go scenario loss")
                    cost[action.lower()] += 1
                    cost["default_" + default_action.lower()] += 1
                    cost["unbounded_review"] += int(unbounded == "REVIEW")
                    cost["unbounded_flag"] += int(unbounded == "FLAG")
                    cost["capacity_downgraded_reviews"] += int(unbounded == "REVIEW" and action == "APPROVE")
                    cost["total_simulated_cost"] += loss
                    cost["default_total_simulated_cost"] += default_loss
                    cost["fraud_approved_misses"] += int(row["fraud"] and action == "APPROVE")
                    cost["fraud_sent_to_review"] += int(row["fraud"] and action == "REVIEW")
                    cost["fraud_flagged"] += int(row["fraud"] and action == "FLAG")
                    cost["legitimate_flagged"] += int(not row["fraud"] and action == "FLAG")
                    selected = row["top_k_selected"][scenario]
                    if not isinstance(selected, bool):
                        raise ValueError("invalid Go top-K selection flag")
                    cost["top_k_selected_rows"] += int(selected)
                    cost["top_k_selected_frauds"] += int(selected and row["fraud"])
            count += 1
    if count != expected_rows:
        raise ValueError("Go evaluator output row count does not match source partition")
    if not np.isfinite(ml_scores).all() or ((ml_scores < 0) | (ml_scores > 1)).any():
        raise ValueError("invalid ML score in Go output")
    frauds = int(labels.sum())
    strategy_metrics, pr_curves = {}, {}
    for strategy in STRATEGIES:
        predicted = predictions[strategy]
        tp, fp = int(np.sum(labels & predicted)), int(np.sum(~labels & predicted))
        tn, fn = int(np.sum(~labels & ~predicted)), int(np.sum(labels & ~predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / frauds if frauds else 0.0
        strategy_metrics[strategy] = {
            "rows": count, "frauds": frauds, "fraud_prevalence": frauds / count,
            "threshold_from_selection": float(bundle["classification_policies"][strategy]["classification_threshold"]), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "average_precision": float(average_precision_score(labels, scores[strategy])),
            "fpr": fp / (fp + tn) if fp + tn else 0.0,
            "false_alarms_per_1000": 1000 * fp / count,
            "alerts_per_1000": 1000 * int(predicted.sum()) / count,
        }
        precision_curve, recall_curve, thresholds = precision_recall_curve(labels, scores[strategy])
        indices = np.linspace(0, len(precision_curve) - 1, min(250, len(precision_curve)), dtype=int)
        pr_curves[strategy] = [{"recall": float(recall_curve[i]), "precision": float(precision_curve[i]), "threshold": float(thresholds[i]) if i < len(thresholds) else None} for i in indices]
    for scenario, strategies in scenarios.items():
        for strategy, cost in strategies.items():
            frozen_cost = bundle["cost_policies"][strategy][scenario]
            default_policy = bundle["classification_policies"][strategy]
            cost.update({
                "review_threshold": frozen_cost["review_threshold"],
                "flag_threshold": frozen_cost["flag_threshold"],
                "default_review_threshold": default_policy["review_threshold"],
                "default_flag_threshold": default_policy["flag_threshold"],
                "denominator_rows": count, "hypothetical_cost_scenario": scenario,
                "cost_per_1000": cost["total_simulated_cost"] * 1000 / count,
                "default_cost_per_1000": cost["default_total_simulated_cost"] * 1000 / count,
                "cost_optimizer_delta_per_1000": (cost["total_simulated_cost"] - cost["default_total_simulated_cost"]) * 1000 / count,
                "review_precision": cost["fraud_sent_to_review"] / cost["review"] if cost["review"] else 0.0,
                "review_recall": cost["fraud_sent_to_review"] / frauds if frauds else 0.0,
                "top_k_precision": cost["top_k_selected_frauds"] / cost["top_k_selected_rows"] if cost["top_k_selected_rows"] else 0.0,
                "top_k_recall": cost["top_k_selected_frauds"] / frauds if frauds else 0.0,
            })
    result = {"strategies": strategy_metrics, "cost_scenarios": scenarios,
              "evaluation_denominators": {
                  "rows_per_strategy": count, "classification_metrics_use_all_source_rows": True,
                  "alerts_per_1000_denominator": "all rows in the partition",
                  "false_alarms_per_1000_denominator": "all rows in the partition",
                  "capacity": "per simulator step floor(rows * capacity_per_1000 / 1000); excess REVIEW becomes APPROVE, FLAG preserved",
                  "top_k": "all rows ranked by frozen strategy score within simulator step; same capacity floor, original row order breaks ties; labels never select rows",
                  "cost_ablation": "same frozen strategy scores, scenario and capacity; fixed default action cutoffs (REVIEW .35, FLAG .8, distinct from F1 classification threshold) versus selection cost-optimized cutoffs; negative delta favors optimizer",
                  "average_precision": "sklearn average_precision_score on scores, including constant-score baseline whose AP equals prevalence; not trapezoidal PR-AUC",
              }}
    bins, ece = [], 0.0
    for index in range(10):
        lower, upper = index / 10, (index + 1) / 10
        mask = (ml_scores >= lower) & ((ml_scores < upper) if index < 9 else (ml_scores <= upper))
        n = int(mask.sum())
        if n:
            mean, observed = float(ml_scores[mask].mean()), float(labels[mask].mean())
            ece += n / count * abs(mean - observed)
            bins.append({"lower": lower, "upper": upper, "rows": n, "mean_ml_score": mean, "observed_fraud_rate": observed})
    result["ml_probability_diagnostics"] = {
        "score_field": "calibrated ML score only; rule and fusion heuristics excluded",
        "brier_score": float(np.mean((ml_scores - labels.astype(float)) ** 2)),
        "expected_calibration_error_10_equal_width_bins": float(ece), "reliability_bins": bins,
        "caveat": "Temporal prevalence drift means calibration need not transfer to later periods.",
    }
    if include_rows:
        drift = {"by_step": {}, "by_type": {}, "conflicts": _groups_finalize(groups["CONFLICT_AWARE_HYBRID"]["conflicts"])}
        for strategy in STRATEGIES:
            for field in ("by_step", "by_type"):
                drift[field][strategy] = _groups_finalize(groups[strategy][field])
        result.update({"_error_rows": [row for kinds in errors.values() for rows in kinds.values() for row in rows], "_pr_curve": pr_curves, "_drift": drift})
    return result

def _threshold_for(strategy: str) -> float:
    bundle = _json(REPORTS / "selection_bundle.json")
    return float(bundle["classification_policies"][strategy]["classification_threshold"])


def _group_update(groups: dict, key: str, row: dict) -> None:
    group = groups.setdefault(key, {"rows": 0, "frauds": 0, "tp": 0, "fp": 0, "tn": 0, "fn": 0})
    group["rows"] += 1
    fraud, predicted = bool(row["fraud"]), bool(row["predicted_fraud"])
    group["frauds"] += int(fraud)
    if fraud and predicted: group["tp"] += 1
    elif not fraud and predicted: group["fp"] += 1
    elif fraud: group["fn"] += 1
    else: group["tn"] += 1


def _groups_finalize(groups: dict) -> dict:
    for group in groups.values():
        group["fraud_prevalence"] = group["frauds"] / group["rows"] if group["rows"] else 0.0
        group["precision"] = group["tp"] / (group["tp"] + group["fp"]) if group["tp"] + group["fp"] else 0.0
        group["recall"] = group["tp"] / (group["tp"] + group["fn"]) if group["tp"] + group["fn"] else 0.0
    return groups


def _write_experiments(metrics: dict) -> None:
    scenarios = _json(ROOT / "configs/scenarios.json")["scenarios"]
    path = REPORTS / "decision_experiments.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["split", "strategy", "scenario", "threshold_from_selection", "rows", "frauds", "tp", "fp", "tn", "fn", "precision", "recall", "f1", "average_precision", "fpr", "false_alarms_per_1000", "alerts_per_1000", "approve", "review", "flag", "total_simulated_cost", "cost_per_1000"]
        fields.extend(["review_threshold", "flag_threshold", "default_review_threshold", "default_flag_threshold", "unbounded_review", "unbounded_flag", "capacity_downgraded_reviews", "fraud_approved_misses", "fraud_sent_to_review", "fraud_flagged", "legitimate_flagged", "review_precision", "review_recall", "default_total_simulated_cost", "default_cost_per_1000", "cost_optimizer_delta_per_1000", "default_approve", "default_review", "default_flag", "top_k_selected_rows", "top_k_selected_frauds", "top_k_precision", "top_k_recall"])
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for strategy, value in metrics["strategies"].items():
            for scenario in scenarios:
                cost = metrics["cost_scenarios"][scenario["id"]][strategy]
                row = {"split": "final_test_551_743", "strategy": strategy, "scenario": scenario["id"], **value, **cost}
                writer.writerow({key: row.get(key, "") for key in fields})


def _write_errors(rows: list[dict]) -> None:
    path = REPORTS / "error_cases.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["strategy", "error_type", "step", "type", "amount", "label", "predicted_fraud", "ml_score", "rule_score", "conflict"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_pr_curve(value: dict) -> None:
    _atomic_json(REPORTS / "pr_curve.json", value)


def _write_drift(value: dict) -> None:
    _atomic_json(REPORTS / "drift_metrics.json", value)


def _write_limitations(metrics: dict) -> None:
    prevalence = {name: value["fraud_prevalence"] for name, value in metrics["strategies"].items()}
    text = """# Measured limitations\n\n"""
    text += "- PaySim is synthetic and may contain simulator artifacts; results do not establish effectiveness at a bank or payment provider.\n"
    text += "- The held-out test covers steps 551–743. Model, rules and policy were frozen on earlier windows; temporal prevalence drift limits transfer to other periods.\n"
    text += "- Review costs, false-block costs, success rates and per-step capacities are hypothetical scenarios, not observed operational costs. Capacity is applied per simulator step using floor(step_rows × capacity_per_1000 / 1000); excess reviews become approvals while flags remain.\n"
    text += "- Scores and decisions are research outputs. They do not affect real transactions; see the README disclaimer.\n"
    text += f"- The held-out fraud prevalence measured in this run was {next(iter(prevalence.values())):.6f}; the strategy rows share the same test labels.\n"
    (REPORTS / "limitations.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--select-only", action="store_true", help="tune policies on steps 471–550 and freeze their hashes")
    modes.add_argument("--final", action="store_true", help="consume held-out steps 551–743 exactly once")
    parser.add_argument("--confirm-final", action="store_true", help="required explicit gate for one-shot final scoring")
    args = parser.parse_args()
    if args.select_only and args.confirm_final:
        parser.error("--confirm-final is only valid with --final")
    result = _selection() if args.select_only else _final(args.confirm_final)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
