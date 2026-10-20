/* Login / register page behaviour. */
(function () {
  document.querySelectorAll("[data-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.toggle);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  const demo = document.getElementById("fill-demo");
  if (demo) demo.addEventListener("click", () => {
    document.getElementById("email").value = demo.dataset.email;
    document.getElementById("password").value = demo.dataset.pw;
  });

  const pw = document.getElementById("password"), bar = document.getElementById("meter-bar"), txt = document.getElementById("meter-text");
  if (pw && bar && txt) pw.addEventListener("input", () => {
    const v = pw.value;
    let s = 0;
    if (v.length >= 8) s++; if (v.length >= 12) s++;
    if (/[A-Za-z]/.test(v) && /\d/.test(v)) s++;
    if (/[A-Z]/.test(v) && /[a-z]/.test(v)) s++;
    if (/[^A-Za-z0-9]/.test(v)) s++;
    const levels = [["8%", "#dc2626", "Too weak"], ["25%", "#dc2626", "Weak"], ["45%", "#f59e0b", "Fair"],
                    ["65%", "#f59e0b", "Good"], ["85%", "#16a34a", "Strong"], ["100%", "#16a34a", "Very strong"]];
    const l = v ? levels[s] : ["0%", "transparent", "Use 8+ characters with letters and numbers."];
    bar.style.width = l[0]; bar.style.background = l[1]; txt.textContent = l[2];
  });
})();
