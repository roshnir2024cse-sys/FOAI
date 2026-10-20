"""
EcoWise AI - core logic (pure Python, no Flask).

Layers (as in the project architecture):
  1. Energy calculator      -> evaluate()
  2. Rule-based reasoning   -> run_rules()      (transparent IF-THEN rules)
  3. CSP + Backtracking     -> _backtrack()     (finds a VALID starting usage state)
  4. Hill Climbing          -> optimize()       (searches for a cheaper VALID state)
  5. Result layer           -> run_full()       (before/after cost, savings)

Constraint model (CSP)
  Variables : hours/day of every appliance
  Domains   : values from `min_hours` up to the current `hours`, in steps of 0.25 h
  Constraints:
     C1  min_hours <= hours <= current hours        (appliance-specific limits)
     C2  comfort retention >= comfort target        (weighted by priority 1-5)
     C3  total daily kWh <= optional daily cap
"""
from __future__ import annotations

import math
import random

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
CO2_KG_PER_KWH = 0.82        # approximate Indian grid emission factor
DAYS_PER_MONTH = 30
STEP = 0.25                  # search granularity (hours)
EPS = 1e-9
MIN_GAIN = 1.0               # ignore moves that save less than Rs 1/month (noise)
MAX_APPLIANCES = 30
BACKTRACK_NODE_LIMIT = 150_000
DEFAULT_FLAT_RATE = 8.0      # Rs/kWh used in the demo

# Illustrative slab tariff (Rs/unit for units falling inside each band).
# Real tariffs differ by state/DISCOM and change over time - edit as needed.
SAMPLE_SLABS = [
    (100, 0.00),
    (200, 2.35),
    (400, 4.70),
    (500, 6.30),
    (600, 8.40),
    (800, 9.45),
    (1000, 10.50),
    (math.inf, 11.55),
]

CATEGORIES = [
    "ac", "fan", "cooler", "lighting", "refrigeration", "heating", "entertainment",
    "laundry", "kitchen", "computing", "pump", "network", "other",
]

# --------------------------------------------------------------------------
# Appliance library
# priority: 1 = easy to give up ... 5 = essential
# --------------------------------------------------------------------------
PRESETS = [
    dict(key="ac", name="Air Conditioner (1.5 ton)", category="ac", watts=1400, hours=8, min_hours=3, priority=4, standby_w=3),
    dict(key="fan", name="Ceiling Fan", category="fan", watts=75, hours=10, min_hours=5, priority=4, standby_w=0),
    dict(key="cooler", name="Air Cooler", category="cooler", watts=180, hours=6, min_hours=2, priority=3, standby_w=0),
    dict(key="led", name="LED Bulb (9 W)", category="lighting", watts=9, hours=6, min_hours=3, priority=4, standby_w=0),
    dict(key="incandescent", name="Incandescent Bulb (60 W)", category="lighting", watts=60, hours=5, min_hours=2, priority=3, standby_w=0),
    dict(key="tube", name="Tube Light (40 W)", category="lighting", watts=40, hours=6, min_hours=3, priority=4, standby_w=0),
    dict(key="fridge", name="Refrigerator (avg draw)", category="refrigeration", watts=130, hours=24, min_hours=24, priority=5, standby_w=0),
    dict(key="tv", name='Television (LED 43")', category="entertainment", watts=90, hours=5, min_hours=1, priority=2, standby_w=1.5),
    dict(key="laptop", name="Laptop", category="computing", watts=60, hours=6, min_hours=2, priority=4, standby_w=1),
    dict(key="desktop", name="Desktop PC", category="computing", watts=200, hours=5, min_hours=2, priority=3, standby_w=3),
    dict(key="router", name="Wi-Fi Router", category="network", watts=10, hours=24, min_hours=12, priority=3, standby_w=0),
    dict(key="washer", name="Washing Machine", category="laundry", watts=500, hours=1, min_hours=0.5, priority=3, standby_w=1),
    dict(key="geyser", name="Water Heater (Geyser)", category="heating", watts=2000, hours=1, min_hours=0.25, priority=4, standby_w=0),
    dict(key="heater", name="Room Heater", category="heating", watts=1500, hours=2, min_hours=0.5, priority=3, standby_w=0),
    dict(key="iron", name="Iron Box", category="laundry", watts=1000, hours=0.5, min_hours=0.25, priority=3, standby_w=0),
    dict(key="microwave", name="Microwave Oven", category="kitchen", watts=1200, hours=0.5, min_hours=0.25, priority=3, standby_w=2),
    dict(key="induction", name="Induction Stove", category="kitchen", watts=1500, hours=1, min_hours=0.5, priority=4, standby_w=0),
    dict(key="mixer", name="Mixer Grinder", category="kitchen", watts=500, hours=0.25, min_hours=0.25, priority=3, standby_w=0),
    dict(key="pump", name="Water Pump (0.5 HP)", category="pump", watts=370, hours=1, min_hours=0.5, priority=4, standby_w=0),
    dict(key="charger", name="Phone Charger", category="computing", watts=10, hours=3, min_hours=1, priority=4, standby_w=0.5),
]
PRESET_BY_KEY = {p["key"]: p for p in PRESETS}

SAMPLE_HOME = [
    dict(key="ac", qty=1, hours=8), dict(key="fan", qty=3, hours=10),
    dict(key="led", qty=6, hours=6), dict(key="incandescent", qty=2, hours=4),
    dict(key="fridge", qty=1, hours=24), dict(key="tv", qty=1, hours=5),
    dict(key="washer", qty=1, hours=1), dict(key="geyser", qty=1, hours=1.5),
    dict(key="router", qty=1, hours=24), dict(key="laptop", qty=1, hours=6),
    dict(key="pump", qty=1, hours=1),
]

# Human-readable rule library (shown in the UI under "How the rules work")
RULE_CATALOG = [
    dict(id="R01", title="Dominant load", cond="appliance uses >= 35% of daily energy", then="target this appliance first"),
    dict(id="R02", title="Long AC runtime", cond="AC runs > 8 h/day", then="raise set-point to 24-26 C, use a sleep timer"),
    dict(id="R03", title="Long heating runtime", cond="heater / geyser runs > 1.5 h/day", then="add a timer or auto cut-off"),
    dict(id="R04", title="Incandescent bulb", cond="bulb type is incandescent", then="replace with a 9 W LED (about 85% less energy)"),
    dict(id="R05", title="Long lighting hours", cond="lighting runs > 8 h/day", then="use switches/sensors, switch off in empty rooms"),
    dict(id="R06", title="Standby (phantom) load", cond="total standby draw across appliances >= 1 kWh/month", then="switch off at the socket"),
    dict(id="R07", title="Always-on appliance", cond="non-essential appliance with >= 50 W runs 24 h/day", then="check whether it can be switched off"),
    dict(id="R08", title="High fridge draw", cond="refrigerator draw > 200 W", then="check door seal / star rating / age"),
    dict(id="R09", title="Long screen time", cond="TV / entertainment runs > 6 h/day", then="reduce hours or enable eco mode"),
    dict(id="R10", title="Pump runtime", cond="water pump runs > 1.5 h/day", then="use a timer or float switch"),
    dict(id="R11", title="Slab boundary", cond="monthly units are within 15 units below the next slab", then="trimming usage avoids a higher rate"),
    dict(id="R12", title="Bill mismatch", cond="estimate differs from your actual bill units by > 25%", then="re-check appliance hours / missing appliances"),
    dict(id="R13", title="High total usage", cond="monthly usage > 400 kWh", then="review the biggest loads first"),
]


# --------------------------------------------------------------------------
# Tariff
# --------------------------------------------------------------------------
class Tariff:
    """Flat Rs/kWh or illustrative slab-based tariff (monthly basis)."""

    def __init__(self, mode: str = "flat", rate: float = DEFAULT_FLAT_RATE):
        self.mode = mode if mode in ("flat", "slab") else "flat"
        self.rate = float(rate)

    def monthly_cost(self, kwh_month: float) -> float:
        if kwh_month <= 0:
            return 0.0
        if self.mode == "slab":
            cost, lower = 0.0, 0.0
            for upper, r in SAMPLE_SLABS:
                if kwh_month <= lower:
                    break
                cost += (min(kwh_month, upper) - lower) * r
                lower = upper
            return cost
        return kwh_month * self.rate

    def next_slab(self, kwh_month: float):
        """(units_to_next_slab, current_rate, next_rate) or None."""
        if self.mode != "slab":
            return None
        lower = 0.0
        for idx, (upper, r) in enumerate(SAMPLE_SLABS[:-1]):
            if kwh_month < upper:
                return upper - kwh_month, r, SAMPLE_SLABS[idx + 1][1]
            lower = upper
        return None

    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "rate": self.rate,
            "slabs": [{"upto": (None if math.isinf(u) else u), "rate": r} for u, r in SAMPLE_SLABS]
            if self.mode == "slab" else None,
        }


# --------------------------------------------------------------------------
# 1. Energy calculator
# --------------------------------------------------------------------------
def kwh_day(a: dict, hours: float | None = None) -> float:
    h = a["hours"] if hours is None else hours
    if h <= 0:
        return 0.0
    active = a["watts"] * h
    standby = a.get("standby_w", 0.0) * max(0.0, 24.0 - h)
    return a["qty"] * (active + standby) / 1000.0


def evaluate(apps: list[dict], tariff: Tariff, hours: list[float] | None = None) -> dict:
    hours = hours if hours is not None else [a["hours"] for a in apps]
    rows, total_day = [], 0.0
    for i, (a, h) in enumerate(zip(apps, hours)):
        k = kwh_day(a, h)
        standby = a["qty"] * a.get("standby_w", 0.0) * max(0.0, 24.0 - h) / 1000.0 if h > 0 else 0.0
        rows.append({"index": i, "name": a["name"], "qty": a["qty"], "watts": a["watts"],
                     "hours": h, "kwh_day": k, "kwh_month": k * DAYS_PER_MONTH,
                     "standby_kwh_day": standby})
        total_day += k
    kwh_month = total_day * DAYS_PER_MONTH
    cost_month = tariff.monthly_cost(kwh_month)
    for r in rows:
        share = (r["kwh_day"] / total_day) if total_day > 0 else 0.0
        r["share"] = share
        r["cost_month"] = cost_month * share
        r["cost_day"] = r["cost_month"] / DAYS_PER_MONTH
    return {
        "rows": rows,
        "kwh_day": total_day,
        "kwh_month": kwh_month,
        "cost_day": cost_month / DAYS_PER_MONTH,
        "cost_month": cost_month,
        "co2_month_kg": kwh_month * CO2_KG_PER_KWH,
    }


def comfort_retention(apps: list[dict], hours: list[float]) -> float:
    """Priority-weighted share of the user's current usage that is retained (0-1)."""
    num = den = 0.0
    for a, h in zip(apps, hours):
        if a["hours"] <= 0:
            continue
        num += a["priority"] * (h / a["hours"])
        den += a["priority"]
    return num / den if den else 1.0


# --------------------------------------------------------------------------
# 2. Rule-based reasoning (explainable IF-THEN rules)
# --------------------------------------------------------------------------
def run_rules(apps: list[dict], ev: dict, tariff: Tariff, actual_kwh_month: float | None) -> list[dict]:
    found: list[dict] = []

    def add(rid, sev, appliance, cond, then, saving=None):
        title = next(r["title"] for r in RULE_CATALOG if r["id"] == rid)
        found.append({"rule": rid, "title": title, "severity": sev, "appliance": appliance,
                      "if_text": cond, "then_text": then,
                      "saving_kwh_month": None if saving is None else round(max(saving, 0.0), 1)})

    for a, r in zip(apps, ev["rows"]):
        if a["hours"] <= 0:
            continue
        cat, name, h = a["category"], a["name"], a["hours"]
        pct = r["share"] * 100

        if len(apps) >= 2 and r["share"] >= 0.35:
            add("R01", "high", name, f"{name} uses {pct:.0f}% of daily energy (>= 35%)",
                "prioritise reducing this appliance first")
        if cat == "ac" and h > 8:
            add("R02", "high" if h > 10 else "medium", name, f"{name} runs {h:g} h/day (> 8 h)",
                "set the thermostat to 24-26 C and use a sleep timer; each +1 C saves roughly 6% (about "
                f"{r['kwh_month'] * 0.06:.0f} kWh/month here)", r["kwh_month"] * 0.06)
        if cat == "heating" and h > 1.5:
            add("R03", "medium", name, f"{name} runs {h:g} h/day (> 1.5 h)",
                "fit a timer or auto cut-off and heat only what you need",
                a["qty"] * a["watts"] * (h - 1.5) * DAYS_PER_MONTH / 1000)
        if a.get("key") == "incandescent":
            add("R04", "high", name, f"{name} are incandescent ({a['watts']:g} W)",
                "replace with 9 W LED bulbs for similar light",
                a["qty"] * (a["watts"] - 9) * h * DAYS_PER_MONTH / 1000)
        if cat == "lighting" and h > 8:
            add("R05", "low", name, f"{name} runs {h:g} h/day (> 8 h)",
                "use switches or motion sensors and switch off in empty rooms")
        if a["priority"] < 5 and h >= 24 and a["watts"] * a["qty"] >= 50:
            add("R07", "medium", name, f"{name} (non-essential, {a['watts'] * a['qty']:g} W) runs 24 h/day",
                "check whether it can be switched off for part of the day")
        if cat == "refrigeration" and a["watts"] * a["qty"] > 200:
            add("R08", "medium", name, f"{name} draws {a['watts'] * a['qty']:g} W (> 200 W)",
                "check the door seal, star rating and age; keep it away from heat")
        if cat == "entertainment" and h > 6:
            add("R09", "low", name, f"{name} runs {h:g} h/day (> 6 h)",
                "cut screen time or enable eco / power-saving mode")
        if cat == "pump" and h > 1.5:
            add("R10", "low", name, f"{name} runs {h:g} h/day (> 1.5 h)",
                "use a timer or float switch to avoid overflow / over-running")

    standby = [(a["name"], r["standby_kwh_day"] * DAYS_PER_MONTH) for a, r in zip(apps, ev["rows"])
               if a["hours"] > 0 and r["standby_kwh_day"] > 0]
    standby_total = sum(k for _, k in standby)
    if standby_total >= 1.0:
        top = ", ".join(n for n, _ in sorted(standby, key=lambda x: -x[1])[:3])
        add("R06", "low", "Whole home",
            f"standby draw adds ~{standby_total:.1f} kWh/month (mainly {top})",
            "switch these off at the socket when not in use", standby_total)

    ns = tariff.next_slab(ev["kwh_month"])
    if ns and ns[0] <= 15 and ns[2] > ns[1]:
        add("R11", "medium", "Whole home",
            f"monthly usage is {ev['kwh_month']:.0f} units, only {ns[0]:.0f} below the next slab",
            f"trim usage to stay in the Rs {ns[1]:g}/unit slab instead of Rs {ns[2]:g}/unit")
    if actual_kwh_month and actual_kwh_month > 0:
        diff = (ev["kwh_month"] - actual_kwh_month) / actual_kwh_month
        if abs(diff) > 0.25:
            word = "higher" if diff > 0 else "lower"
            add("R12", "low", "Whole home",
                f"estimate ({ev['kwh_month']:.0f} units) is {abs(diff) * 100:.0f}% {word} than your bill ({actual_kwh_month:.0f} units)",
                "re-check hours, wattage and any appliances you have not added")
    if ev["kwh_month"] > 400:
        add("R13", "medium", "Whole home", f"monthly usage is {ev['kwh_month']:.0f} kWh (> 400)",
            "review the biggest loads first - see the share chart")

    order = {"high": 0, "medium": 1, "low": 2}
    found.sort(key=lambda f: order[f["severity"]])
    return found


def efficiency_score(rules: list[dict]) -> tuple[int, str]:
    penalty = {"high": 12, "medium": 6, "low": 3}
    score = max(0, 100 - sum(penalty[r["severity"]] for r in rules))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "E"
    return score, grade


# --------------------------------------------------------------------------
# 3 + 4. CSP (backtracking) + Hill Climbing
# --------------------------------------------------------------------------
def _domain(a: dict, step: float = STEP) -> list[float]:
    hi, lo = a["hours"], min(a["min_hours"], a["hours"])
    if hi <= 0:
        return [0.0]
    vals = {round(hi, 4), round(lo, 4)}
    v = hi
    while v - step >= lo - EPS:
        v -= step
        vals.add(round(v, 4))
    return sorted(vals)


def optimize(apps: list[dict], tariff: Tariff, comfort_target: float = 0.7,
             cap_kwh_day: float | None = None, restarts: int = 12, seed: int = 42,
             max_iter: int = 400) -> dict:
    n = len(apps)
    dom = [_domain(a) for a in apps]
    W = sum(a["priority"] for a in apps if a["hours"] > 0) or 1.0
    kw = [[kwh_day(a, h) for h in dom[i]] for i, a in enumerate(apps)]
    cm = [[(a["priority"] * h / a["hours"]) if a["hours"] > 0 else 0.0 for h in dom[i]]
          for i, a in enumerate(apps)]
    need = comfort_target * W

    def cost_of(total_day: float) -> float:
        return tariff.monthly_cost(total_day * DAYS_PER_MONTH)

    def ok(comf: float, tot: float) -> bool:
        return comf >= need - EPS and (cap_kwh_day is None or tot <= cap_kwh_day + EPS)

    # ---- CSP: backtracking with forward-checking style bounds ----
    order = sorted(range(n), key=lambda i: (len(dom[i]), -max(kw[i])))
    suf_comf = [0.0] * (n + 1)
    suf_kw = [0.0] * (n + 1)
    for d in range(n - 1, -1, -1):
        i = order[d]
        suf_comf[d] = suf_comf[d + 1] + max(cm[i])
        suf_kw[d] = suf_kw[d + 1] + min(kw[i])
    nodes = [0]

    def _backtrack(rng: random.Random | None):
        state = [0] * n

        def bt(d: int, comf: float, tot: float):
            nodes[0] += 1
            if nodes[0] > BACKTRACK_NODE_LIMIT:
                return None
            if d == n:
                return state[:] if ok(comf, tot) else None
            i = order[d]
            ks = list(range(len(dom[i]) - 1, -1, -1))     # closest to current usage first
            if rng is not None:
                rng.shuffle(ks)
            for k in ks:
                c2, t2 = comf + cm[i][k], tot + kw[i][k]
                if c2 + suf_comf[d + 1] < need - EPS:      # cannot reach comfort target
                    continue
                if cap_kwh_day is not None and t2 + suf_kw[d + 1] > cap_kwh_day + EPS:   # cannot meet cap
                    continue
                state[i] = k
                res = bt(d + 1, c2, t2)
                if res is not None:
                    return res
            return None

        return bt(0, 0.0, 0.0)

    original_state = [len(dom[i]) - 1 for i in range(n)]
    min_possible = sum(min(kw[i]) for i in range(n))
    first = _backtrack(None)
    if first is None:
        reason = ("The daily kWh cap is lower than the minimum possible usage "
                  f"({min_possible:.2f} kWh/day with every appliance at its minimum hours)."
                  if cap_kwh_day is not None and cap_kwh_day < min_possible - EPS
                  else "No usage plan satisfies the comfort target and the cap together. Relax one of them.")
        return {"feasible": False, "message": reason, "backtrack_nodes": nodes[0]}

    # ---- Hill climbing (steepest descent on monthly cost) ----
    def climb(start: list[int]):
        s = start[:]
        tot = sum(kw[i][s[i]] for i in range(n))
        comf = sum(cm[i][s[i]] for i in range(n))
        cur = cost_of(tot)
        trace, its = [cur], 0
        for _ in range(max_iter):
            best = None   # (cost, moves, tot, comf)
            for i in range(n):
                for dlt in (-1, 1):
                    k = s[i] + dlt
                    if 0 <= k < len(dom[i]):
                        t2 = tot - kw[i][s[i]] + kw[i][k]
                        c2 = comf - cm[i][s[i]] + cm[i][k]
                        if ok(c2, t2):
                            c = cost_of(t2)
                            if c < cur - MIN_GAIN and (best is None or c < best[0] - EPS):
                                best = (c, [(i, k)], t2, c2)
            for i in range(n):                      # swap moves: cut i, give back to j
                if s[i] - 1 < 0:
                    continue
                for j in range(n):
                    if j == i or s[j] + 1 >= len(dom[j]):
                        continue
                    t2 = tot - kw[i][s[i]] + kw[i][s[i] - 1] - kw[j][s[j]] + kw[j][s[j] + 1]
                    c2 = comf - cm[i][s[i]] + cm[i][s[i] - 1] - cm[j][s[j]] + cm[j][s[j] + 1]
                    if ok(c2, t2):
                        c = cost_of(t2)
                        if c < cur - MIN_GAIN and (best is None or c < best[0] - EPS):
                            best = (c, [(i, s[i] - 1), (j, s[j] + 1)], t2, c2)
            if best is None:
                break
            for i, k in best[1]:
                s[i] = k
            cur, tot, comf = best[0], best[2], best[3]
            trace.append(cur)
            its += 1
        return s, cur, comf, trace, its

    rng = random.Random(seed)
    best_run = climb(first)
    best_idx, total_its, restarts_done = 0, best_run[4], 0
    for r in range(1, restarts + 1):
        start = _backtrack(rng)
        if start is None:
            continue
        restarts_done += 1
        run = climb(start)
        total_its += run[4]
        if run[1] < best_run[1] - EPS or (abs(run[1] - best_run[1]) <= EPS and run[2] > best_run[2] + EPS):
            best_run, best_idx = run, r

    s, final_cost, _, trace, its = best_run
    return {
        "feasible": True,
        "hours": [dom[i][s[i]] for i in range(n)],
        "trace": trace,
        "backtrack_nodes": nodes[0],
        "iterations": total_its,
        "restarts": restarts_done,
        "best_run": best_idx,
    }


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------
def _num(v, name, lo, hi, errors, default=None, integer=False):
    if v is None or v == "":
        if default is not None:
            return default
        errors.append(f"{name} is required.")
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        errors.append(f"{name} must be a number.")
        return None
    if math.isnan(x) or math.isinf(x) or x < lo or x > hi:
        errors.append(f"{name} must be between {lo:g} and {hi:g}.")
        return None
    return int(round(x)) if integer else x


def parse_request(data: dict) -> tuple[list[dict], dict, list[str]]:
    errors: list[str] = []
    raw = data.get("appliances") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        return [], {}, ["Add at least one appliance."]
    if len(raw) > MAX_APPLIANCES:
        return [], {}, [f"Please use at most {MAX_APPLIANCES} appliances."]

    apps = []
    for idx, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            errors.append(f"Row {idx}: invalid data.")
            continue
        errs: list[str] = []
        name = str(item.get("name", "")).strip()[:60]
        label = name or f"Row {idx}"
        if not name:
            errs.append(f"Row {idx}: name is required.")
        qty = _num(item.get("qty"), f"{label} quantity", 1, 50, errs, default=1, integer=True)
        watts = _num(item.get("watts"), f"{label} watts", 0.1, 10000, errs)
        hours = _num(item.get("hours"), f"{label} hours/day", 0, 24, errs)
        step_default = round((hours or 0) * 0.5 / STEP) * STEP if hours is not None else 0
        min_h = _num(item.get("min_hours"), f"{label} min hours", 0, 24, errs, default=step_default)
        prio = _num(item.get("priority"), f"{label} priority", 1, 5, errs, default=3, integer=True)
        stby = _num(item.get("standby_w"), f"{label} standby watts", 0, 100, errs, default=0.0)
        if not errs and min_h is not None and hours is not None and min_h > hours:
            min_h = hours       # cannot demand less than the user's own usage
        cat = str(item.get("category", "other"))
        key = str(item.get("key", ""))[:30]
        errors.extend(errs)
        if not errs:
            apps.append({"key": key, "name": name, "category": cat if cat in CATEGORIES else "other",
                         "qty": qty, "watts": watts, "hours": hours, "min_hours": min_h,
                         "priority": prio, "standby_w": stby})

    s = data.get("settings") or {}
    mode = s.get("tariff_mode", "flat")
    if mode not in ("flat", "slab"):
        errors.append("Tariff mode must be flat or slab.")
    rate = _num(s.get("tariff_rate"), "Tariff rate", 0.5, 100, errors, default=DEFAULT_FLAT_RATE)
    comfort = _num(s.get("comfort_target"), "Comfort target", 50, 100, errors, default=70)
    cap = _num(s.get("cap_kwh_day"), "Daily kWh cap", 0.1, 1000, errors, default=-1)
    actual = _num(s.get("actual_kwh_month"), "Actual monthly units", 1, 100000, errors, default=-1)
    settings = {"tariff_mode": mode, "tariff_rate": rate,
                "comfort_target": (comfort or 70) / 100.0,
                "cap_kwh_day": None if cap in (None, -1) else cap,
                "actual_kwh_month": None if actual in (None, -1) else actual}
    return apps, settings, errors


# --------------------------------------------------------------------------
# Result layer
# --------------------------------------------------------------------------
def _r(x, nd=2):
    return round(float(x), nd)


def _pack(ev: dict) -> dict:
    return {
        "kwh_day": _r(ev["kwh_day"]), "kwh_month": _r(ev["kwh_month"], 1),
        "cost_day": _r(ev["cost_day"]), "cost_month": _r(ev["cost_month"]),
        "co2_month_kg": _r(ev["co2_month_kg"], 1),
        "rows": [{**r, **{k: _r(r[k], 3) for k in ("kwh_day", "kwh_month", "cost_day", "cost_month", "share", "standby_kwh_day")}}
                 for r in ev["rows"]],
    }


def _reason(a: dict) -> str:
    if a["priority"] <= 2:
        return "Low priority - cheapest comfort to give up"
    if a["watts"] * a["qty"] >= 1000:
        return "High-wattage appliance - biggest saving per hour trimmed"
    return "Trimmed to meet the comfort target at lowest cost"


def run_full(apps: list[dict], settings: dict) -> dict:
    tariff = Tariff(settings["tariff_mode"], settings["tariff_rate"])
    before = evaluate(apps, tariff)
    rules = run_rules(apps, before, tariff, settings.get("actual_kwh_month"))
    score, grade = efficiency_score(rules)
    out = {
        "tariff": tariff.describe(),
        "analysis": {"before": _pack(before), "rules": rules, "score": score, "grade": grade},
    }
    opt = optimize(apps, tariff, settings["comfort_target"], settings.get("cap_kwh_day"))
    if not opt["feasible"]:
        out["optimization"] = {"feasible": False, "message": opt["message"], "backtrack_nodes": opt["backtrack_nodes"]}
        return out

    after = evaluate(apps, tariff, opt["hours"])
    plan, moves = [], []
    for a, rb, ra in zip(apps, before["rows"], after["rows"]):
        delta = ra["hours"] - rb["hours"]
        plan.append({"name": a["name"], "qty": a["qty"], "before_hours": rb["hours"], "after_hours": ra["hours"],
                     "delta_hours": _r(delta), "kwh_month_before": _r(rb["kwh_month"], 1),
                     "kwh_month_after": _r(ra["kwh_month"], 1),
                     "cost_month_saved": _r(rb["cost_month"] - ra["cost_month"])})
        if delta < -EPS:
            moves.append({"name": a["name"], "text": f"Reduce {a['name']} from {rb['hours']:g} h to {ra['hours']:g} h per day",
                          "reason": _reason(a)})
    monthly_saved = before["cost_month"] - after["cost_month"]
    out["optimization"] = {
        "feasible": True,
        "plan": plan, "moves": moves,
        "after": _pack(after),
        "comfort_retention": _r(comfort_retention(apps, opt["hours"]) * 100, 1),
        "comfort_target": _r(settings["comfort_target"] * 100, 0),
        "savings": {
            "daily_cost": _r(monthly_saved / DAYS_PER_MONTH),
            "monthly_cost": _r(monthly_saved),
            "yearly_cost": _r(monthly_saved * 12),
            "percent": _r((monthly_saved / before["cost_month"] * 100) if before["cost_month"] > 0 else 0, 1),
            "monthly_kwh": _r(before["kwh_month"] - after["kwh_month"], 1),
            "co2_month_kg": _r(before["co2_month_kg"] - after["co2_month_kg"], 1),
        },
        "trace": [_r(t) for t in opt["trace"]],
        "stats": {"backtrack_nodes": opt["backtrack_nodes"], "iterations": opt["iterations"],
                  "restarts": opt["restarts"], "best_run": opt["best_run"]},
    }
    return out


def what_if(apps: list[dict], settings: dict, hours: list[float]) -> dict:
    """Evaluate a user-chosen usage state against the original."""
    tariff = Tariff(settings["tariff_mode"], settings["tariff_rate"])
    hours = [max(0.0, min(float(h), a["hours"])) for a, h in zip(apps, hours)]
    before, after = evaluate(apps, tariff), evaluate(apps, tariff, hours)
    saved = before["cost_month"] - after["cost_month"]
    return {
        "after": _pack(after),
        "monthly_saved": _r(saved), "daily_saved": _r(saved / DAYS_PER_MONTH),
        "kwh_saved": _r(before["kwh_month"] - after["kwh_month"], 1),
        "percent": _r((saved / before["cost_month"] * 100) if before["cost_month"] > 0 else 0, 1),
        "comfort_retention": _r(comfort_retention(apps, hours) * 100, 1),
    }
