/* Shared helpers: theme toggle, escaping, number formatting, CSRF-aware fetch. */
window.Eco = (function () {
  const csrf = () => (document.querySelector('meta[name="csrf"]') || {}).content || "";

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const inr = n => { const v = Math.round(Number(n)) || 0; return "₹" + v.toLocaleString("en-IN"); };   // avoids "₹-0"
  const num = (n, d = 1) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: d });

  async function api(path, method = "GET", body) {
    const opts = { method, headers: { "X-CSRF-Token": csrf() } };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    let res;
    try { res = await fetch(path, opts); } catch (e) { throw { message: "Cannot reach the server. Is it running?" }; }
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON response */ }
    if (res.status === 401) { window.location.href = "/login"; throw { message: "Session expired." }; }
    if (!res.ok) throw { message: data.error || "Request failed (" + res.status + ")", details: data.details || [] };
    return data;
  }

  const toggle = document.getElementById("theme-toggle");
  if (toggle) toggle.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("ecowise-theme", next); } catch (e) { /* storage blocked */ }
  });

  return { esc, inr, num, api };
})();
