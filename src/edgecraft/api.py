from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from edgecraft import __version__
from edgecraft.data import MarketDataError, MarketDataProvider, synthetic_market_data
from edgecraft.ledger import AuditLedger
from edgecraft.models import BacktestRequest
from edgecraft.observability import autonomy_health, prometheus_metrics
from edgecraft.research import run_research
from edgecraft.strategies import STRATEGY_SCHEMAS

app = FastAPI(
    title="Edgecraft API",
    version=__version__,
    description="Point-in-time stock strategy research and adversarial validation.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/autonomy/health")
def autonomous_health() -> dict:
    return autonomy_health(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return prometheus_metrics(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/api/strategies")
def strategies() -> list[dict]:
    return STRATEGY_SCHEMAS


@app.post("/api/backtests")
def backtests(
    request: BacktestRequest,
    data_source: str = Query("market", pattern="^(market|synthetic)$"),
) -> dict:
    try:
        if data_source == "synthetic":
            data = synthetic_market_data(
                request.symbols, periods=1_500, seed=request.validation.random_seed
            )
        else:
            data = MarketDataProvider().load(
                request.symbols,
                request.start.isoformat(),
                request.end.isoformat(),
            )
        return run_research(data, request)
    except (ValueError, MarketDataError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if os.getenv("EDGECRAFT_DEBUG") == "1":
            raise
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}") from exc


frontend_dist = Path(__file__).resolve().parents[2] / "frontend"
if (frontend_dist / "index.html").exists():

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = frontend_dist / ("src/styles.css" if path == "styles.css" else path)
        if path in {"app.js", "styles.css"} and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("edgecraft.api:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
