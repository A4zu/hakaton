"""Hesablama mühərriki: Altman Z, growth rate, leverage, Monte Carlo, optimal məbləğ.

Hər addım istifadəçinin təsvir etdiyi qaydalara uyğundur (bax README → "Qaydalar").
"""
import math
import numpy as np

REQUIRED = ["current_assets", "current_liabilities", "total_assets", "total_liabilities",
            "retained_earnings", "ebit", "ebitda", "sales", "market_equity", "debt", "annual_payment"]

# Fərziyyələr (istifadəçiyə göstərilir və dəyişdirilə bilir)
DEFAULTS = dict(
    payout_rate=0.12,   # cari EBITDA səviyyəsində investora illik ödəniş (investisiyanın %-i); real ödəniş EBITDA ilə dəyişir
    recovery=0.40,      # defoltda əsas məbləğdən geri qayıdan hissə
    max_leverage=3.01,  # sektor limiti (Damodaran Debt/EBITDA; default: maliyyəsiz ümumi bazar)
    base_vol=None,      # None → EBITDA-nın tarixi illik artım dəyişkənliyindən qiymətləndirilir
    lev_penalty=2.0,    # limiti aşan hər 100% əlavə leverage dəyişkənliyi neçə dəfə artırır
    alt_return=None,    # əlavə pulu başqa yerdə qazana biləcəyiniz illik gəlir (None → minimum gəlirlə eyni)
    sims=4000,
    seed=42,
)
VOL_FLOOR, VOL_CAP, VOL_DEFAULT = 0.10, 0.50, 0.20
MAX_GRID = 100


class InputError(ValueError):
    """İstifadəçiyə göstərilə bilən giriş xətası."""


# ───────────── Yoxlamalar ─────────────
def validate_financials(f):
    miss = [k for k in REQUIRED if k not in f or f[k] is None]
    if miss:
        raise InputError(f"Çatışmayan göstəricilər: {', '.join(miss)}")
    eb = f["ebitda"]
    if not isinstance(eb, (list, tuple)) or len(eb) < 2:
        raise InputError("Ən azı 2 illik EBITDA lazımdır.")
    if eb[0] <= 0 or eb[-1] <= 0:
        raise InputError("Growth rate üçün ilk və son ilin EBITDA-sı müsbət olmalıdır "
                         "(mənfi/sıfır EBITDA ilə (son/ilk)^(1/n) hesablanmır).")
    if f["total_assets"] <= 0 or f["total_liabilities"] <= 0:
        raise InputError("Cəmi aktivlər və cəmi öhdəliklər müsbət olmalıdır.")
    if f["debt"] < 0 or f["annual_payment"] < 0:
        raise InputError("Borc və illik ödəniş mənfi ola bilməz.")


def validate_params(p):
    for k in ("min_amount", "max_amount", "step", "years", "min_success", "min_return"):
        if p.get(k) is None:
            raise InputError(f"'{k}' daxil edilməyib.")
    if p["min_amount"] <= 0 or p["step"] <= 0:
        raise InputError("Minimum məbləğ və addım müsbət olmalıdır.")
    if p["max_amount"] < p["min_amount"]:
        raise InputError("Maksimum məbləğ minimumdan kiçik ola bilməz.")
    if int(p["years"]) != p["years"] or not 1 <= p["years"] <= 30:
        raise InputError("İl sayı 1–30 arasında tam ədəd olmalıdır.")
    if not 0 < p["min_success"] <= 1:
        raise InputError("Minimum uğur ehtimalı 0–100% arasında olmalıdır.")
    if not 0 <= p["min_return"] < 1:
        raise InputError("Minimum illik gəlir 0–100% arasında olmalıdır.")
    if not 0 < p["payout_rate"] < 1 or not 0 <= p["recovery"] <= 1:
        raise InputError("Ödəniş və geri qayıtma faizləri düzgün deyil.")
    if p.get("alt_return") is not None and not 0 <= p["alt_return"] < 1:
        raise InputError("Alternativ gəlir 0–100% arasında olmalıdır.")
    if p["max_leverage"] <= 0:
        raise InputError("Leverage limiti müsbət olmalıdır.")
    if n_grid(p) > MAX_GRID:
        raise InputError(f"Çox məbləğ ({n_grid(p)}) alınır; addımı artırın (maksimum {MAX_GRID} məbləğ).")


# ───────────── Hissə 1: Altman Z ─────────────
def altman_z(f):
    ta, tl = f["total_assets"], f["total_liabilities"]
    parts = [
        ("A", "(Cari aktivlər − Cari öhdəliklər) / Cəmi aktivlər", 1.2, (f["current_assets"] - f["current_liabilities"]) / ta),
        ("B", "Bölünməmiş mənfəət / Cəmi aktivlər", 1.4, f["retained_earnings"] / ta),
        ("C", "EBIT / Cəmi aktivlər", 3.3, f["ebit"] / ta),
        ("D", "Kapitalın bazar dəyəri / Cəmi öhdəliklər", 0.6, f["market_equity"] / tl),
        ("E", "Satışlar / Cəmi aktivlər", 1.0, f["sales"] / ta),
    ]
    z = sum(w * r for _, _, w, r in parts)
    zone = "safe" if z > 2.99 else "grey" if z >= 1.81 else "distress"
    return {"z": round(z, 2), "zone": zone,
            "to_safe": round(z - 2.99, 2),       # + → Safe həddindən yuxarı
            "to_distress": round(z - 1.81, 2),   # − → Distress zonasında
            "components": [{"id": i, "name": n, "weight": w, "ratio": round(r, 4), "contribution": round(w * r, 3)}
                           for i, n, w, r in parts]}


# ───────────── Hissə 2: growth ─────────────
def growth_rate(ebitda):
    n = len(ebitda) - 1
    return (ebitda[-1] / ebitda[0]) ** (1 / n) - 1


def estimate_vol(ebitda):
    """EBITDA illik artım tempinin tarixi standart sapması (az data → aşağı limitlə qorunur)."""
    yoy = [b / a - 1 for a, b in zip(ebitda, ebitda[1:]) if a > 0]
    if len(yoy) < 3:
        return VOL_DEFAULT, "default (data az)"
    s = float(np.std(yoy, ddof=1))
    return min(max(s, VOL_FLOOR), VOL_CAP), f"tarixi {s:.1%} → [{VOL_FLOOR:.0%}, {VOL_CAP:.0%}] aralığına salındı"


# ───────────── Hissə 3: leverage ─────────────
def new_leverage(debt, amount, ebitda_last):
    return (debt + amount) / ebitda_last


def n_grid(p):
    return int(math.floor((p["max_amount"] - p["min_amount"]) / p["step"] + 1e-9)) + 1


def build_grid(p):
    return [round(p["min_amount"] + i * p["step"], 2) for i in range(n_grid(p))]


# ───────────── Hissə 4: simulyasiya ─────────────
def cashflows(paths, share, amount, existing, recovery):
    """Hər ssenari üçün investorun pul axını (S × (n+1)); sütun 0 = −investisiya.

    Ödəniş(il) = share × EBITDA(il)  → pis ildə az, yaxşı ildə çox.
    Defolt: investora ödənişdən SONRA qalan pul köhnə borc ödənişinə çatmırsa
    (DSCR = (EBITDA − investora ödəniş) / köhnə ödəniş < 1). O il ödəniş olmur, ssenari dayanır,
    investor əsas məbləğin `recovery` hissəsini həmin ilin sonunda alır.
    """
    S, n = paths.shape
    pay = share * paths
    bad = (paths - pay) < existing
    dflt = bad.any(axis=1)
    first = np.where(dflt, bad.argmax(axis=1), n)            # defolt ilinin indeksi (0-dan) və ya n
    paid = np.arange(n)[None, :] < first[:, None]            # tam ödənilmiş illər
    cf = np.zeros((S, n + 1))
    cf[:, 0] = -amount
    cf[:, 1:] = np.where(paid, pay, 0.0)
    rec_t = np.where(dflt, first + 1, n)                     # əsas məbləğin qayıtma ili
    cf[np.arange(S), rec_t] += np.where(dflt, recovery * amount, amount)
    return cf, dflt


def irr(cf, lo=-0.999, hi=10.0, iters=80):
    """IRR: −A + Σ cf_t/(1+r)^t = 0 (vektorlaşdırılmış bisection; NPV r-in azalan funksiyasıdır)."""
    cf = np.atleast_2d(cf)
    t = np.arange(cf.shape[1])
    lo = np.full(cf.shape[0], lo)
    hi = np.full(cf.shape[0], hi)
    for _ in range(iters):
        mid = (lo + hi) / 2
        pos = (cf / (1 + mid)[:, None] ** t).sum(axis=1) > 0
        lo, hi = np.where(pos, mid, lo), np.where(pos, hi, mid)
    return (lo + hi) / 2


def simulate(f, amount, p, noise):
    g, e0 = growth_rate(f["ebitda"]), f["ebitda"][-1]
    lev = new_leverage(f["debt"], amount, e0)
    exc = max(0.0, lev - p["max_leverage"])                       # limiti aşan hissə
    sig = p["vol"] * (1 + p["lev_penalty"] * exc / p["max_leverage"])  # aşma yalnız dəyişkənliyi artırır
    n = int(p["years"])
    factors = np.maximum(1 + g + sig * noise[:, :n], 0.0)          # EBITDA mənfiyə düşməsin
    paths = e0 * np.cumprod(factors, axis=1)
    share = p["payout_rate"] * amount / e0                          # EBITDA-nın investor payı (müqavilə bağlananda sabitlənir)
    cf, dflt = cashflows(paths, share, amount, f["annual_payment"], p["recovery"])
    r = irr(cf)
    ok = (~dflt) & (r >= p["min_return"])
    total = cf[:, 1:].sum(axis=1)                                   # investorun aldığı ümumi pul
    p10, p50, p90 = np.percentile(total, [10, 50, 90])
    mean = float(total.mean())
    mean_cf = cf.mean(axis=0)
    npv = float((mean_cf / (1 + p["hurdle"]) ** np.arange(n + 1)).sum())   # alternativ gəlirlə diskontlanmış gözlənilən xalis dəyər
    return {"amount": amount, "leverage": round(lev, 2), "excess": round(exc, 2), "vol": round(sig, 3),
            "share": float(share), "success_prob": float(ok.mean()), "default_prob": float(dflt.mean()),
            "irr_hit_prob": float((r >= p["min_return"]).mean()),
            "expected_return": mean, "expected_profit": mean - amount,
            "expected_irr": float(irr(mean_cf)[0]), "npv": npv,
            "p10": float(p10), "p50": float(p50), "p90": float(p90)}


def pick_best(rows, min_success):
    """Uğur ehtimalı minimumu ödəyənlər arasında alternativə nisbətən ən çox dəyər (NPV) yaradan məbləğ.

    NPV = Σ gözlənilən_pul_axını(il) / (1+alt_gəlir)^il − investisiya. Əlavə investisiyanın gətirdiyi əlavə gəlir
    həmin pulun alternativdə qazanacağından azdırsa, NPV azalır və daha böyük məbləğ seçilmir.
    """
    valid = [r for r in rows if r["success_prob"] >= min_success]
    return max(valid, key=lambda r: r["npv"]) if valid else None


def explain_choice(best, rows, min_success):
    """Optimaldan bir pillə böyük (uğur şərtini ödəyən) məbləğ niyə seçilmədi."""
    bigger = [r for r in rows if r["amount"] > best["amount"] and r["success_prob"] >= min_success]
    if not bigger:
        return None
    nxt = min(bigger, key=lambda r: r["amount"])
    return {"next_amount": nxt["amount"], "extra_amount": nxt["amount"] - best["amount"],
            "extra_profit": nxt["expected_profit"] - best["expected_profit"], "extra_npv": nxt["npv"] - best["npv"]}


def analyze(f, params):
    validate_financials(f)
    p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    validate_params(p)
    if p["base_vol"] is None:
        p["vol"], p["vol_note"] = estimate_vol(f["ebitda"])
    else:
        p["vol"], p["vol_note"] = float(p["base_vol"]), "istifadəçi"
    p["hurdle"] = p["alt_return"] if p["alt_return"] is not None else p["min_return"]
    n, S = int(p["years"]), int(p["sims"])
    rng = np.random.default_rng(int(p["seed"]))
    noise = rng.standard_normal((S, n))  # EYNİ təsadüfi ədədlər bütün məbləğlər üçün → ədalətli müqayisə
    rows = [simulate(f, a, p, noise) for a in build_grid(p)]
    best = pick_best(rows, p["min_success"])

    warnings = []
    if max(r["irr_hit_prob"] for r in rows) < 0.01:
        warnings.append(f"Minimum gəlir ({p['min_return']:.1%}) çox yüksəkdir: heç bir məbləğdə ssenarilərin 1%-i belə bu IRR-i vermir. "
                        "Minimum gəliri azaldın və ya ödəniş faizini artırın.")
    if any(r["share"] > 0.5 for r in rows):
        warnings.append("Bəzi məbləğlərdə investora EBITDA-nın 50%-dən çoxu düşür; bu, şirkət üçün real deyil və defolt riskini artırır.")
    if best and best["npv"] < 0:
        warnings.append(f"Optimal məbləğdə belə gözlənilən gəlir alternativdən ({p['hurdle']:.1%}/il) zəifdir (NPV mənfi): pulu alternativdə saxlamaq daha sərfəli ola bilər.")
    if all(r["excess"] == 0 for r in rows):
        warnings.append(f"Heç bir məbləğ leverage limitini ({p['max_leverage']}x) aşmır, ona görə leverage cəriməsi işləmədi.")
    return {"altman": altman_z(f), "growth": growth_rate(f["ebitda"]), "rows": rows, "best": best,
            "choice_note": explain_choice(best, rows, p["min_success"]) if best else None,
            "params": p, "warnings": warnings}
