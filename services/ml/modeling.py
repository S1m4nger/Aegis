"""Model and calibration utilities for the chronological PaySim baseline."""
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression


def build_model(seed=42):
    features = ColumnTransformer([
        ("type", OneHotEncoder(handle_unknown="ignore"), ["type"]),
        ("numeric", StandardScaler(), ["amount_log", "hour"]),
    ])
    return Pipeline([
        ("features", features),
        ("classifier", LogisticRegression(max_iter=500, class_weight="balanced", random_state=seed)),
    ])


def build_calibrator(seed=42):
    """Fit this logistic score mapping only on the independent calibration window."""
    return LogisticRegression(max_iter=500, random_state=seed)
