import io, numpy as np, pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient
from backend import engine, benchmarks
from backend.main import app, SAMPLE
from backend.excel_parser import parse_excel

P = dict(min_amount=50000, max_amount=200000, step=15000, years=5, min_success=0.80, min_return=0.06)
client = TestClient(app)


def test_leverage_example_from_spec():
    assert engine.new_leverage(200000, 100000, 100000) == 3          # (200K+100K)/100K = 3x


def test_growth_formula():
    assert engine.growth_rate([100, 110, 121, 133.1, 146.41]) == pytest.approx(0.10, abs=1e-9)


def test_altman_components_and_zones():
    f = dict(SAMPLE)
    z = 1.2*(200000/1500000) + 1.4*(400000/1500000) + 3.3*(250000/1500000) + 0.6*(1200000/800000) + 1.0*(2000000/1500000)
    a = engine.altman_z(f)
    assert a["z"] == round(z, 2) and a["zone"] == "safe" and "risk_pct" not in a
    f.update(ebit=-100000, sales=500000, retained_earnings=-300000, market_equity=100000)
    assert engine.altman_z(f)["zone"] == "distress"


def test_grid_min_max_step():
    g = engine.build_grid(P)
    assert g[0] == 50000 and g[1] == 65000 and g[-1] == 200000 and len(g) == 11


def test_selection_rule_and_common_random_numbers():
    r = engine.analyze(SAMPLE, P)
    assert len(r["rows"]) == 11
    ok = [x for x in r["rows"] if x["success_prob"] >= 0.8]
    assert r["best"] == max(ok, key=lambda x: x["npv"])
    assert all(x["npv"] <= r["best"]["npv"] for x in ok)
    # eyni seed → eyni nəticə
    assert engine.analyze(SAMPLE, P)["rows"] == r["rows"]


def test_leverage_excess_raises_risk():
    f = dict(SAMPLE, debt=500000)
    r = engine.analyze(f, dict(P, max_amount=500000, step=150000, max_leverage=2.5))
    ex = [x for x in r["rows"] if x["excess"] > 0]
    assert ex and ex[-1]["vol"] > ex[0]["vol"] > r["params"]["vol"]
    assert ex[-1]["default_prob"] >= r["rows"][0]["default_prob"]


def test_min_return_unreachable_warns_and_fails():
    r = engine.analyze(SAMPLE, dict(P, min_return=0.90))
    assert r["warnings"] and r["best"] is None and all(x["success_prob"] == 0 for x in r["rows"])


def test_user_table_variant_B_payments_and_default():
    """İstifadəçinin cədvəli: EBITDA payı 10%, köhnə borc ödənişi 90 000, investisiya 100 000."""
    ok = np.array([[190000, 170000, 120000, 150000, 160000]], float)
    cf, d = engine.cashflows(ok, 0.10, 100000, 90000, 0.40)
    assert not d[0]
    assert list(cf[0]) == [-100000, 19000, 17000, 12000, 15000, 16000 + 100000]
    assert engine.irr(cf)[0] == pytest.approx(0.1607, abs=5e-4)            # CAGR 12.35% idi, IRR 16.07%
    bad = np.array([[190000, 170000, 95000, 150000, 160000]], float)       # 3-cü il: 95000−9500 = 85500 < 90000
    cf, d = engine.cashflows(bad, 0.10, 100000, 90000, 0.40)
    assert d[0] and list(cf[0]) == [-100000, 19000, 17000, 40000, 0, 0]    # 2 il ödəniş + 40% recovery 3-cü ilin sonunda


def test_irr_solves_npv_zero_and_fixed_coupon_equals_rate():
    cf = np.array([[-100000, 12000, 12000, 12000, 12000, 112000]], float)
    assert engine.irr(cf)[0] == pytest.approx(0.12, abs=1e-6)             # sabit kupon 12% → IRR tam 12%
    r = engine.irr(np.array([[-100, 30, 50, 70]], float))[0]
    assert sum(c / (1 + r) ** t for t, c in enumerate([-100, 30, 50, 70])) == pytest.approx(0, abs=1e-6)


def test_payments_scale_with_amount_and_float_with_ebitda():
    r = engine.analyze(SAMPLE, dict(P, min_amount=100000, max_amount=100000, step=1000))
    x = r["rows"][0]
    assert x["share"] == pytest.approx(0.12 * 100000 / 180000)            # share = rate × məbləğ / cari EBITDA
    assert x["p90"] > x["p10"]                                             # ödəniş sabit olsaydı P10 = P90 olardı
    det = engine.analyze(SAMPLE, dict(P, min_amount=100000, max_amount=100000, step=1000, base_vol=0.0))["rows"][0]
    assert det["expected_irr"] > 0.12 and det["default_prob"] == 0         # EBITDA artdıqca ödəniş artır → IRR > 12%


def test_default_stops_scenario_and_partial_recovery():
    f = dict(SAMPLE, annual_payment=400000)          # köhnə borc EBITDA-dan çox → hər ssenari 1-ci ildə defolt
    r = engine.analyze(f, P)
    assert all(x["default_prob"] == 1 for x in r["rows"])
    assert r["rows"][0]["expected_return"] == pytest.approx(0.4 * 50000, rel=1e-9)


@pytest.mark.parametrize("bad", [dict(max_amount=1000), dict(step=0), dict(years=0), dict(min_success=0.0),
                                 dict(min_success=80), dict(step=1)])
def test_param_validation(bad):
    with pytest.raises(engine.InputError):
        engine.analyze(SAMPLE, {**P, **bad})


def test_negative_ebitda_rejected():
    with pytest.raises(engine.InputError):
        engine.analyze(dict(SAMPLE, ebitda=[-100, 50, 60]), P)


def test_api_flow_and_sector_benchmark():
    body = {"financials": SAMPLE, "params": {**P, "sector": "Steel"}}
    r = client.post("/api/analyze", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["params"]["max_leverage"] == 2.20 and j["params"]["sector"] == "Steel" and j["summary"]
    bad = client.post("/api/analyze", json={"financials": SAMPLE, "params": {**P, "max_amount": 10}})
    assert bad.status_code == 400
    assert client.get("/api/sectors?q=retail").json()["matches"]
    assert client.get("/").status_code == 200
    c = client.post("/api/chat", json={"message": "200K niyə atıldı?", "history": [], "context": j}).json()["reply"]
    assert "200" in c


def test_excel_parser_traps_and_descending_years():
    wb = Workbook(); ws = wb.active
    rows = [["", 2022, 2021, 2020], ["Cost of sales", 900, 800, 700], ["Revenue", 2000, 1800, 1600],
            ["Deferred revenue", 5, 5, 5], ["EBITDA", 180, 165, 150], ["EBIT", 150, 140, 130],
            ["Total Current Assets", 500, 0, 0], ["Total assets", 1500, 0, 0], ["Total current liabilities", 300, 0, 0],
            ["Total liabilities", 800, 0, 0], ["Total liabilities and equity", 1500, 0, 0],
            ["Retained earnings", 400, 0, 0], ["Market capitalization", 1200, 0, 0],
            ["Total debt", 300, 0, 0], ["Debt service", 90, 0, 0]]
    for r in rows: ws.append(r)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    found, missing, notes = parse_excel(buf)
    assert not missing
    assert found["sales"] == 2000 and found["ebitda"] == [150, 165, 180] and found["total_liabilities"] == 800
    assert found["total_assets"] == 1500 and found["current_assets"] == 500


def test_benchmark_values_match_damodaran():
    assert benchmarks.SECTORS["Steel"] == 2.20 and benchmarks.SECTORS[benchmarks.DEFAULT_SECTOR] == 3.01


def test_csv_upload_sample_matches_builtin_sample():
    raw = open("/mnt/user-data/outputs/numune_sirket.csv", "rb").read()
    r = client.post("/api/upload", files={"file": ("numune_sirket.csv", raw, "text/csv")})
    assert r.status_code == 200
    j = r.json()
    assert j["missing"] == [] and j["found"]["ebitda"] == SAMPLE["ebitda"]
    for k in ("sales", "total_assets", "market_equity", "debt", "annual_payment", "ebit"):
        assert j["found"][k] == SAMPLE[k]
    # nöqtəli-vergül ayırıcı və minlik ayırıcı
    semi = "Göstərici;2022\nRevenue;\"2 000 000\"\nEBITDA;180000\n".encode("utf-8")
    j2 = client.post("/api/upload", files={"file": ("x.csv", semi, "text/csv")}).json()
    assert j2["found"]["sales"] == 2000000
    assert client.post("/api/upload", files={"file": ("x.txt", b"a", "text/plain")}).status_code == 400


def test_user_case_400k_beats_430k_when_extra_profit_is_tiny():
    """İstifadəçinin nümunəsi: 430K yalnız 136 əlavə xalis gəlir verir, amma əlavə 30K alternativdə daha çox qazandırır."""
    rows = [
        dict(amount=400000, success_prob=0.94, npv=0, expected_profit=215088),
        dict(amount=430000, success_prob=0.90, npv=0, expected_profit=215224),
    ]
    h, n = 0.06, 5
    # NPV = (gözlənilən xalis gəlirin cari dəyəri) − alternativdə qazanılacaq; sadə yaxınlaşma ilə yoxlama:
    for r in rows:
        r["npv"] = r["expected_profit"] - r["amount"] * ((1 + h) ** n - 1)
    assert rows[1]["expected_profit"] > rows[0]["expected_profit"]       # köhnə qayda 430K seçərdi
    assert engine.pick_best(rows, 0.80)["amount"] == 400000              # yeni qayda 400K seçir
    note = engine.explain_choice(rows[0], rows, 0.80)
    assert note["extra_amount"] == 30000 and note["extra_profit"] == 136 and note["extra_npv"] < 0


def test_higher_alternative_return_never_picks_larger_amount():
    base = dict(P, min_amount=100000, max_amount=1000000, step=100000, min_return=0.06)
    lo = engine.analyze(SAMPLE, dict(base, alt_return=0.0))["best"]["amount"]
    mid = engine.analyze(SAMPLE, dict(base, alt_return=0.10))["best"]["amount"]
    hi = engine.analyze(SAMPLE, dict(base, alt_return=0.20))["best"]
    assert lo >= mid and (hi is None or hi["amount"] <= mid)


def test_default_alt_return_equals_min_return_and_validation():
    r = engine.analyze(SAMPLE, P)
    assert r["params"]["hurdle"] == P["min_return"]
    with pytest.raises(engine.InputError):
        engine.analyze(SAMPLE, dict(P, alt_return=1.5))
    # alt_return = 0 → NPV = ümumi xalis gəlir (diskont yoxdur)
    z = engine.analyze(SAMPLE, dict(P, alt_return=0.0))["rows"][0]
    assert z["npv"] == pytest.approx(z["expected_profit"], rel=1e-9)
