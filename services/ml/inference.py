"""Shared inference transform for offline evidence and the private scorer."""
import numpy as np
from .features import make_features


def predict_scores(model, calibrator, rows):
    features = make_features(rows)
    base = np.asarray(model.predict_proba(features))
    if base.shape != (len(features), 2) or not np.isfinite(base).all() or ((base < 0) | (base > 1)).any():
        raise ValueError("invalid base model output")
    raw = np.clip(base[:, 1], 1e-6, 1 - 1e-6)
    calibrated = np.asarray(calibrator.predict_proba(np.log(raw / (1 - raw)).reshape(-1, 1)))
    if calibrated.shape != (len(features), 2):
        raise ValueError("invalid calibrator output shape")
    scores = calibrated[:, 1]
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("invalid model output")
    return scores
