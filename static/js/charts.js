/* Tiny dependency-free SVG charts: donut, grouped bars, line, trend. */
window.EcoCharts = (function () {
  const PALETTE = ["#16a34a", "#f59e0b", "#3b82f6", "#ec4899", "#8b5cf6", "#14b8a6", "#ef4444", "#84cc16", "#06b6d4", "#f97316", "#a855f7", "#64748b"];
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const text = "var(--text)", muted = "var(--muted)", grid = "var(--border)";

  function donut(el, items, centerTop, centerBottom) {
    const total = items.reduce((a, b) => a + b.value, 0);
    const R = 40, C = 2 * Math.PI * R;
    let off = 0, segs = "";
    items.forEach((it, i) => {
      const len = total > 0 ? (it.value / total) * C : 0;
      segs += `<circle r="${R}" cx="60" cy="60" fill="none" stroke="${PALETTE[i % PALETTE.length]}" stroke-width="18"
        stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 60 60)"><title>${esc(it.label)}</title></circle>`;
      off += len;
    });
    el.innerHTML = `<svg viewBox="0 0 120 120" role="img" aria-label="Energy share by appliance">
      <circle r="${R}" cx="60" cy="60" fill="none" stroke="${grid}" stroke-width="18"/>${segs}
      <text x="60" y="58" text-anchor="middle" font-size="15" font-weight="700" fill="${text}">${esc(centerTop)}</text>
      <text x="60" y="73" text-anchor="middle" font-size="8" fill="${muted}">${esc(centerBottom)}</text></svg>`;
  }

  function colorFor(i) { return PALETTE[i % PALETTE.length]; }

  function ring(el, score, grade) {
    const R = 44, C = 2 * Math.PI * R, len = (score / 100) * C;
    const col = score >= 70 ? "#16a34a" : score >= 45 ? "#f59e0b" : "#dc2626";
    el.innerHTML = `<svg viewBox="0 0 120 120" role="img" aria-label="Efficiency score ${score} out of 100">
      <circle r="${R}" cx="60" cy="60" fill="none" stroke="${grid}" stroke-width="12"/>
      <circle r="${R}" cx="60" cy="60" fill="none" stroke="${col}" stroke-width="12" stroke-linecap="round"
        stroke-dasharray="${len} ${C - len}" transform="rotate(-90 60 60)"/>
      <text x="60" y="64" text-anchor="middle" font-size="26" font-weight="800" fill="${text}">${score}</text>
      <text x="60" y="80" text-anchor="middle" font-size="9" fill="${muted}">out of 100</text></svg>`;
  }

  function bars(el, rows) {   // rows: [{label, a, b}]  a = before, b = after
    const rowH = 30, left = 130, W = 420, H = rows.length * rowH + 28;
    const max = Math.max(1, ...rows.map(r => Math.max(r.a, r.b)));
    const sx = v => (v / max) * (W - left - 52);
    let g = "";
    rows.forEach((r, i) => {
      const y = 22 + i * rowH;
      const label = r.label.length > 20 ? r.label.slice(0, 19) + "…" : r.label;
      g += `<text x="${left - 6}" y="${y + 9}" text-anchor="end" font-size="9.5" fill="${text}">${esc(label)}</text>
        <rect x="${left}" y="${y}" width="${Math.max(1, sx(r.a))}" height="9" rx="2" fill="#f59e0b"><title>Before: ${r.a} kWh</title></rect>
        <rect x="${left}" y="${y + 11}" width="${Math.max(1, sx(r.b))}" height="9" rx="2" fill="#16a34a"><title>After: ${r.b} kWh</title></rect>
        <text x="${left + sx(r.a) + 4}" y="${y + 8}" font-size="8" fill="${muted}">${r.a}</text>
        <text x="${left + sx(r.b) + 4}" y="${y + 19}" font-size="8" fill="${muted}">${r.b}</text>`;
    });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly kWh before and after">
      <rect x="${left}" y="4" width="9" height="9" rx="2" fill="#f59e0b"/><text x="${left + 13}" y="12" font-size="9" fill="${muted}">Before</text>
      <rect x="${left + 60}" y="4" width="9" height="9" rx="2" fill="#16a34a"/><text x="${left + 73}" y="12" font-size="9" fill="${muted}">After</text>${g}</svg>`;
  }

  function line(el, series, opts) {   // series: numbers; opts: {xLabel, yLabel, fmt}
    opts = opts || {};
    const W = 420, H = 190, l = 46, r = 12, t = 14, b = 30;
    const mn = Math.min(...series), mx = Math.max(...series), span = (mx - mn) || 1;
    const x = i => l + (series.length === 1 ? (W - l - r) / 2 : i * (W - l - r) / (series.length - 1));
    const y = v => t + (1 - (v - mn) / span) * (H - t - b);
    const fmt = opts.fmt || (v => Math.round(v).toLocaleString("en-IN"));
    const pts = series.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    let ticks = "";
    for (let k = 0; k <= 3; k++) {
      const v = mn + span * k / 3, yy = y(v);
      ticks += `<line x1="${l}" x2="${W - r}" y1="${yy}" y2="${yy}" stroke="${grid}" stroke-dasharray="3 3"/>
        <text x="${l - 6}" y="${yy + 3}" text-anchor="end" font-size="8.5" fill="${muted}">${fmt(v)}</text>`;
    }
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.yLabel || "Line chart")}">${ticks}
      <polyline points="${pts}" fill="none" stroke="#16a34a" stroke-width="2.5" stroke-linejoin="round"/>
      <circle cx="${x(0)}" cy="${y(series[0])}" r="3.5" fill="#f59e0b"/>
      <circle cx="${x(series.length - 1)}" cy="${y(series[series.length - 1])}" r="3.5" fill="#16a34a"/>
      <text x="${(W + l) / 2}" y="${H - 6}" text-anchor="middle" font-size="9" fill="${muted}">${esc(opts.xLabel || "")}</text>
      <text x="12" y="${H / 2}" font-size="9" fill="${muted}" transform="rotate(-90 12 ${H / 2})" text-anchor="middle">${esc(opts.yLabel || "")}</text></svg>`;
  }

  function trend(el, items) {   // items: [{label, before, after}] oldest -> newest
    const n = items.length, W = 640, H = 220, l = 56, r = 14, t = 22, b = 34;
    const all = items.flatMap(i => [i.before, i.after == null ? i.before : i.after]);
    const mx = Math.max(1, ...all), slot = (W - l - r) / n, bw = Math.min(26, slot / 3);
    let g = "";
    for (let k = 0; k <= 3; k++) {
      const v = mx * k / 3, yy = H - b - (v / mx) * (H - t - b);
      g += `<line x1="${l}" x2="${W - r}" y1="${yy}" y2="${yy}" stroke="${grid}" stroke-dasharray="3 3"/>
        <text x="${l - 6}" y="${yy + 3}" text-anchor="end" font-size="9" fill="${muted}">₹${Math.round(v).toLocaleString("en-IN")}</text>`;
    }
    items.forEach((it, i) => {
      const cx = l + slot * i + slot / 2, hb = (it.before / mx) * (H - t - b), ha = ((it.after == null ? it.before : it.after) / mx) * (H - t - b);
      g += `<rect x="${cx - bw - 1}" y="${H - b - hb}" width="${bw}" height="${hb}" rx="2" fill="#f59e0b"><title>${esc(it.label)} - before ₹${Math.round(it.before)}</title></rect>
        <rect x="${cx + 1}" y="${H - b - ha}" width="${bw}" height="${ha}" rx="2" fill="#16a34a"><title>${esc(it.label)} - after ₹${Math.round(it.after == null ? it.before : it.after)}</title></rect>
        <text x="${cx}" y="${H - 14}" text-anchor="middle" font-size="9" fill="${muted}">${esc(it.label.length > 12 ? it.label.slice(0, 11) + "…" : it.label)}</text>`;
    });
    g += `<rect x="${l}" y="4" width="9" height="9" rx="2" fill="#f59e0b"/><text x="${l + 13}" y="12" font-size="9.5" fill="${muted}">Before</text>
      <rect x="${l + 62}" y="4" width="9" height="9" rx="2" fill="#16a34a"/><text x="${l + 75}" y="12" font-size="9.5" fill="${muted}">After</text>`;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly cost trend">${g}</svg>`;
  }

  return { donut, ring, bars, line, trend, colorFor };
})();
