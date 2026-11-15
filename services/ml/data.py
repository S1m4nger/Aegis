"""Strict, bounded-memory PaySim audit and chronological training partitions."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .features import MAX_AMOUNT, TYPES

EXPECTED_COLUMNS = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud",
]
READ_COLUMNS = ["step", "type", "amount", "isFraud"]
CHUNK_ROWS = 250_000
TRAIN_MAX_STEP = 400
CALIBRATION_MAX_STEP = 470
SELECTION_MAX_STEP = 550
MAX_STEP = 743
MAX_TRAIN_NEGATIVES = 200_000
SEED = 42

PARTITIONS = ("train", "calibration", "selection", "test")


@dataclass
class Partitions:
    train: pd.DataFrame
    calibration: pd.DataFrame
    audit: dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_header(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
    except (OSError, UnicodeError, StopIteration, csv.Error) as exc:
        raise ValueError(f"cannot read PaySim CSV header: {exc}") from exc
    if header != EXPECTED_COLUMNS:
        raise ValueError(f"unexpected PaySim schema: expected {EXPECTED_COLUMNS}, got {header}")


def _partition_name(step: int) -> str:
    if step <= TRAIN_MAX_STEP:
        return "train"
    if step <= CALIBRATION_MAX_STEP:
        return "calibration"
    if step <= SELECTION_MAX_STEP:
        return "selection"
    return "test"


def _read_chunks(path: Path):
    return pd.read_csv(
        path,
        usecols=READ_COLUMNS,
        dtype={"step": "int64", "type": "string", "amount": "float64", "isFraud": "int64"},
        chunksize=CHUNK_ROWS,
        on_bad_lines="error",
    )


def audit_source(path: Path) -> dict:
    """Validate the entire source while retaining counts only, including held-out test."""
    _check_header(path)
    counts = {
        name: {"rows": 0, "frauds": 0, "legitimate": 0, "types": {kind: 0 for kind in sorted(TYPES)}}
        for name in PARTITIONS
    }
    step_min, step_max, total = None, None, 0
    negative_counts = []
    for chunk_number, chunk in enumerate(_read_chunks(path), start=1):
        if chunk[READ_COLUMNS].isna().any().any():
            raise ValueError(f"missing required value in CSV chunk {chunk_number}")
        if not chunk["type"].isin(TYPES).all():
            raise ValueError(f"unknown transaction type in CSV chunk {chunk_number}")
        if not chunk["isFraud"].isin([0, 1]).all():
            raise ValueError(f"isFraud must be binary in CSV chunk {chunk_number}")
        if ((chunk["step"] < 1) | (chunk["step"] > MAX_STEP)).any():
            raise ValueError(f"step must be in [1, {MAX_STEP}] in CSV chunk {chunk_number}")
        if ((~np.isfinite(chunk["amount"])) | (chunk["amount"] < 0) | (chunk["amount"] > MAX_AMOUNT)).any():
            raise ValueError(f"amount must be finite and in [0, {MAX_AMOUNT}] in CSV chunk {chunk_number}")

        step_min = int(chunk.step.min()) if step_min is None else min(step_min, int(chunk.step.min()))
        step_max = int(chunk.step.max()) if step_max is None else max(step_max, int(chunk.step.max()))
        total += len(chunk)
        negative_counts.append(int(((chunk["step"] <= TRAIN_MAX_STEP) & (chunk["isFraud"] == 0)).sum()))
        # Accumulate per-window and transaction-type counts without retaining source rows.
        labels = chunk["isFraud"].to_numpy()
        steps = chunk["step"].to_numpy()
        types = chunk["type"].to_numpy()
        for name in PARTITIONS:
            if name == "train":
                mask = steps <= TRAIN_MAX_STEP
            elif name == "calibration":
                mask = (steps > TRAIN_MAX_STEP) & (steps <= CALIBRATION_MAX_STEP)
            elif name == "selection":
                mask = (steps > CALIBRATION_MAX_STEP) & (steps <= SELECTION_MAX_STEP)
            else:
                mask = steps > SELECTION_MAX_STEP
            selected = int(mask.sum())
            frauds = int(labels[mask].sum())
            counts[name]["rows"] += selected
            counts[name]["frauds"] += frauds
            counts[name]["legitimate"] += selected - frauds
            if selected:
                unique, type_counts = np.unique(types[mask], return_counts=True)
                for kind, type_count in zip(unique, type_counts):
                    counts[name]["types"][str(kind)] += int(type_count)

    if total == 0:
        raise ValueError("PaySim CSV contains no data rows")
    for name in PARTITIONS:
        if counts[name]["rows"] == 0:
            raise ValueError(f"chronological partition {name} is empty")
        if counts[name]["frauds"] == 0 or counts[name]["legitimate"] == 0:
            raise ValueError(f"chronological partition {name} must contain both labels")
    return {
        "schema": EXPECTED_COLUMNS,
        "model_input_columns": READ_COLUMNS,
        "feature_columns": ["type", "amount_log", "hour"],
        "excluded_columns": ["isFraud is target-only", "isFlaggedFraud", "oldbalanceOrg", "newbalanceOrig",
                             "oldbalanceDest", "newbalanceDest", "nameOrig", "nameDest"],
        "source_rows": total,
        "step_min": step_min,
        "step_max": step_max,
        "partitions": counts,
        "held_out_test_retained_as_partition": False,
        "final_test_predictions_computed": False,
        "_negative_counts_per_chunk": negative_counts,
    }


def _allocate_quotas(negative_counts: list[int], cap: int) -> list[int]:
    total = sum(negative_counts)
    target = min(total, cap)
    if target == 0:
        return [0] * len(negative_counts)
    exact = [count * target / total for count in negative_counts]
    quotas = [min(count, int(value)) for count, value in zip(negative_counts, exact)]
    remainder = target - sum(quotas)
    order = sorted(range(len(negative_counts)), key=lambda i: (exact[i] - quotas[i], negative_counts[i]), reverse=True)
    for index in order:
        if remainder == 0:
            break
        if quotas[index] < negative_counts[index]:
            quotas[index] += 1
            remainder -= 1
    if remainder:
        raise RuntimeError("could not allocate bounded negative sampling quotas")
    return quotas


def load_training_partitions(path: Path, *, max_train_negatives: int = MAX_TRAIN_NEGATIVES, seed: int = SEED) -> Partitions:
    """Audit all windows, then materialize only fit and calibration rows."""
    if not 0 <= max_train_negatives <= MAX_TRAIN_NEGATIVES:
        raise ValueError(f"max_train_negatives must be between 0 and {MAX_TRAIN_NEGATIVES}")
    audit = audit_source(path)

    # Counts from the audit pass assign exact deterministic quotas per CSV chunk.
    negative_counts = audit.pop("_negative_counts_per_chunk")
    quotas = _allocate_quotas(negative_counts, max_train_negatives)

    train_parts, calibration_parts = [], []
    for chunk_index, chunk in enumerate(_read_chunks(path)):
        train_mask = chunk.step <= TRAIN_MAX_STEP
        calibration_mask = (chunk.step > TRAIN_MAX_STEP) & (chunk.step <= CALIBRATION_MAX_STEP)
        positives = chunk.loc[train_mask & (chunk.isFraud == 1), READ_COLUMNS]
        negatives = chunk.loc[train_mask & (chunk.isFraud == 0), READ_COLUMNS]
        quota = quotas[chunk_index]
        if quota:
            negatives = negatives.sample(n=quota, random_state=seed + chunk_index)
        else:
            negatives = negatives.iloc[0:0]
        if not positives.empty or not negatives.empty:
            train_parts.append(pd.concat([positives, negatives], ignore_index=True))
        calibration = chunk.loc[calibration_mask, READ_COLUMNS]
        if not calibration.empty:
            calibration_parts.append(calibration)
        # Selection and held-out test are counted during audit only, never retained.

    train = pd.concat(train_parts, ignore_index=True)
    calibration = pd.concat(calibration_parts, ignore_index=True)
    sampled_negatives = int((train.isFraud == 0).sum())
    if sampled_negatives > MAX_TRAIN_NEGATIVES:
        raise RuntimeError("negative sample exceeded the hard cap")
    if int((train.isFraud == 1).sum()) != audit["partitions"]["train"]["frauds"]:
        raise RuntimeError("training positives differ from first-pass audit")
    expected = audit["partitions"]["calibration"]
    if len(calibration) != expected["rows"] or int(calibration.isFraud.sum()) != expected["frauds"]:
        raise RuntimeError("calibration rows differ from first-pass audit")
    audit["training_sample"] = {
        "rows": len(train),
        "frauds": int(train.isFraud.sum()),
        "legitimate_sampled": sampled_negatives,
        "legitimate_source": audit["partitions"]["train"]["legitimate"],
        "legitimate_sampling_fraction": sampled_negatives / audit["partitions"]["train"]["legitimate"],
        "seed": seed,
        "negative_cap": MAX_TRAIN_NEGATIVES,
    }
    return Partitions(train=train, calibration=calibration, audit=audit)
