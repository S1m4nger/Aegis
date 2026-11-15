"""Internal inference only. Artifacts are trusted local outputs, never uploads."""
from contextlib import asynccontextmanager
import hashlib
import io
import json
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .features import FEATURE_NAMES, TYPES
from .inference import predict_scores

ART = Path(__file__).parent / "artifacts"


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int = Field(strict=True, gt=0, le=1_000_000)
    type: str
    amount: float = Field(strict=True, ge=0, le=1e12, allow_inf_nan=False)

    @field_validator("type")
    @classmethod
    def check_type(cls, value):
        if value not in TYPES:
            raise ValueError("unknown transaction type")
        return value


@asynccontextmanager
async def lifespan(application):
    application.state.bundle = None
    try:
        metadata = json.loads((ART / "metadata.json").read_text(encoding="utf8"))
        if metadata["feature_names"] != FEATURE_NAMES:
            raise ValueError("incompatible feature schema")
        artifacts = {}
        for name in ("model", "calibrator"):
            content = (ART / f"{name}.joblib").read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != metadata[f"{name}_sha256"]:
                raise ValueError("artifact checksum mismatch")
            artifacts[name] = content
        model = joblib.load(io.BytesIO(artifacts["model"]))
        calibrator = joblib.load(io.BytesIO(artifacts["calibrator"]))
        predict_scores(model, calibrator, [{"step": 1, "type": "TRANSFER", "amount": 1.0}])
        if not metadata["model_version"] or not metadata["score_semantics"]:
            raise ValueError("missing artifact provenance")
        application.state.bundle = (model, calibrator, metadata)
    except (OSError, ValueError, KeyError, EOFError, TypeError):
        # Fail readiness without exposing artifact paths or substituting a score.
        application.state.bundle = None
    yield
    application.state.bundle = None


app = FastAPI(title="Aegis internal ML scorer", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


def bundle():
    value = getattr(app.state, "bundle", None)
    if value is None:
        raise HTTPException(status_code=503, detail="model not ready")
    return value


@app.get("/health/ready")
def ready():
    _, _, metadata = bundle()
    return {"ready": True, "model_version": metadata["model_version"]}


@app.post("/internal/v1/score")
def score(tx: Transaction):
    model, calibrator, metadata = bundle()
    try:
        value = float(predict_scores(model, calibrator, [tx.model_dump()])[0])
    except (ValueError, TypeError):
        raise HTTPException(status_code=503, detail="scoring unavailable") from None
    return {"score": value, "model_version": metadata["model_version"],
            "score_semantics": metadata["score_semantics"]}
