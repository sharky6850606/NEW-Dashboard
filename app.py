from flask import Flask, render_template, abort
import requests
from collections import defaultdict

app = Flask(__name__)

# =============================
# CONFIG
# =============================
SHEET_ID = "175ErynCbO3X82AcPgc9QHeg4846G6Jk2EQmcpfKnL7A"

TABS = {
    "summary": "Dashboard_Summary",
    "countries": "Country_Profiles",
    "pefa": "PEFA_Tracker",
    "practices": "Good_Practices",
    "missions": "Joint_Missions",
    "methodology": "PEFA_Score_Methodology"
}

PILLAR_COLUMNS = [
    "Pillar I: Budget Reliability (PI-1 to PI-3)",
    "Pillar II: Transparency of Public Finances (PI-4 to PI-9)",
    "Pillar III: Assets, Liabilities & Fiscal Strategy (PI-10 to PI-18)",
    "Pillar IV: Predictability & Control in Execution (PI-19 to PI-26)",
    "Pillar V: Accounting, Reporting & External Scrutiny (PI-27 to PI-31)"
]

TA_COLUMNS = [
    "Public Financial Management",
    "Revenue Administration",
    "Real Sector Statistics",
    "Debt Management",
    "Financial Sector Supervision",
    "Macroeconomic Frameworks",
    "Macroeconomic Programming and Analysis",
    "Government Finance Statistics",
    "Prices",
    "External Sector"
]

# =============================
# HELPERS
# =============================
def fetch(tab_key: str):
    url = f"https://opensheet.elk.sh/{SHEET_ID}/{TABS[tab_key]}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def norm_code(v):
    return str(v or "").replace("\u00a0", "").strip().upper()

def score_band(score):
    if score is None:
        return "N/A"
    try:
        s = float(str(score).strip())
    except Exception:
        return "N/A"
    if s >= 85:
        return "Very Strong"
    elif s >= 70:
        return "Strong"
    elif s >= 55:
        return "Moderate"
    else:
        return "Weak"

def extract_code(row: dict) -> str:
    for k, v in (row or {}).items():
        if "code" in str(k).lower():
            return norm_code(v)
    return ""

def safe_float(v):
    s = str(v or '').strip()
    if not s or s.upper() == 'TBC':
        return None
    try:
        return float(s.replace(',', ''))
    except:
        return None

# =============================
# GLOBAL DATA LOAD
# =============================
def load_all_data():
    country_profiles = fetch("countries")
    pefa_rows = fetch("pefa")
    practices_rows = fetch("practices")
    return country_profiles, pefa_rows, practices_rows

# =============================
# ROUTES
# =============================
@app.route("/")
def overview():
    country_profiles, _, practices_rows = load_all_data()

    # Summary Metrics
    scores = []
    pefa_count = reform_plan_count = gcf_count = 0

    for c in country_profiles:
        val = safe_float(c.get("Overall Score"))
        if val is not None:
            scores.append(val)
        else:
            # keep TBC / blank out of averages
            pass
        if str(c.get("PEFA Count", "")).strip():
            pefa_count += 1
        if str(c.get("Reform Plan", "")).lower() == "yes":
            reform_plan_count += 1
        if str(c.get("GCF Readiness", "")).lower() == "yes":
            gcf_count += 1

    avg_overall_score = sum(scores) / len(scores) if scores else 0

    summary_metrics = {
        "countries_total": len(country_profiles),
        "avg_overall": round(avg_overall_score, 1),
        "pefa_count": pefa_count,
        "reform_plan_count": reform_plan_count,
        "gcf_count": gcf_count,
        "good_practices": len(practices_rows),
    }

    # Score Bands
    band_counts = {b: 0 for b in ["Very Strong", "Strong", "Moderate", "Weak", "N/A"]}
    for c in country_profiles:
        band = score_band(c.get("Overall Score"))
        band_counts[band] += 1

    # Dimension Averages
    dim_sums = defaultdict(float)
    dim_counts = defaultdict(int)

    for row in country_profiles:
        for dim in PILLAR_COLUMNS:
            val = safe_float(row.get(dim))
            if val is not None:
                dim_sums[dim] += val
                dim_counts[dim] += 1

    dimension_avgs = {
        dim: round(dim_sums[dim] / dim_counts[dim], 1) if dim_counts[dim] else 0
        for dim in PILLAR_COLUMNS
    }

    # Country Scores
    country_scores = []
    for c in country_profiles:
        name = c.get("Country") or ""
        code = norm_code(c.get("Code"))
        score = safe_float(c.get("Overall Score"))
        band = score_band(score)
        if name and code:
            country_scores.append({
                "name": name,
                "score": score,
                "band": band,
                "url": f"/country/{code}"
            })
    country_scores.sort(key=lambda x: x["score"], reverse=True)

    # TA Area Data (include zero)
    ta_area_data = {}
    for col in TA_COLUMNS:
        all_scores = []
        for c in country_profiles:
            name = c.get("Country") or ""
            code = norm_code(c.get("Code"))
            score = safe_float(c.get(col))
            if name and code:
                all_scores.append({
                    "name": name,
                    "score": score,
                    "url": f"/country/{code}"
                })
        ta_area_data[col] = sorted(all_scores, key=lambda x: x["score"], reverse=True)

    return render_template(
        "overview.html",
        summary_metrics=summary_metrics,
        band_counts=band_counts,
        dimension_avgs=dimension_avgs,
        country_scores=country_scores,
        ta_area_data=ta_area_data
    )

@app.route("/countries")
def countries():
    rows = fetch("countries")
    countries_list = []
    for r in rows:
        code = norm_code(r.get("Code"))
        overall = safe_float(r.get("Overall Score"))
        band = score_band(overall)
        countries_list.append({
            "Country": r.get("Country") or "",
            "Code": code,
            "Overall Score": overall,
            "Score Band": band,
        })
    countries_list.sort(key=lambda x: x.get("Country") or "")

    map_data = {
        c["Code"]: {
            "name": c["Country"],
            "band": c["Score Band"],
            "score": c["Overall Score"],
            "url": f"/country/{c['Code']}"
        }
        for c in countries_list if c.get("Code")
    }
    return render_template("countries.html", countries=countries_list, map_data=map_data)

@app.route("/country/<code>")
def country(code):
    code = norm_code(code)
    country_profiles, pefa_rows, practices_rows = load_all_data()

    country_row = next((c for c in country_profiles if norm_code(c.get("Code")) == code), None)
    if not country_row:
        abort(404)

    country_obj = {
        "Country": country_row.get("Country") or "",
        "Code": country_row.get("Code") or "",
        "Overall Score": (country_row.get("Overall Score") or "").strip(),
        "Score Band": score_band(safe_float(country_row.get("Overall Score"))),
    }

    dims = {dim: (country_row.get(dim) or "").strip() for dim in PILLAR_COLUMNS}

    country_pefa = []
    for p in pefa_rows:
        if extract_code(p) == code:
            country_pefa.append({
                "assessments": p.get("PEFA_Assessments") or p.get("# PEFA Assessments") or "",
                "latest_year": p.get("Latest PEFA Year") or "",
                "reform_plan": p.get("PFM Reform Plan") or "",
                "other_assessments": p.get("Other PFM & Fiscal Assessments") or "",
                "latest_pfm_activities": (
                    p.get("Latest PFM Activities (PFTAC Country Workplans FY 25/26)") or
                    p.get("Latest PFM Activities") or
                    ""
                ),
                "link": p.get("PEFA Report/Portal Link") or "",
            })

    country_practices = []
    for g in practices_rows:
        if extract_code(g) == code:
            country_practices.append({
                "area": g.get("Practice Area") or "",
                "description": g.get("Description") or "",
                "replicability": g.get("Replicability") or "",
            })

        workplan_link = (country_row.get("Workplan (Link)") or "").strip()
    methodology_rows = fetch("methodology")

return render_template(
        "country.html",
        country=country_obj,
        dims=dims,
        pefa=country_pefa,
        practices=country_practices,
        workplan_link=workplan_link,
        methodology=methodology_rows,
    )

if __name__ == "__main__":
    app.run(debug=True)


# ===============================
# JOINT MISSIONS
# ===============================
from collections import Counter

def load_missions():
    rows = fetch("missions")
    cleaned = []
    for r in rows:
        rid = str(r.get("ID") or "").strip()
        # Skip empty/notes rows
        if not rid:
            continue
        # Quarter header rows often start with "Q"
        if rid.upper().startswith("Q") and "202" in rid:
            cleaned.append({"_type":"quarter", "label": rid})
            continue
        if rid.upper().startswith("M-"):
            cleaned.append({"_type":"mission", **r})
    return cleaned

@app.route("/joint-missions")
def joint_missions():
    rows = load_missions()
    # status counts from missions only
    counts = Counter()
    total = 0
    for r in rows:
        if r.get("_type") != "mission":
            continue
        total += 1
        status = (r.get("Status") or "Not Started").strip()
        counts[status] += 1
    # Convert to plain dict for Jinja/JSON
    status_counts = dict(counts)
    return render_template("joint_missions.html", missions=rows, status_counts=status_counts, total=total)

@app.route("/mission/<mission_id>")
def mission_detail(mission_id):
    rows = load_missions()
    mission = next((r for r in rows if r.get("_type")=="mission" and str(r.get("ID") or "").strip()==mission_id), None)
    if not mission:
        abort(404)
    return render_template("mission_detail.html", mission=mission)
