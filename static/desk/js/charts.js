/* Dashboard charts (plain SVG, ported from the original page). Data comes from the #chart-data JSON. */
(function () {
  const el = document.getElementById('chart-data');
  if (!el) return;
  const D = JSON.parse(el.textContent);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => Math.round(n || 0).toLocaleString('en-US');
  const short = v => v >= 1e6 ? Number((v / 1e6).toFixed(2)) + 'M' : v >= 1e3 ? Number((v / 1e3).toFixed(1)) + 'k' : String(Math.round(v));
  function niceMax(v) {
    if (v <= 0) return 1;
    const e = Math.pow(10, Math.floor(Math.log10(v))), f = v / e;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
  }

  function colChart(cats, series) {
    const W = 900, H = 260, L = 46, Rr = 8, T = 10, B = 34, iw = W - L - Rr, ih = H - T - B;
    const mx = niceMax(Math.max(1, ...series.flatMap(s => s.v)));
    let g = '';
    for (let i = 0; i <= 4; i++) {
      const y = T + ih - ih * i / 4;
      g += `<line class="grid" x1="${L}" x2="${W - Rr}" y1="${y}" y2="${y}"/><text x="${L - 6}" y="${y + 4}" text-anchor="end">${short(mx * i / 4)}</text>`;
    }
    const gw = iw / cats.length, bw = Math.min(16, (gw - 6) / series.length);
    cats.forEach((c, i) => {
      const x0 = L + gw * i + (gw - bw * series.length) / 2;
      series.forEach((s, k) => {
        const h = ih * s.v[i] / mx;
        g += `<rect x="${x0 + k * bw}" y="${T + ih - h}" width="${bw - 1}" height="${Math.max(h, 0)}" fill="var(${s.c})" rx="1"><title>${esc(c)} - ${esc(s.n)}: ${fmt(s.v[i])} UGX</title></rect>`;
      });
      g += `<text x="${L + gw * i + gw / 2}" y="${H - B + 15}" text-anchor="middle">${esc(c)}</text>`;
    });
    return `<div class="chwrap"><svg class="ch wide" viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly chart">${g}</svg></div>` +
      `<div class="legend">${series.map(s => `<span><i style="background:var(${s.c})"></i>${esc(s.n)}</span>`).join('')}</div>`;
  }

  function barChart(items, fmtV, colorFn) {
    if (!items.length) return '<div class="note">No data for this selection.</div>';
    const rowH = 26, L = 112, Rr = 56, W = 420, H = items.length * rowH + 8, iw = W - L - Rr;
    const mx = Math.max(1, ...items.map(i => i.v));
    const g = items.map((it, i) => {
      const y = 4 + i * rowH, w = iw * it.v / mx;
      return `<text x="${L - 8}" y="${y + 15}" text-anchor="end">${esc(it.l.length > 17 ? it.l.slice(0, 16) + '…' : it.l)}</text>` +
        `<rect x="${L}" y="${y + 3}" width="${Math.max(w, it.v > 0 ? 2 : 0)}" height="${rowH - 8}" fill="${colorFn ? colorFn(it) : 'var(--ch4)'}" rx="2"><title>${esc(it.l)}: ${fmtV(it.v)}</title></rect>` +
        `<text x="${L + w + 6}" y="${y + 15}">${fmtV(it.v)}</text>`;
    }).join('');
    return `<svg class="ch" viewBox="0 0 ${W} ${H}" role="img" aria-label="Bar chart">${g}</svg>`;
  }

  const put = (id, html) => { const n = document.getElementById(id); if (n) n.innerHTML = html; };
  put('chart-month', colChart(D.months, D.series));
  put('chart-officer', barChart(D.officers, short));
  put('chart-flags', barChart(D.flags, fmt, it => it.c));
})();
