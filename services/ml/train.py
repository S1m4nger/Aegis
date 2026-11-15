"""Fit and calibrate the PaySim baseline without evaluating the held-out test."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .data import MAX_TRAIN_NEGATIVES, SEED, load_training_partitions, sha256_file
from .features import DENYLIST, FEATURE_NAMES, make_features
from .modeling import build_calibrator, build_model

ROOT = Path(__file__).resolve().parents[2]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_joblib(value, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        joblib.dump(value, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _versions() -> dict:
    packages = ("numpy", "pandas", "scikit-learn", "joblib", "threadpoolctl")
    return {"python": platform.python_version(), **{package: importlib.metadata.version(package) for package in packages}}


def _rule_candidates(train_frame: pd.DataFrame) -> dict:
    """Suggest amount cutoffs from the fit sample only; selection must choose among them."""
    quantiles = (0.50, 0.75, 0.90, 0.95, 0.99)
    candidates = {}
    for tx_type in ("TRANSFER", "CASH_OUT"):
        amounts = train_frame.loc[train_frame.type == tx_type, "amount"].astype("float64")
        if amounts.empty:
            raise ValueError(f"training sample has no {tx_type} rows for rule candidates")
        candidates[tx_type] = {
            str(q): float(amounts.quantile(q, interpolation="linear")) for q in quantiles
        }
    return {
        "source": "train_fit_sample_only; all frauds plus deterministic capped negative sample",
        "quantiles": list(quantiles),
        "amount_thresholds": candidates,
        "selection_required": True,
    }


def _calibration_logits(model, frame: pd.DataFrame, chunk_size: int = 100_000) -> np.ndarray:
    """Predict raw scores in bounded batches; only calibration rows reach this function."""
    outputs = []
    for start in range(0, len(frame), chunk_size):
        features = make_features(frame.iloc[start : start + chunk_size])
        raw = np.clip(model.predict_proba(features)[:, 1], 1e-6, 1 - 1e-6)
        outputs.append(np.log(raw / (1 - raw)))
    if not outputs:
        raise ValueError("calibration partition is empty")
    return np.concatenate(outputs).reshape(-1, 1)


def train(data_path: Path, artifact_dir: Path, report_dir: Path) -> dict:
    if not data_path.is_file():
        raise SystemExit(f"PaySim CSV not found: {data_path}; run scripts/prepare_data.py first")
    source_stat = data_path.stat()
    partitions = load_training_partitions(data_path, max_train_negatives=MAX_TRAIN_NEGATIVES, seed=SEED)
    train_frame = partitions.train
    calibration = partitions.calibration
    audit = partitions.audit

    if train_frame.isFraud.nunique() != 2 or calibration.isFraud.nunique() != 2:
        raise ValueError("training and calibration partitions must each contain both labels")
    sampled_negatives = int((train_frame.isFraud == 0).sum())
    if sampled_negatives > MAX_TRAIN_NEGATIVES:
        raise RuntimeError("negative sample exceeded configured hard cap")

    model = build_model(SEED)
    calibrator = build_calibrator(SEED)
    with threadpool_limits(limits=1):
        model.fit(make_features(train_frame), train_frame.isFraud.to_numpy(dtype=np.int8))
        logits = _calibration_logits(model, calibration)
        calibrator.fit(logits, calibration.isFraud.to_numpy(dtype=np.int8))

    if data_path.stat().st_size != source_stat.st_size or data_path.stat().st_mtime_ns != source_stat.st_mtime_ns:
        raise RuntimeError("source CSV changed during training; artifacts were not written")
    source_hash = sha256_file(data_path)
    model_path = artifact_dir / "model.joblib"
    calibrator_path = artifact_dir / "calibrator.joblib"
    _atomic_joblib(model, model_path)
    _atomic_joblib(calibrator, calibrator_path)
    model_hash = _file_sha256(model_path)
    calibrator_hash = _file_sha256(calibrator_path)
    version_material = hashlib.sha256(f"{model_hash}:{calibrator_hash}".encode("ascii")).hexdigest()
    model_version = f"paysim-lr-{version_material[:16]}"

    metadata = {
        "model_version": model_version,
        "feature_names": FEATURE_NAMES,
        "score_semantics": "calibrated_probability_estimate_with_temporal_drift_warning",
        "model_sha256": model_hash,
        "calibrator_sha256": calibrator_hash,
        "source_sha256": source_hash,
        "training_seed": SEED,
        "train_step_range": [1, 400],
        "calibration_step_range": [401, 470],
    }
    _atomic_json(artifact_dir / "metadata.json", metadata)

    # This report records fit/calibration provenance and row-count audit only.
    # It intentionally contains no selection metrics and no held-out test scores.
    training_report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "trained_and_calibrated; strategy selection and final evaluation not run",
        "dataset": {"path": str(data_path), "sha256": source_hash, "rows": audit["source_rows"]},
        "feature_names": FEATURE_NAMES,
        "excluded_columns": sorted(DENYLIST),
        "partitions": {
            "train": audit["partitions"]["train"],
            "calibration": audit["partitions"]["calibration"],
            "selection_audit_only": audit["partitions"]["selection"],
            "test_audit_only_unopened": audit["partitions"]["test"],
        },
        "training_sample": audit["training_sample"],
        "calibration_method": "logistic regression on clipped base-model logits; calibration window only",
        "rule_candidates": _rule_candidates(train_frame),
        "selection_threshold": None,
        "test_scored": False,
        "test_rows_loaded_into_training_memory": False,
        "model_version": model_version,
        "model_sha256": model_hash,
        "calibrator_sha256": calibrator_hash,
        "source_sha256": source_hash,
        "versions": _versions(),
    }
    _atomic_json(report_dir / "data_audit.json", audit)
    _atomic_json(report_dir / "training.json", training_report)
    return training_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, default=ROOT / "services/ml/artifacts")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    report = train(args.data, args.artifact_dir, args.report_dir)
    print(json.dumps({
        "status": report["status"],
        "model_version": report["model_version"],
        "train_sample_rows": report["training_sample"]["rows"],
        "calibration_rows": report["partitions"]["calibration"]["rows"],
        "selection_rows_audit_only": report["partitions"]["selection_audit_only"]["rows"],
        "test_rows_audit_only_unopened": report["partitions"]["test_audit_only_unopened"]["rows"],
    }, indent=2))


if __name__ == "__main__":
    main()
