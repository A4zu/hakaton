import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import benchmarks, engine, llm
from .excel_parser import parse_csv, parse_excel

app = FastAPI(title="Investor AI")

SAMPLE = dict(current_assets=500000, current_liabilities=300000, total_assets=1500000,
              total_liabilities=800000, retained_earnings=400000, ebit=250000, sales=2000000,
              market_equity=1200000, ebitda=[120000, 135000, 150000, 165000, 180000],
              debt=300000, annual_payment=90000)


class Params(BaseModel):
    min_amount: float
    max_amount: float
    step: float
    years: int
    min_success: float          # 0..1
    min_return: float           # 0..1
    payout_rate: Optional[float] = None
    alt_return: Optional[float] = None
    recovery: Optional[float] = None
    max_leverage: Optional[float] = None
    sector: Optional[str] = None


class AnalyzeReq(BaseModel):
    financials: Dict[str, Any]
    params: Params


class ChatReq(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    context: Optional[Dict[str, Any]] = None


@app.get("/api/sample")
def sample():
    return SAMPLE


@app.get("/api/sectors")
def sectors(q: str = ""):
    return {"default": {"name": benchmarks.DEFAULT_SECTOR, "debt_to_ebitda": benchmarks.SECTORS[benchmarks.DEFAULT_SECTOR]},
            "matches": benchmarks.find_sectors(q)}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Yalnız .xlsx və ya .csv faylı yükləyin")
    try:
        raw = await file.read()
        found, missing, notes = parse_csv(raw) if name.endswith(".csv") else parse_excel(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(400, f"Fayl oxunmadı: {e}")
    return {"found": found, "missing": missing, "notes": notes}


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    params = req.params.model_dump()
    sector = params.pop("sector", None)
    if params.get("max_leverage") is None:  # sektor adı verilibsə, benchmark-dan götür
        name = sector or benchmarks.DEFAULT_SECTOR
        params["max_leverage"] = benchmarks.SECTORS.get(name, benchmarks.SECTORS[benchmarks.DEFAULT_SECTOR])
        sector = name if name in benchmarks.SECTORS else benchmarks.DEFAULT_SECTOR
    try:
        res = engine.analyze(req.financials, params)
    except engine.InputError as e:
        raise HTTPException(400, str(e))
    except (KeyError, TypeError, ZeroDivisionError) as e:
        raise HTTPException(400, f"Çatışmayan və ya yanlış göstərici: {e}")
    res["params"]["sector"] = sector
    res["summary"] = llm.explain(res)
    return res


@app.post("/api/chat")
def chat(req: ChatReq):
    return {"reply": llm.chat(req.message, req.history, req.context)}


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="ui")
