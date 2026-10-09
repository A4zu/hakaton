"""OpenAI inteqrasiyası. Açar yoxdursa, hesablama nəticələrinə əsaslanan qayda-əsaslı cavab verir."""
import json, os, re
from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SYSTEM = ("Sən investorlara kömək edən maliyyə analitikisən. Azərbaycan dilində, sadə və QISA (maksimum 6 cümlə) cavab ver. "
          "QAYDALAR: 1) YALNIZ verilən rəqəmlərdən istifadə et, uydurma, yeni hesablama aparma. "
          "2) Valyuta adı (AZN, USD...) YAZMA, valyuta verilməyib. "
          "3) 'tövsiyə edirəm', 'investisiya etməlisiniz', 'təhlükəsiz', 'risksiz' kimi ifadələr işlətmə: bu, hesablama nəticəsidir, məsləhət deyil. "
          "4) Texniki sahə adlarını (to_safe, default_prob...) yazma, adi dillə de. "
          "5) Z-Score ehtimal vermir, yalnız zona verir; Safe həddinə məsafə azdırsa (<0.5) bunu qeyd et. "
          "6) 0% defolt 'risk yoxdur' demək deyil, yalnız modelin fərziyyələri daxilində belə çıxdığını bildir; ödəniş faizi, defoltda geri qayıtma və dəyişkənlik fərziyyədir, onları adlandır. "
          "7) all_amounts_pass=true isə, bütün məbləğlər tələbi ödədiyi üçün optimal sadəcə yoxlanan ən böyük məbləğdir, bunu açıq de. "
          "8) 'gəlir' sözünü dəqiq işlət: expected_return = geri qayıdan ümumi məbləğ, expected_profit = xalis gəlir, expected_irr = illik gəlirlilik (zamanın dəyəri nəzərə alınıb). "
          "9) İnvestora ödəniş sabit deyil: EBITDA-nın sabit payıdır (share), şirkət yaxşı qazananda çox, pis qazananda az ödəyir. "
          "10) Optimal seçimi NPV-yə görə izah et: daha böyük məbləğ əlavə pulun alternativdə qazanacağından az gəlir gətirdiyi üçün seçilmir (choice_note-dan istifadə et). 11) best=null isə heç bir məbləğ tələbi ödəmir, optimal YOXDUR, bunu açıq de.")
ZONE_AZ = {"safe": "sağlam (Safe)", "grey": "orta (Grey)", "distress": "təhlükə (Distress)"}


def _client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=key)


def _ask(messages):
    c = _client()
    if c is None:
        return None
    try:
        r = c.chat.completions.create(model=MODEL, messages=messages, temperature=0.2)
        return r.choices[0].message.content
    except Exception as e:
        return f"(OpenAI xətası: {e})"


def _compact(res):
    keep = ("amount", "leverage", "excess", "success_prob", "default_prob", "expected_return",
            "expected_profit", "expected_irr", "npv", "share", "p10", "p50", "p90")
    p = res["params"]
    pk = ("min_amount", "max_amount", "step", "years", "min_success", "min_return", "hurdle", "payout_rate", "recovery",
          "max_leverage", "vol", "sector")
    return json.dumps({
        "altman": {k: res["altman"][k] for k in ("z", "zone", "to_safe", "to_distress")},
        "growth": round(res["growth"], 4), "params": {k: p.get(k) for k in pk},
        "selection_rule": "uğur ehtimalı ≥ min_success olanlardan alternativ gəlirə (hurdle) nisbətən ən yüksək NPV; əlavə investisiyanın əlavə gəliri alternativdən azdırsa daha böyük məbləğ seçilmir",
        "choice_note": res.get("choice_note"),
        "best": res["best"], "warnings": res.get("warnings", []),
        "all_amounts_pass": all(r["success_prob"] >= p["min_success"] for r in res["rows"]),
        "best_is_largest_tested": bool(res["best"]) and res["best"]["amount"] == res["rows"][-1]["amount"],
        "volatility_note": p.get("vol_note"),
        "rows": [{k: round(r[k], 4) if isinstance(r[k], float) else r[k] for k in keep} for r in res["rows"]],
    }, ensure_ascii=False)


def _fallback_summary(res):
    a, b, p = res["altman"], res["best"], res["params"]
    s = f"Şirkət {ZONE_AZ[a['zone']]} zonadadır (Z={a['z']}). EBITDA artımı ≈ {res['growth']:.1%}/il. "
    if b:
        s += (f"Optimal məbləğ {b['amount']:,.0f}: uğur ehtimalı {b['success_prob']:.0%}, gözlənilən xalis gəlir "
              f"{b['expected_profit']:,.0f}, defolt ehtimalı {b['default_prob']:.0%}.")
    else:
        s += f"Heç bir məbləğ {p['min_success']:.0%} minimum uğur ehtimalını ödəmir."
    return s + " (Ətraflı AI izahı üçün .env faylına OPENAI_API_KEY əlavə edin.)"


def explain(res):
    return _ask([{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": "Bu nəticəni investora izah et:\n" + _compact(res)}]) or _fallback_summary(res)


def _parse_amount(msg):
    m = re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*([kKmM])?", msg)
    if not m:
        return None
    v = float(m.group(1).replace(" ", "").replace(",", "."))
    return v * {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)


def _fallback_chat(msg, ctx):
    if not ctx:
        return "Əvvəlcə analiz aparılmalıdır."
    p, rows = ctx["params"], ctx["rows"]
    amt = _parse_amount(msg)
    if amt:
        r = min(rows, key=lambda x: abs(x["amount"] - amt))
        why = []
        if r["success_prob"] < p["min_success"]:
            why.append(f"uğur ehtimalı {r['success_prob']:.0%} < tələb olunan {p['min_success']:.0%}")
        if r["excess"] > 0:
            why.append(f"leverage {r['leverage']}x limiti ({p['max_leverage']}x) {r['excess']}x aşır → dəyişkənlik artır")
        verdict = "tələbi ödəyir" if r["success_prob"] >= p["min_success"] else "atıldı"
        best = ctx["best"]
        extra = "" if not best or best["amount"] == r["amount"] else f" Optimal seçim: {best['amount']:,.0f}."
        return (f"{r['amount']:,.0f}: uğur {r['success_prob']:.0%}, defolt {r['default_prob']:.0%}, "
                f"leverage {r['leverage']}x, gözlənilən xalis gəlir {r['expected_profit']:,.0f} → {verdict}"
                + (" (" + "; ".join(why) + ")" if why else "") + "." + extra)
    return _fallback_summary(ctx) + " Konkret məbləğ yazın (məs. \"200K niyə atıldı?\")."


def chat(message, history, ctx):
    msgs = [{"role": "system", "content": SYSTEM + "\nAnaliz nəticəsi:\n" + (_compact(ctx) if ctx else "hələ yoxdur")}]
    msgs += history[-6:] + [{"role": "user", "content": message}]
    return _ask(msgs) or _fallback_chat(message, ctx)
