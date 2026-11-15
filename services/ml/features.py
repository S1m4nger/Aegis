"""Pure feature conversion: training and live inference use this exact function."""
import numpy as np
import pandas as pd

TYPES = {"CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"}
FEATURE_NAMES = ["type", "amount_log", "hour"]
MAX_AMOUNT = 1e12
MAX_STEP = 1_000_000
DENYLIST = {"isFraud", "isFlaggedFraud", "nameOrig", "nameDest", "oldbalanceOrg",
            "newbalanceOrig", "oldbalanceDest", "newbalanceDest"}


def make_features(data):
    """Return ONLY preapproved columns. Never pass full raw CSV directly to a model."""
    df = pd.DataFrame(data).copy()
    for col in ("type", "amount", "step"):
        if col not in df:
            raise ValueError(f"missing feature {col}")
    if not set(df["type"].astype(str)).issubset(TYPES):
        raise ValueError("unknown transaction type")
    amount = pd.to_numeric(df["amount"], errors="raise")
    steps = pd.to_numeric(df["step"], errors="raise")
    if not np.isfinite(amount).all() or not np.isfinite(steps).all():
        raise ValueError("nonfinite transaction value")
    if ((amount < 0) | (amount > MAX_AMOUNT)).any() or (steps < 1).any() or (steps > MAX_STEP).any() or (steps != np.floor(steps)).any():
        raise ValueError("invalid numeric transaction value")
    return pd.DataFrame({
        "type": df["type"].astype(str),
        "amount_log": np.log1p(amount.astype("float64")),
        "hour": ((steps.astype("int64") - 1) % 24).astype("int64"),
    }, index=df.index)[FEATURE_NAMES]
