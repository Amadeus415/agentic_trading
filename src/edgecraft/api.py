from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from edgecraft import __version__
from edgecraft.data import MarketDataError, MarketDataProvider, synthetic_market_data
from edgecraft.learning import LearningScenarioRequest, learning_guide, run_learning_scenario
from edgecraft.ledger import AuditLedger
from edgecraft.models import BacktestRequest
from edgecraft.observability import autonomy_health, control_plane_snapshot, prometheus_metrics
from edgecraft.research import run_research
from edgecraft.strategies import STRATEGY_SCHEMAS

app = FastAPI(
    title="Edgecraft API",
    version=__version__,
    description="Point-in-time stock strategy research and adversarial validation.",
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/autonomy/health")
def autonomous_health() -> dict:
    return autonomy_health(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/api/control-plane")
def control_plane() -> dict:
    return control_plane_snapshot(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/api/trades/{order_key}")
def trade_detail(order_key: str) -> dict:
    try:
        return AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")).trade_audit(
            order_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return prometheus_metrics(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/api/strategies")
def strategies() -> list[dict]:
    return STRATEGY_SCHEMAS


@app.get("/api/learn")
def learn() -> dict:
    return learning_guide()


@app.post("/api/learn/scenarios")
def learning_scenario(request: LearningScenarioRequest) -> dict:
    return run_learning_scenario(request)


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
        raise HTTPException(status_code=500, detail="Backtest failed") from exc


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
