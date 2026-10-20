/* Dashboard: appliance editor, analyze/optimize, results rendering, what-if, save, CSV. */
(function () {
  const { esc, inr, num, api } = Eco;
  const CFG = JSON.parse(document.getElementById("cfg").textContent);
  const $ = (s, r = document) => r.querySelector(s);
  const tbody = $("#appliance-table tbody");

  let rows = [];            // appliance models shown in the table
  let lastPayload = null;   // payload used for the last successful analysis
  let lastResult = null;
  let whatIfTimer = null;

  /* ---------- appliance table ---------- */
  const presetByKey = Object.fromEntries(CFG.presets.map(p => [p.key, p]));
  const sel = $("#preset-select");
  sel.innerHTML = CFG.presets.map(p => `<option value="${esc(p.key)}">${esc(p.name)} - ${p.watts} W</option>`).join("");

  function fromPreset(key, over) {
    const p = presetByKey[key];
    return Object.assign({ key: p.key, name: p.name, category: p.category, qty: 1, watts: p.watts, hours: p.hours,
      min_hours: p.min_hours, priority: p.priority, standby_w: p.standby_w }, over || {});
  }
  function customRow() {
    return { key: "", name: "", category: "other", qty: 1, watts: 100, hours: 2, min_hours: 1, priority: 3, standby_w: 0 };
  }

  const FIELDS = [["qty", 1, 1, 50], ["watts", 1, 0.1, 10000], ["hours", 0.25, 0, 24], ["min_hours", 0.25, 0, 24]];

  function renderTable() {
    tbody.innerHTML = "";
    rows.forEach((r, i) => {
      const tr = document.createElement("tr");
      let html = `<td><input data-f="name" value="${esc(r.name)}" maxlength="60" placeholder="Appliance name" aria-label="Appliance name"></td>`;
      FIELDS.forEach(([f, step, min, max]) => {
        html += `<td><input data-f="${f}" type="number" step="${step}" min="${min}" max="${max}" value="${r[f]}" aria-label="${f}"></td>`;
      });
      html += `<td><select data-f="priority" aria-label="priority">${[1, 2, 3, 4, 5].map(p =>
        `<option value="${p}" ${p === r.priority ? "selected" : ""}>${p}${p === 1 ? " - easy to cut" : p === 5 ? " - essential" : ""}</option>`).join("")}</select></td>`;
      html += `<td><input data-f="standby_w" type="number" step="0.5" min="0" max="100" value="${r.standby_w}" aria-label="standby watts"></td>`;
      html += `<td><button class="btn ghost small danger-text" type="button" data-remove="${i}" aria-label="Remove">✕</button></td>`;
      tr.innerHTML = html;
      tbody.appendChild(tr);
    });
    $("#empty-hint").classList.toggle("hidden", rows.length > 0);
    $("#appliance-table").classList.toggle("hidden", rows.length === 0);
  }

  tbody.addEventListener("input", e => {
    const f = e.target.dataset.f; if (!f) return;
    const i = [...tbody.children].indexOf(e.target.closest("tr"));
    rows[i][f] = (f === "name") ? e.target.value : (f === "priority" ? parseInt(e.target.value, 10) : e.target.value);
    e.target.classList.remove("invalid");
  });
  tbody.addEventListener("click", e => {
    const b = e.target.closest("[data-remove]"); if (!b) return;
    rows.splice(parseInt(b.dataset.remove, 10), 1); renderTable();
  });
  $("#add-preset").addEventListener("click", () => { rows.push(fromPreset(sel.value)); renderTable(); });
  $("#add-custom").addEventListener("click", () => { rows.push(customRow()); renderTable(); const l = tbody.lastElementChild; if (l) l.querySelector("input").focus(); });
  $("#load-sample").addEventListener("click", () => { rows = CFG.sample.map(s => fromPreset(s.key, { qty: s.qty, hours: s.hours })); renderTable(); });
  $("#clear-all").addEventListener("click", () => { if (!rows.length || confirm("Remove all appliances?")) { rows = []; renderTable(); hideResults(); } });

  /* ---------- settings ---------- */
  const modeEl = $("#tariff_mode"), rateEl = $("#tariff_rate"), comfortEl = $("#comfort");
  modeEl.value = CFG.defaults.tariff_mode; rateEl.value = CFG.defaults.tariff_rate;
  function syncTariffUi() {
    const slab = modeEl.value === "slab";
    $("#rate-field").classList.toggle("hidden", slab);
    $("#tariff-note").textContent = slab
      ? "Slab mode uses illustrative sample slabs (first 100 units free, then ₹2.35 up to ₹11.55 per unit). Edit SAMPLE_SLABS in engine.py to match your state's tariff."
      : "Demo tariff is ₹8/kWh. Savings are estimates and depend on real usage and your actual electricity rates.";
  }
  modeEl.addEventListener("change", syncTariffUi); syncTariffUi();
  comfortEl.addEventListener("input", () => { $("#comfort-val").textContent = comfortEl.value + "%"; });

  function collect() {
    return {
      appliances: rows.map(r => ({ key: r.key, name: r.name.trim(), category: r.category, qty: r.qty, watts: r.watts,
        hours: r.hours, min_hours: r.min_hours, priority: r.priority, standby_w: r.standby_w })),
      settings: { tariff_mode: modeEl.value, tariff_rate: rateEl.value, comfort_target: comfortEl.value,
        cap_kwh_day: $("#cap").value, actual_kwh_month: $("#actual").value },
    };
  }

  function showErrors(err) {
    const box = $("#errors");
    const list = (err.details || []).map(d => `<li>${esc(d)}</li>`).join("");
    box.innerHTML = `<b>${esc(err.message)}</b>${list ? `<ul>${list}</ul>` : ""}`;
    box.classList.remove("hidden");
    box.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  const clearErrors = () => $("#errors").classList.add("hidden");
  const hideResults = () => { $("#results").classList.add("hidden"); lastResult = null; };

  /* ---------- analyze ---------- */
  $("#analyze").addEventListener("click", analyze);
  let savedId = null;     // id of the history entry for the current results
  async function analyze(_evt, skipAutoSave) {
    clearErrors();
    const payload = collect();
    const btn = $("#analyze");
    btn.disabled = true; $("#busy").classList.remove("hidden");
    try {
      const res = await api("/api/optimize", "POST", payload);
      lastPayload = payload; lastResult = res;
      render(res, payload);
      savedId = null;
      if (!skipAutoSave) {      // auto-save every new analysis to history
        try {
          const saved = await api("/api/history", "POST", Object.assign({}, payload, { title: $("#save-title").value }));
          savedId = saved.id;
        } catch (e) { /* analysis still shown; manual Save button remains available */ }
      } else if (CFG.load_id) { savedId = CFG.load_id; }
      $("#results").classList.remove("hidden");
      $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { showErrors(e); }
    finally { btn.disabled = false; $("#busy").classList.add("hidden"); }
  }

  /* ---------- render results ---------- */
  function render(res, payload) {
    const a = res.analysis, b = a.before, o = res.optimization;
    $("#tariff-label").textContent = res.tariff.mode === "slab" ? "slab (sample)" : `flat ₹${res.tariff.rate}/kWh`;

    // KPIs
    let k = `<div class="kpi"><span>Daily energy</span><b>${num(b.kwh_day, 2)} kWh</b><small>${num(b.kwh_month, 0)} kWh / month</small></div>
      <div class="kpi"><span>Estimated monthly bill</span><b>${inr(b.cost_month)}</b><small>${inr(b.cost_day)} / day</small></div>
      <div class="kpi"><span>Carbon footprint</span><b>${num(b.co2_month_kg, 0)} kg</b><small>CO₂ per month (approx.)</small></div>`;
    if (o.feasible) k += `<div class="kpi highlight"><span>Potential saving</span><b>${inr(o.savings.monthly_cost)} / mo</b><small>${o.savings.percent}% less · ${inr(o.savings.yearly_cost)} / year</small></div>`;
    $("#kpis").innerHTML = k;

    // donut + legend (top 8 + others)
    const sorted = b.rows.filter(r => r.kwh_day > 0).sort((x, y) => y.kwh_day - x.kwh_day);
    const top = sorted.slice(0, 8), rest = sorted.slice(8).reduce((s, r) => s + r.kwh_day, 0);
    const items = top.map(r => ({ label: r.name, value: r.kwh_day, share: r.share }));
    if (rest > 0) items.push({ label: "Others", value: rest, share: rest / b.kwh_day });
    EcoCharts.donut($("#donut"), items, num(b.kwh_day, 1), "kWh / day");
    $("#donut-legend").innerHTML = items.map((it, i) =>
      `<li><i style="background:${EcoCharts.colorFor(i)}"></i>${esc(it.label)}<span>${(it.share * 100).toFixed(0)}%</span></li>`).join("");

    // score
    const nHigh = a.rules.filter(r => r.severity === "high").length;
    const msg = a.score >= 85 ? "Excellent - your usage looks efficient." : a.score >= 55 ? "Decent, with a few areas to improve." : "Plenty of room to save - start with the high-priority findings.";
    $("#score").innerHTML = `<div class="score-ring" id="ring"></div><div class="score-text"><div class="grade">Grade ${esc(a.grade)}</div><p>${esc(msg)}</p>
      <p class="muted small-text">${a.rules.length} finding(s), ${nHigh} high priority.</p></div>`;
    EcoCharts.ring($("#ring"), a.score, a.grade);

    // rules
    $("#rules").innerHTML = a.rules.length ? a.rules.map(r => `
      <div class="rule ${esc(r.severity)}">
        <div class="rule-top"><span class="tag">${esc(r.rule)}</span><span class="tag ${esc(r.severity)}">${esc(r.severity)}</span>${esc(r.title)} · <span class="muted">${esc(r.appliance)}</span></div>
        <p><span class="kw">IF</span> ${esc(r.if_text)}</p>
        <p><span class="kw">THEN</span> ${esc(r.then_text)}${r.saving_kwh_month ? ` <span class="save">(≈ ${num(r.saving_kwh_month, 1)} kWh/month)</span>` : ""}</p>
      </div>`).join("") : `<div class="all-good">✅ No inefficiencies detected by the rules. Nice work!</div>`;
    $("#rule-lib").innerHTML = CFG.rules.map(r => `<li><b>${esc(r.id)}</b> - IF ${esc(r.cond)} THEN ${esc(r.then)}</li>`).join("");

    // before table
    $("#before-table tbody").innerHTML = b.rows.map(r => `<tr><td>${esc(r.name)}${r.qty > 1 ? ` ×${r.qty}` : ""}</td>
      <td class="num">${num(r.kwh_day, 2)}</td><td class="num">${num(r.kwh_month, 1)}</td><td class="num">${inr(r.cost_month)}</td><td class="num">${(r.share * 100).toFixed(1)}%</td></tr>`).join("") +
      `<tr><td><b>Total</b></td><td class="num"><b>${num(b.kwh_day, 2)}</b></td><td class="num"><b>${num(b.kwh_month, 1)}</b></td><td class="num"><b>${inr(b.cost_month)}</b></td><td class="num">100%</td></tr>`;

    renderOptimization(res, payload);
  }

  function renderOptimization(res, payload) {
    const o = res.optimization, b = res.analysis.before;
    const planBody = $("#plan-table tbody"), whatCard = $("#whatif-card");
    if (!o.feasible) {
      $("#opt-summary").innerHTML = `<div class="warn"><b>No valid plan found.</b> ${esc(o.message)}</div>`;
      planBody.innerHTML = ""; $("#bars").innerHTML = ""; $("#trace").innerHTML = ""; $("#algo-stats").textContent = ""; $("#moves").innerHTML = "";
      whatCard.classList.add("hidden");
      return;
    }
    whatCard.classList.remove("hidden");
    $("#opt-summary").innerHTML = `<div class="opt-banner">
      <div><span>Monthly bill</span><b>${inr(b.cost_month)} → ${inr(o.after.cost_month)}</b></div>
      <div><span>Daily saving</span><b>${inr(o.savings.daily_cost)}</b></div>
      <div><span>Monthly saving</span><b>${inr(o.savings.monthly_cost)} (${o.savings.percent}%)</b></div>
      <div><span>Energy saved</span><b>${num(o.savings.monthly_kwh, 0)} kWh/mo</b></div>
      <div><span>CO₂ avoided</span><b>${num(o.savings.co2_month_kg, 0)} kg/mo</b></div>
      <div><span>Comfort kept</span><b>${o.comfort_retention}%</b></div></div>`;

    planBody.innerHTML = o.plan.map(p => {
      const cls = p.delta_hours < 0 ? "delta-neg" : "delta-zero";
      return `<tr><td>${esc(p.name)}${p.qty > 1 ? ` ×${p.qty}` : ""}</td><td class="num">${p.before_hours}</td><td class="num"><b>${p.after_hours}</b></td>
        <td class="num ${cls}">${p.delta_hours > 0 ? "+" : ""}${p.delta_hours}</td><td class="num">${num(p.kwh_month_before - p.kwh_month_after, 1)}</td><td class="num">${inr(p.cost_month_saved)}</td></tr>`;
    }).join("");

    const barRows = o.plan.filter(p => p.kwh_month_before > 0).sort((x, y) => y.kwh_month_before - x.kwh_month_before).slice(0, 8)
      .map(p => ({ label: p.name, a: Math.round(p.kwh_month_before), b: Math.round(p.kwh_month_after) }));
    EcoCharts.bars($("#bars"), barRows);
    EcoCharts.line($("#trace"), o.trace.length > 1 ? o.trace : [o.trace[0], o.trace[0]], { xLabel: "Hill-climbing step", yLabel: "Monthly cost (₹)", fmt: v => "₹" + Math.round(v).toLocaleString("en-IN") });
    const s = o.stats;
    $("#algo-stats").textContent = `CSP backtracking visited ${s.backtrack_nodes} nodes to find valid starting states; hill climbing made ${s.iterations} moves across ${s.restarts + 1} runs (best: run ${s.best_run + 1}).`;

    $("#moves").innerHTML = o.moves.length ? `<h3 style="margin-top:1rem">Recommended changes</h3><ol class="moves">${o.moves.map(m =>
      `<li>${esc(m.text)} <em>- ${esc(m.reason)}</em></li>`).join("")}</ol>`
      : `<p class="muted">Your current usage already meets the comfort target at the lowest cost - nothing to change.</p>`;

    buildWhatIf(res, payload);
  }

  /* ---------- what-if simulator ---------- */
  function buildWhatIf(res, payload) {
    const plan = res.optimization.plan, box = $("#whatif-sliders");
    box.innerHTML = plan.map((p, i) => p.before_hours <= 0 ? "" : `<div class="s-row">
      <label for="wi-${i}">${esc(p.name)}${p.qty > 1 ? ` ×${p.qty}` : ""}</label><output id="wi-out-${i}">${p.after_hours} h</output>
      <input id="wi-${i}" data-i="${i}" type="range" min="0" max="${p.before_hours}" step="0.25" value="${p.after_hours}"></div>`).join("");
    box.oninput = e => {
      const r = e.target; if (!r.dataset.i) return;
      $("#wi-out-" + r.dataset.i).textContent = r.value + " h";
      clearTimeout(whatIfTimer); whatIfTimer = setTimeout(runWhatIf, 150);
    };
    runWhatIf();
  }
  async function runWhatIf() {
    if (!lastPayload) return;
    const plan = lastResult.optimization.plan;
    const hours = plan.map((p, i) => { const el = document.getElementById("wi-" + i); return el ? parseFloat(el.value) : 0; });
    try {
      const r = await api("/api/calculate", "POST", Object.assign({}, lastPayload, { hours }));
      const base = lastResult.analysis.before;
      $("#whatif-out").innerHTML = `
        <div class="row"><span>Monthly bill</span><b>${inr(r.after.cost_month)}</b></div>
        <div class="row"><span>You save</span><b class="good">${inr(r.monthly_saved)} / month (${r.percent}%)</b></div>
        <div class="row"><span>Energy</span><b>${num(r.after.kwh_month, 0)} kWh <small class="muted">of ${num(base.kwh_month, 0)}</small></b></div>
        <div class="row"><span>Comfort kept</span><b>${r.comfort_retention}%</b></div>
        <button class="btn small ghost" type="button" id="wi-reset">Reset to optimised plan</button>`;
      $("#wi-reset").onclick = () => { plan.forEach((p, i) => { const el = document.getElementById("wi-" + i); if (el) { el.value = p.after_hours; $("#wi-out-" + i).textContent = p.after_hours + " h"; } }); runWhatIf(); };
    } catch (e) { $("#whatif-out").textContent = e.message; }
  }

  /* ---------- save / csv / print ---------- */
  $("#save-btn").addEventListener("click", async () => {
    if (!lastPayload) return;
    const btn = $("#save-btn"); btn.disabled = true;
    try {
      const title = $("#save-title").value.trim();
      if (savedId && title) await api("/api/history/" + savedId, "PUT", { title });
      else if (!savedId) savedId = (await api("/api/history", "POST", Object.assign({}, lastPayload, { title }))).id;
      btn.textContent = "✔ Saved";
      setTimeout(() => { btn.textContent = "💾 Save name"; btn.disabled = false; }, 1800);
    } catch (e) { showErrors(e); btn.disabled = false; }
  });

  $("#csv-btn").addEventListener("click", () => {
    if (!lastResult) return;
    const o = lastResult.optimization, b = lastResult.analysis.before;
    const q = v => '"' + String(v).replace(/"/g, '""') + '"';
    const lines = [["Appliance", "Qty", "Watts", "Hours before", "Hours after", "kWh/month before", "kWh/month after", "Rs/month before", "Rs saved/month"].map(q).join(",")];
    b.rows.forEach((r, i) => {
      const p = o.feasible ? o.plan[i] : null;
      lines.push([r.name, r.qty, r.watts, r.hours, p ? p.after_hours : "", r.kwh_month, p ? p.kwh_month_after : "", r.cost_month, p ? p.cost_month_saved : ""].map(q).join(","));
    });
    lines.push("", [`Total monthly cost before`, b.cost_month].map(q).join(","));
    if (o.feasible) lines.push([`Total monthly cost after`, o.after.cost_month].map(q).join(","), [`Monthly saving`, o.savings.monthly_cost].map(q).join(","));
    const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ecowise-report.csv"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $("#print-btn").addEventListener("click", () => window.print());

  /* ---------- init ---------- */
  async function init() {
    if (CFG.load_id) {
      try {
        const d = await api("/api/history/" + CFG.load_id);
        rows = d.appliances.map(a => Object.assign({}, a));
        modeEl.value = d.settings.tariff_mode; rateEl.value = d.settings.tariff_rate;
        comfortEl.value = d.settings.comfort_target; $("#comfort-val").textContent = comfortEl.value + "%";
        $("#cap").value = d.settings.cap_kwh_day || ""; $("#actual").value = d.settings.actual_kwh_month || "";
        $("#save-title").value = d.title;
        syncTariffUi(); renderTable(); await analyze(null, true);
        return;
      } catch (e) { showErrors(e); }
    }
    rows = CFG.sample.map(s => fromPreset(s.key, { qty: s.qty, hours: s.hours }));   // start with a ready demo
    renderTable();
  }
  init();
})();
