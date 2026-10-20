# ⚡ EcoWise AI – Smart Energy Advisor

A rule-based AI web app that estimates appliance-level energy use and cost, **explains** inefficiencies with
transparent IF–THEN rules, and **optimizes** usage to find a cheaper valid plan using CSP + Hill Climbing.

> Presented by **Roshni R** · Roll No **240701443** · Dept. CSE

---

## 🚀 Run it in VS Code (3 minutes)

**Requirements:** Python 3.9+ ([python.org](https://www.python.org/downloads/) – tick *"Add Python to PATH"* on Windows). Nothing else.

1. Extract the zip, then in VS Code: **File → Open Folder…** → choose the `ecowise-ai` folder.
2. Open the terminal: **Terminal → New Terminal** and run:

**Windows (PowerShell / CMD)**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
*(If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use CMD instead.)*

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

3. Open **http://127.0.0.1:5000** in your browser.

**Even easier:** double-click `run.bat` (Windows) or run `bash run.sh` (macOS/Linux) – it does steps 2-3 for you.
You can also press **F5** in VS Code (choose the interpreter `.venv` when prompted) to run/debug.

### Demo login
| Email | Password |
|---|---|
| `demo@ecowise.ai` | `Demo@1234` |

Or click **Create an account**. (To disable the demo account set the env variable `ECOWISE_SEED_DEMO=0` before first run.)

---

## ✨ Features

**From the project presentation**
- **Calculate** – daily/monthly kWh and cost per appliance (with standby draw)
- **Explain** – 13 transparent IF–THEN rules; each finding shows the exact condition that fired
- **Validate** – appliance-specific limits (min/max hours) + comfort & daily-cap constraints (CSP)
- **Optimize** – backtracking finds valid starting states, **Hill Climbing** (steepest descent + swap moves + random restarts) finds the cheapest valid plan
- **Compare** – before/after cost, daily/monthly/yearly savings, CO₂ avoided
- **Present** – responsive web dashboard (Flask API at `/api/optimize`)

**Added on top (the "Future Enhancements" from the slides, plus extras)**
- 🔐 **Login / Register / Logout**, password hashing, CSRF protection, login lockout, change password, delete account
- 🗄️ **Persistent database (SQLite)** – no setup needed, created automatically in `instance/`
- 🗂️ **History** – save analyses, re-open them, delete them, and see a cost-trend chart
- 💰 **Tariff slabs** – flat rate or slab-based billing (illustrative sample slabs)
- 🎚️ **What-if simulator** – drag sliders and watch the bill change live
- 🧾 **Bill check** – enter your last bill's units to compare with the estimate
- 📊 **Efficiency score (A–E)**, appliance share donut chart, before/after bars, optimizer progress chart
- 🌱 **CO₂ estimate**, standby-load detection, slab-boundary warnings
- ⬇️ **CSV export** and 🖨️ **print** view
- 🌓 **Dark / light theme**, mobile-friendly layout
- 🧪 **20 automated tests**

---

## 🧠 How the AI works

```
Browser (HTML/CSS/JS)  ──►  Flask  /api/optimize  ──►  engine.py
                                                          ├─ evaluate()    energy + cost
                                                          ├─ run_rules()   IF-THEN reasoning
                                                          ├─ _backtrack()  CSP: valid start state
                                                          └─ optimize()    Hill Climbing
```

**CSP model**
- *Variables:* hours/day of each appliance
- *Domains:* from `Min hrs` up to the current hours, in 0.25 h steps
- *Constraints:* (1) per-appliance min/max hours, (2) **comfort retained ≥ target** (priority-weighted), (3) optional **daily kWh cap**

**Hill Climbing** – starting from a valid state, it repeatedly takes the best neighbouring move
(±0.25 h on one appliance, or *cut one / give back to another*) that lowers the monthly bill while staying valid,
until no move helps. Random restarts (seeded, so results are repeatable) avoid poor local optima.
On small cases it was verified against brute force and finds the true optimum.

> **Tip:** The *Min hrs* column is what you are willing to accept, and *Priority* (1 easy to cut … 5 essential) sets how
> much comfort each appliance carries. Set these realistically for realistic recommendations.

---

## 📁 Project structure

```
ecowise-ai/
├── app.py              Flask app: auth, database, JSON API
├── engine.py           AI logic: calculator, rules, CSP/backtracking, hill climbing
├── requirements.txt    Flask only
├── run.bat / run.sh    One-click start
├── templates/          login, register, dashboard, history, settings, base, error
├── static/
│   ├── css/style.css
│   └── js/             dashboard.js, charts.js (offline SVG charts), auth.js, history.js, common.js
├── tests/              test_engine.py, test_app.py
├── instance/           (auto-created) ecowise.db + secret.key
└── .vscode/            launch.json (F5), settings.json
```

## 🔌 API (login required, JSON, CSRF header `X-CSRF-Token`)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/optimize` | Analyze + rules + optimize |
| POST | `/api/calculate` | What-if evaluation for chosen hours |
| POST | `/api/history` | Save an analysis |
| GET / DELETE | `/api/history/<id>` | Load / delete a saved analysis |

Request body: `{"appliances":[{name, qty, watts, hours, min_hours, priority, standby_w, category}], "settings":{tariff_mode, tariff_rate, comfort_target, cap_kwh_day, actual_kwh_month}}`

---

## 🧪 Run the tests
```bash
python -m unittest discover -s tests -v
```

## ⚙️ Customising
- **Tariff slabs:** edit `SAMPLE_SLABS` in `engine.py` to match your state/DISCOM.
- **Appliance library:** edit `PRESETS` in `engine.py`.
- **Rules:** add a rule in `run_rules()` and a line in `RULE_CATALOG`.
- **Port:** `set PORT=8000` (Windows) / `PORT=8000 python app.py` (macOS/Linux).
- **Reset everything:** stop the app and delete the `instance/` folder.

## 🛠️ Troubleshooting
| Problem | Fix |
|---|---|
| `python` not found | Reinstall Python with *Add to PATH*, or try `py -3` / `python3` |
| `No module named flask` | Activate the venv (`.venv\Scripts\activate`) then `pip install -r requirements.txt` |
| Port 5000 busy (macOS AirPlay) | `PORT=5001 python app.py` |
| "Invalid CSRF token" | Refresh the page (the session expired) |

## ⚠️ Notes & limitations
- All savings are **estimates**; they depend on real usage and actual tariffs. The sample slab rates are illustrative – verify with your electricity board.
- CO₂ uses an approximate grid factor of 0.82 kg/kWh.
- Appliance data is entered manually (no smart-meter integration).
- For real deployment: set a `SECRET_KEY` environment variable, run behind HTTPS with a production server (e.g. gunicorn/waitress), and disable the demo account.
