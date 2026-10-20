/* History page: trend chart + delete. */
(function () {
  const box = document.getElementById("trend");
  if (box) {
    try {
      const items = JSON.parse(box.dataset.points).slice().reverse().slice(-12).map(i => ({
        label: i.title, before: i.cost_before, after: i.cost_after
      }));
      if (items.length) EcoCharts.trend(box, items);
    } catch (e) { box.textContent = "Could not draw chart."; }
  }
  document.querySelectorAll("[data-delete]").forEach(btn => btn.addEventListener("click", async () => {
    if (!confirm("Delete this saved analysis?")) return;
    try {
      await Eco.api("/api/history/" + btn.dataset.delete, "DELETE");
      window.location.reload();
    } catch (e) { alert(e.message); }
  }));
})();
