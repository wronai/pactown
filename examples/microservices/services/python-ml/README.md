# Python ML Service

Machine learning prediction service using Python. Demonstrates Python service in a polyglot ecosystem.

## Endpoints

- `GET /health` – Health check
- `POST /predict` – Make a prediction
- `GET /model/info` – Model information

---

```python markpact:deps
fastapi
uvicorn
numpy
```

```python markpact:file path=main.py
import os
import random
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ML Prediction Service", version="1.0.0")

class PredictionRequest(BaseModel):
    features: list[float]

class PredictionResponse(BaseModel):
    prediction: float
    confidence: float
    model_version: str

# Simple mock model
MODEL_VERSION = "1.0.0"

def predict(features: list[float]) -> tuple[float, float]:
    """Mock prediction - in real scenario would use sklearn/pytorch."""
    import numpy as np
    arr = np.array(features)
    prediction = float(np.mean(arr) * 2 + np.std(arr))
    confidence = min(0.95, 0.5 + len(features) * 0.05)
    return prediction, confidence

@app.get("/health")
def health():
    return {"status": "ok", "service": "python-ml"}

@app.get("/model/info")
def model_info():
    return {
        "name": "SimplePredictor",
        "version": MODEL_VERSION,
        "framework": "numpy",
        "input_features": "variable",
    }

@app.post("/predict", response_model=PredictionResponse)
def make_prediction(request: PredictionRequest):
    prediction, confidence = predict(request.features)
    return PredictionResponse(
        prediction=prediction,
        confidence=confidence,
        model_version=MODEL_VERSION,
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MARKPACT_PORT", 8010))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

```bash markpact:run
uvicorn main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8010} --reload
```

```http markpact:test
GET /health EXPECT 200
GET /model/info EXPECT 200
POST /predict BODY {"features":[1.0,2.0,3.0]} EXPECT 200
```
