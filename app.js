const $ = s => document.querySelector(s), log = $('#log'), inp = $('#in');
const LBL = {current_assets:'Cari aktivlər', current_liabilities:'Cari öhdəliklər', total_assets:'Cəmi aktivlər',
  total_liabilities:'Cəmi öhdəliklər', retained_earnings:'Bölünməmiş mənfəət', ebit:'EBIT', sales:'Satışlar',
  market_equity:'Kapitalın bazar dəyəri (xüsusi şirkətdə kapitalın balans dəyəri)', debt:'Mövcud borc',
  annual_payment:'Mövcud illik borc ödənişi',
  ebitda:'EBITDA illər üzrə (köhnədən yeniyə, boşluqla ayırın: 120000 135000 150000)'};
const S = {fin:{}, missing:[], mode:'idle', qi:0, p:{}, ctx:null, hist:[]};
const fmt = n => Math.round(n).toLocaleString('en-US').replace(/,/g, ' ');
const pc = (x, d = 0) => (x * 100).toFixed(d) + '%';
const hm = () => new Date().toLocaleTimeString('az', {hour:'2-digit', minute:'2-digit'});
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function bot(html, qr) {
  const r = document.createElement('div'); r.className = 'row';
  r.innerHTML = `<div class="av">🤖</div><div class="b">${html}<span class="t">${hm()}</span></div>`;
  log.append(r);
  if (qr) { const q = document.createElement('div'); q.className = 'qr';
    qr.forEach(([l, fn]) => { const b = document.createElement('button'); b.textContent = l;
      b.onclick = () => { q.remove(); user(l); fn(); }; q.append(b); }); log.append(q); }
  log.scrollTop = log.scrollHeight;
}
function user(t) {
  const r = document.createElement('div'); r.className = 'row u';
  r.innerHTML = `<div class="b">${esc(t)}<span class="t">${hm()}</span></div>`; log.append(r); log.scrollTop = log.scrollHeight;
}
// "50K", "1.5m", "50 000" → ədəd; səhv olarsa null
function num(s) {
  s = String(s).trim().toLowerCase().replace(/[\s,%]/g, ''); let m = 1;
  if (s.endsWith('k')) { m = 1e3; s = s.slice(0, -1); } else if (s.endsWith('m')) { m = 1e6; s = s.slice(0, -1); }
  if (!/^-?\d+(\.\d+)?$/.test(s)) return null;
  return parseFloat(s) * m;
}
async function api(path, opts) {
  const r = await fetch(path, opts); const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Server xətası'); return j;
}
const post = (p, body) => api(p, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});

/* ───────── 6 əsas sual + 3 fərziyyə sualı ───────── */
const gridCount = p => Math.floor((p.max_amount - p.min_amount) / p.step + 1e-9) + 1;
const money = (t) => { const v = num(t); return v !== null && v > 0 ? v : 'Müsbət məbləğ yazın (məs. 50K).'; };
const percent = (lo, hi, name) => t => { const v = num(t); return v !== null && v >= lo && v <= hi ? v / 100 : `${name} ${lo}–${hi}% arasında faizlə yazın (məs. ${Math.max(lo, 6)}).`; };
const QS = [
  {k:'min_amount', q:'1) <b>Minimum investisiya məbləği</b> neçədir? (məs. 50K)', parse:money},
  {k:'max_amount', q:'2) <b>Maksimum investisiya məbləği</b> neçədir? (məs. 500K)',
    parse:t => { const v = money(t); return typeof v === 'string' ? v : v < S.p.min_amount ? 'Maksimum minimumdan kiçik ola bilməz.' : v; }},
  {k:'step', q:'3) <b>Addım</b> neçədir? (məs. 15K)',
    parse:t => { const v = money(t); if (typeof v === 'string') return v;
      const n = gridCount({...S.p, step:v}); return n > 100 ? `Bu addımla ${n} məbləğ alınır; addımı artırın (maksimum 100 məbləğ).` : v; }},
  {k:'years', q:'4) <b>Neçə il</b> müddətinə? (məs. 5)', parse:t => { const v = num(t); return v !== null && Number.isInteger(v) && v >= 1 && v <= 30 ? v : '1–30 arası tam il sayı yazın.'; }},
  {k:'min_success', q:'5) <b>Minimum qəbul etdiyiniz uğur ehtimalı</b>? (məs. 80%)', parse:percent(1, 100, 'Uğur ehtimalı')},
  {k:'min_return', q:'6) <b>Minimum gözlədiyiniz illik gəlirlilik (IRR)</b>? (məs. 6%)', parse:percent(0, 99, 'Gəlir')},
  {k:'alt_return', q:'Model fərziyyəsi: əlavə pulu <b>başqa yerdə</b> (depozit, başqa investisiya) illik təxminən neçə % qazana bilərsiniz? Böyük məbləğ yalnız əlavə pul bu gəlirdən çoxunu gətirəndə seçiləcək.',
    def:[() => S.p.min_return, 'Minimum gəlirlə eyni'], parse:percent(0, 99, 'Alternativ gəlir')},
  {k:'payout_rate', q:'Model fərziyyəsi: şirkət investora <b>cari qazanc səviyyəsində</b> illik investisiyanın təxminən neçə %-ni ödəsin? Ödəniş sabit deyil, şirkətin EBITDA-sı ilə dəyişir: yaxşı ildə çox, pis ildə az. Sonda əsas məbləğ qaytarılır.',
    def:[0.12, 'Standart: 12%'], parse:percent(1, 99, 'Ödəniş')},
  {k:'recovery', q:'Defolt olarsa investor <b>əsas məbləğin neçə %-ni</b> geri alır?', def:[0.40, 'Standart: 40%'], parse:percent(0, 100, 'Geri qayıtma')},
  {k:'sector', q:'<b>Sektor</b> nədir? Leverage limiti Damodaran-ın sektor üzrə Debt/EBITDA göstəricisindən götürüləcək. Sektor adını ingiliscə yazın (məs. Retail, Software, Steel) və ya limiti rəqəmlə yazın (məs. 2.5).',
    def:null},
];
function startQuestions() { S.qi = 0; S.p = {}; S.mode = 'q'; askQ(); }
function askQ() {
  const q = QS[S.qi];
  if (q.k === 'sector') return bot(q.q, [['Ümumi bazar (3.01x)', () => setSector(null, 3.01, 'Total Market (without financials)')]]);
  bot(q.q, q.def ? [[q.def[1], () => answer(typeof q.def[0] === 'function' ? q.def[0]() : q.def[0])]] : null);
}
function answer(v) { S.p[QS[S.qi].k] = v; S.qi++; S.qi < QS.length ? askQ() : run(); }
function setSector(_, lev, name) { S.p.max_leverage = lev; S.p.sector = name; S.qi++; run(); }
async function sectorInput(t) {
  if (/(ümumi|umumi|bazar|market|bilmir)/i.test(t)) return setSector(null, 3.01, 'Total Market (without financials)');
  const n = num(t);
  if (n !== null) { if (n <= 0 || n > 50) return bot('Limit 0–50 arası olmalıdır (məs. 2.5).'); return setSector(null, n, null); }
  try {
    const r = await api('/api/sectors?q=' + encodeURIComponent(t));
    if (!r.matches.length) return bot(`"${esc(t)}" tapılmadı. Başqa ad yazın (məs. Retail, Steel, Software) və ya rəqəmlə limit daxil edin.`,
      [[`Ümumi bazar (${r.default.debt_to_ebitda}x)`, () => setSector(null, r.default.debt_to_ebitda, r.default.name)]]);
    if (r.matches.length === 1) return setSector(null, r.matches[0].debt_to_ebitda, r.matches[0].name);
    bot('Hansı sektor?', r.matches.map(m => [`${m.name} (${m.debt_to_ebitda}x)`, () => setSector(null, m.debt_to_ebitda, m.name)]));
  } catch (e) { bot('⚠️ ' + esc(e.message)); }
}

/* ───────── Məlumat daxil etmə ───────── */
function welcome() {
  S.mode = 'idle'; S.fin = {}; S.missing = [];
  bot('Salam! Şirkətin maliyyə hesabatını (Excel və ya CSV) yükləyin. Rəqəmləri oxuyub müflisləşmə riskini (Altman Z), leverage-i və 4000 ssenarilik Monte Carlo ilə optimal investisiya məbləğini hesablayacağam. Sonra sizə 6 sual verəcəyəm.',
    [['Nümunə data ilə başla', async () => { S.fin = await api('/api/sample'); S.missing = []; startQuestions(); }],
     ['Excel/CSV yükləyəcəm (📎)', () => bot('Aşağıdakı 📎 düyməsi ilə .xlsx və ya .csv faylını seçin.')]]);
}
$('#file').onchange = async e => {
  const f = e.target.files[0]; if (!f) return; user('📎 ' + f.name);
  const fd = new FormData(); fd.append('file', f);
  try {
    const r = await api('/api/upload', {method:'POST', body:fd});
    S.fin = r.found; S.missing = r.missing;
    const got = Object.keys(r.found).map(k => LBL[k].split(' (')[0]).join(', ');
    bot(`Fayldan oxundu: <b>${esc(got || 'heç nə')}</b>.` + (r.missing.length ? ` ${r.missing.length} göstərici tapılmadı, onları soruşacağam.` : '')
      + (r.notes.length ? '<br>' + esc(r.notes.join(' ')) : '') + (r.found.ebitda ? `<br>EBITDA: ${esc(r.found.ebitda.map(fmt).join(' → '))} (son rəqəm ən son ildir). Səhvdirsə, səhifəni yeniləyib faylı düzəldin.` : ''));
    nextMissing();
  } catch (err) { bot('⚠️ ' + esc(err.message)); }
  e.target.value = '';
};
function nextMissing() {
  if (!S.missing.length) return startQuestions();
  S.mode = 'missing'; bot(`<b>${LBL[S.missing[0]]}</b> neçədir?`);
}

/* ───────── Hesablama və nəticə ───────── */
async function run() {
  S.mode = 'busy'; bot('Hesablayıram: hər məbləğ üçün 4000 ssenari…');
  try {
    const res = await post('/api/analyze', {financials:S.fin, params:S.p});
    S.ctx = res; show(res); S.mode = 'chat';
  } catch (err) {
    bot('⚠️ ' + esc(err.message) + '<br>Parametrləri yenidən daxil edək.'); startQuestions();
  }
}
function show(r) {
  const a = r.altman, p = r.params;
  const col = {safe:'#1e9e5a', grey:'#d98a00', distress:'#d33'}[a.zone];
  const nm = {safe:'Sağlam zona (Safe)', grey:'Orta zona (Grey)', distress:'Təhlükə zonası (Distress)'}[a.zone];
  const pos = (v, t) => v >= 0 ? `${t} həddindən ${v.toFixed(2)} yuxarı` : `${t} həddindən ${(-v).toFixed(2)} aşağı`;
  const comp = a.components.map(c => `<tr><td>${c.id} — ${esc(c.name)}</td><td>${c.ratio}</td><td>×${c.weight}</td><td>${c.contribution}</td></tr>`).join('');
  bot(`<b>Müflisləşmə riski (Altman Z-Score):</b> Z = <b>${a.z}</b> <span class="tag" style="background:${col}">${nm}</span><br>` +
      `${pos(a.to_safe, 'Safe (2.99)')}; ${pos(a.to_distress, 'Distress (1.81)')}.<br>` +
      `<table><tr><th>Amil</th><th>Nisbət</th><th>Əmsal</th><th>Töhfə</th></tr>${comp}</table>` +
      `<b>EBITDA artımı:</b> ${pc(r.growth, 1)} / il`);
  const tr = r.rows.map(x => { const bad = x.success_prob < p.min_success;
    return `<tr class="${r.best && x.amount === r.best.amount ? 'best' : bad ? 'bad' : ''}"><td>${fmt(x.amount)}</td>` +
    `<td>${x.leverage}x${x.excess ? ' (+' + x.excess + ')' : ''}</td><td>${pc(x.share, 1)}</td><td>${pc(x.success_prob)}${bad ? ' ❌' : ''}</td><td>${pc(x.default_prob)}</td>` +
    `<td>${fmt(x.expected_profit)}</td><td>${pc(x.expected_irr, 1)}</td><td>${fmt(x.npv)}</td><td>${fmt(x.p10)} / ${fmt(x.p50)} / ${fmt(x.p90)}</td></tr>`; }).join('');
  bot(`<table><tr><th>Məbləğ</th><th>Leverage</th><th>EBITDA payı</th><th>Uğur</th><th>Defolt</th><th>Gözl. xalis gəlir</th><th>IRR</th><th>Alternativdən artıq dəyər (NPV)</th><th>P10 / P50 / P90 (ümumi alınan pul)</th></tr>${tr}</table>` +
    (r.best ? `<br>✅ <b>Optimal: ${fmt(r.best.amount)}</b>: uğur ${pc(r.best.success_prob)}, gözlənilən xalis gəlir ${fmt(r.best.expected_profit)}, illik gəlirlilik (IRR) ${pc(r.best.expected_irr, 1)}.`
            : `<br>⚠️ Heç bir məbləğ ${pc(p.min_success)} uğur ehtimalını ödəmir.`) +
    (r.choice_note ? `<br>ℹ️ Daha böyük <b>${fmt(r.choice_note.next_amount)}</b> niyə seçilmədi: əlavə ${fmt(r.choice_note.extra_amount)} investisiya yalnız ${fmt(r.choice_note.extra_profit)} əlavə gözlənilən xalis gəlir gətirir. Həmin pul ${pc(p.hurdle)}/il alternativdə daha çox qazandırardı (cari dəyərdə fərq: ${fmt(r.choice_note.extra_npv)}).` : ''));
  bot(`<b>İstifadə olunan fərziyyələr:</b> müddət ${p.years} il · ilkin ödəniş ${pc(p.payout_rate)} (EBITDA ilə dəyişir) · alternativ gəlir ${pc(p.hurdle)}/il · defoltda geri qayıtma ${pc(p.recovery)} · ` +
      `leverage limiti ${p.max_leverage}x${p.sector ? ' (' + esc(p.sector) + ', Damodaran)' : ' (əl ilə)'} · EBITDA dəyişkənliyi ${pc(p.vol, 0)} (${esc(p.vol_note)}).` +
      (r.warnings.length ? '<br>⚠️ ' + r.warnings.map(esc).join('<br>⚠️ ') : ''));
  bot('<b>AI izahı:</b>\n' + esc(r.summary) + '\n\nSual verə bilərsiniz (məs. "Niyə 200K atıldı?").',
    [['🔁 Parametrləri dəyiş', startQuestions], ['📂 Başqa şirkət', welcome]]);
}

/* ───────── Mesaj göndərmə ───────── */
$('#f').onsubmit = async e => {
  e.preventDefault(); const t = inp.value.trim(); inp.value = ''; if (!t) return; user(t);
  if (S.mode === 'missing') {
    const k = S.missing[0], v = k === 'ebitda' ? t.split(/[;\s]+/).map(num) : num(t);
    if (k === 'ebitda' ? (v.length < 2 || v.some(x => x === null)) : v === null) return bot('Düzgün rəqəm daxil edin.');
    S.fin[k] = v; S.missing.shift(); nextMissing();
  } else if (S.mode === 'q') {
    const q = QS[S.qi];
    if (q.k === 'sector') return sectorInput(t);
    const v = q.parse(t); if (typeof v === 'string') return bot(v);
    answer(v);
  } else if (S.mode === 'chat') {
    try { const r = await post('/api/chat', {message:t, history:S.hist, context:S.ctx});
      S.hist.push({role:'user', content:t}, {role:'assistant', content:r.reply}); bot(esc(r.reply));
    } catch (err) { bot('⚠️ ' + esc(err.message)); }
  } else if (S.mode === 'idle') bot('Əvvəlcə Excel yükləyin və ya nümunə data ilə başlayın.');
};
welcome();
