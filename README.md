# Investor AI (yenidən qurulmuş versiya)

Maliyyə hesabatı (Excel) → Altman Z → Monte Carlo → optimal investisiya məbləği.

## İşə salmaq
```
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY ixtiyaridir; olmasa qayda-əsaslı izah işləyir
uvicorn backend.main:app --reload
# http://localhost:8000
pytest -q tests             # düsturların yoxlanışı (18 test)
```

## Söhbət axını
Data (Excel/nümunə) → çatışmayanlar → **6 sual** (min, max, addım, il, min uğur ehtimalı, min illik gəlir)
→ 3 fərziyyə (ilkin ödəniş faizi, defoltda geri qayıtma, sektor) → hesablama → nəticə → sərbəst sual / parametrləri dəyiş.
Bütün cavablar həm frontend-də, həm backend-də yoxlanılır.

## Qaydalar və koddakı yeri (backend/engine.py)
| Qayda | Funksiya |
|---|---|
| Z = 1.2A+1.4B+3.3C+0.6D+1.0E; >2.99 Safe, 1.81–2.99 Grey, <1.81 Distress | `altman_z` |
| growth = (EBITDA_son/EBITDA_ilk)^(1/n) − 1, n = illər − 1 | `growth_rate` |
| New Leverage = (borc + investisiya)/EBITDA; limiti aşan hissə yalnız dəyişkənliyi artırır | `new_leverage`, `simulate` |
| Limit = Damodaran sektor Debt/EBITDA (2026-01) | `benchmarks.py` |
| 4000 ssenari. Investora ödəniş = EBITDA-nın sabit payı (pis ildə az, yaxşı ildə çox). Defolt: (EBITDA − investora ödəniş) < köhnə borc ödənişi, ssenari dayanır | `cashflows`, `simulate` |
| Gəlir = IRR: −İnvestisiya + Σ Ödəniş(il)/(1+IRR)^il = 0 (zamanın dəyəri nəzərə alınır); IRR ≥ minimum və defolt yoxdursa ssenari uğurlu | `irr`, `simulate` |
| Uğur ehtimalı < minimum olanlar atılır, qalanlardan **alternativə nisbətən ən çox dəyər (NPV)** yaradan məbləğ seçilir | `pick_best` |

## Əvvəlki versiyadan düzəlişlər
- 6 sual indi doğrudan soruşulur (əvvəl yalnız məbləğ soruşulurdu, qalanı sabit idi).
- Məbləğ şəbəkəsi min → max, istifadəçinin addımı ilə qurulur.
- Uydurma "risk %" çıxarıldı: yalnız Z, zona, hədlərə məsafə və amillərin töhfəsi göstərilir.
- Leverage limiti sabit 2.5x əvəzinə Damodaran sektor göstəricisidir (və ya əl ilə rəqəm).
- EBITDA dəyişkənliyi sabit 20% əvəzinə tarixi artımdan qiymətləndirilir (aşağı hədd 10%, yuxarı 50%).
- Bütün məbləğlər EYNİ təsadüfi ədədlərlə simulyasiya olunur (müqayisə küydən azaddır).
- Optimal seçim **xalis gəlirə** (geri qayıdan − investisiya) görə edilir; ümumi geri qayıdan məbləğ böyük investisiyanı həmişə üstün göstərirdi.
- Mənfi/sıfır EBITDA, yanlış parametrlər, çox məbləğ (>100) üçün aydın xəta mesajları.
- Min gəlir heç bir məbləğdə əldə oluna bilmirsə (ssenarilərin 1%-i belə IRR-ə çatmırsa) xəbərdarlıq verilir.
- Nəticədən sonra parametrləri dəyişib yenidən hesablamaq və ya başqa şirkətə keçmək olur.
- Excel parser: dəqiq uyğunluq, `Cost of sales`/`Deferred revenue` kimi yanlış sətirlərin istisnası, azalan il sırasının düzəldilməsi.
- AI açarı olmadıqda "200K niyə atıldı?" kimi suallara hesablama nəticələrinə əsaslanan cavab.

## Optimal məbləğ necə seçilir
Yalnız ən yüksək gəlirə baxmaq yanlışdır: 400K → 430K keçəndə əlavə 30K cəmi 136 əlavə gəlir gətirə bilər, halbuki həmin pul başqa yerdə daha çox qazandırar.
Ona görə hər məbləğ üçün **NPV = Σ gözlənilən_pul_axını(il)/(1+alternativ_gəlir)^il** (investisiya daxil) hesablanır və uğur şərtini ödəyənlərdən ən yüksək NPV seçilir.
Əlavə investisiyanın gətirdiyi əlavə gəlir alternativdən azdırsa, NPV azalır və daha böyük məbləğ seçilmir. Nəticədə "daha böyük X niyə seçilmədi" izahı göstərilir.
- **Alternativ gəlir** (başqa yerdə illik qazanc) soruşulur; standart: minimum gəlirlə eyni.
- Alternativ gəlir artdıqca optimal məbləğ eyni qalır və ya azalır, heç vaxt artmır (test edilir).
- NPV optimal məbləğdə də mənfidirsə, xəbərdarlıq verilir (pulu alternativdə saxlamaq daha sərfəli ola bilər).

## Ödəniş modeli (Variant B)
- Müqavilə bağlananda investora EBITDA-nın sabit payı verilir: **pay = ilkin ödəniş faizi × məbləğ / cari EBITDA**.
  Məsələn, 100 000 investisiya, 12% və EBITDA 180 000 → pay 6.7%. Bu pay bütün il boyu sabit qalır, pul isə EBITDA ilə dəyişir.
- Pay məbləğ artdıqca artır (böyük investisiya şirkətin daha çox qazancını alır). Bu olmasa, böyük məbləğ eyni ödənişi alıb gəliri düşərdi.
- Köhnə borc ödənişi (annual_payment) hər halda sabit qalır; defolt onun üzərində yoxlanılır.
- Defoltda investor həmin ildə ödəniş almır, ildən əvvəl alınanlar + əsas məbləğin geri qayıtma hissəsi (həmin ilin sonunda) hesablanır.
- Gəlirlilik **IRR**-dir (CAGR deyil): hər ilin ödənişi öz vaxtına görə diskontlaşdırılır. Sabit 12% kuponda IRR tam 12% çıxır.

## Bilməli olduqlarınız
- **Ödəniş faizi (12%) və recovery (40%) fərziyyədir**; investisiya razılaşmanıza uyğun dəyişin.
- Z-Score müflisləşmə **ehtimalı** vermir, yalnız zona verir. Bazarda satılmayan şirkətlərdə D üçün kapitalın balans dəyərindən istifadə edilir (orijinal modeldən fərqlidir).
- Damodaran göstəriciləri ABŞ sektor ortalamasıdır; bəzi sektorlarda (REIT, Software (Internet)) aşağı EBITDA-ya görə şişirdilib. Limiti rəqəmlə əl ilə də verə bilərsiniz.
- Excel-də düsturlu xanalar yadda saxlanmış dəyərlə oxunur (faylı Excel-də bir dəfə saxlayın).
