"""Tests for resin life estimation. No Home Assistant required.

    python test_resin.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "custom_components", "culligan_azure"))
import resin  # noqa: E402

DAY = 86400.0
FAILURES = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' -- ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(name)


def build(days: int, start_cap: float, fade_per_year: float,
          regens_per_day: float = 1.0, step_days: int = 7):
    """Synthesize cumulative samples for a unit whose capacity fades linearly."""
    samples, gallons, regens, t = [], 0.0, 0.0, 0.0
    for d in range(0, days + 1, step_days):
        cap = start_cap - fade_per_year * (d / 365.25)
        cap = max(cap, 1.0)
        n = regens_per_day * step_days
        if d > 0:
            regens += n
            gallons += n * cap
        t = d * DAY
        samples.append({"ts": t, "gallons": gallons, "regens": regens})
    return samples


print("=== insufficient / collecting ===")
r = resin.analyse([])
check("empty is insufficient_data", r["status"] == "insufficient_data", r["status"])
check("empty has no estimate", r["years_remaining"] is None)

r = resin.analyse(build(14, 243, 20, step_days=7))
check("short history not extrapolated",
      r["status"] in ("insufficient_data", "collecting"), r["status"])

print("\n=== clear degradation (243 gal/cycle, -20/yr, 2 years) ===")
r = resin.analyse(build(730, 243, 20))
check("status ok", r["status"] == "ok", r["status"])
check("detects fade direction", r["fade_per_year"] > 0, f"{r['fade_per_year']}/yr")
check("fade magnitude ~20/yr", 15 < r["fade_per_year"] < 25, str(r["fade_per_year"]))
check("baseline near 243", 235 < r["baseline_capacity"] < 250, str(r["baseline_capacity"]))
check("current below baseline", r["current_capacity"] < r["baseline_capacity"])
check("years_remaining positive", r["years_remaining"] > 0, str(r["years_remaining"]))
check("high confidence on clean data", r["confidence"] > 0.9, str(r["confidence"]))
# baseline 243, EOL at 60% = 145.8; after 2yr at -20/yr current ~203
# remaining = (203 - 145.8)/20 = ~2.9 years
check("years_remaining plausible", 1.5 < r["years_remaining"] < 5,
      str(r["years_remaining"]))

print("\n=== healthy unit, no measurable fade ===")
r = resin.analyse(build(730, 243, 0.0))
check("no_degradation_detected", r["status"] == "no_degradation_detected", r["status"])
check("refuses to claim infinite life", r["years_remaining"] is None)

print("\n=== already spent ===")
r = resin.analyse(build(2000, 243, 40))
check("at_end_of_life or ok-with-low-remaining",
      r["status"] in ("at_end_of_life", "ok"), r["status"])
check("remaining is small", (r["years_remaining"] or 0) < 2, str(r["years_remaining"]))

print("\n=== robustness ===")
s = build(730, 243, 20)
s.append({"ts": s[-1]["ts"] + DAY, "gallons": 0.0, "regens": 0.0})  # counter reset
r = resin.analyse(s)
check("counter reset does not crash", isinstance(r, dict))
check("counter reset does not invent a negative life",
      r["years_remaining"] is None or r["years_remaining"] >= 0,
      str(r["years_remaining"]))

r = resin.analyse([{"ts": 0, "gallons": 100, "regens": 0}] * 10)
check("zero regens handled", r["years_remaining"] is None, r["status"])

bad = [{"nope": 1}, {"ts": 0, "gallons": "x", "regens": 1}]
check("malformed samples ignored", isinstance(resin.analyse(bad), dict))

print("\n=== windowing ===")
w = resin.windowed_capacities(build(90, 243, 0.0, regens_per_day=1.0, step_days=7))
check("windows produced", len(w) > 5, f"{len(w)} windows")
check("window capacity near truth",
      all(235 < v < 250 for _, v in w), str([round(v) for _, v in w][:4]))

w2 = resin.windowed_capacities(build(30, 243, 0.0, regens_per_day=0.05, step_days=1))
check("sparse regens do not produce noisy windows", len(w2) <= 2, f"{len(w2)} windows")

print("\n=== pruning keeps baseline and current ===")
many = build(2000, 243, 10, step_days=1)
p = resin.prune(many, max_samples=100)
check("pruned to cap", len(p) <= 100, str(len(p)))
check("oldest kept", p[0]["ts"] == many[0]["ts"])
check("newest kept", p[-1]["ts"] == many[-1]["ts"])

print("\n=== lifetime average (headline figure) ===")
lt = resin.capacity_per_cycle_lifetime(
    {"total_water_usage_since_install_tank_1": 182179, "total_regens_since_install": 749}
)
check("lifetime avg ~243", 240 < lt < 246, str(round(lt, 1)))
check("lifetime avg handles zero regens",
      resin.capacity_per_cycle_lifetime(
          {"total_water_usage_since_install_tank_1": 100, "total_regens_since_install": 0}
      ) is None)

print("\n=== cycle age (accelerated wear from over-regeneration) ===")
REAL = {"total_regens_since_install": 749, "days_since_install": 747}
check("cycle_age ~10.1 years",
      abs(resin.cycle_age_years(REAL, 4.902) - 10.05) < 0.2,
      str(round(resin.cycle_age_years(REAL, 4.902), 2)))
check("acceleration ~4.9x",
      abs(resin.cycle_age_acceleration(REAL, 4.902) - 4.9) < 0.2,
      str(round(resin.cycle_age_acceleration(REAL, 4.902), 2)))
check("excess cycles ~597",
      abs(resin.excess_cycles_lifetime(REAL, 4.902) - 597) < 3,
      str(round(resin.excess_cycles_lifetime(REAL, 4.902))))

CORRECT = {"total_regens_since_install": 152, "days_since_install": 747}
check("correct unit: cycle age == calendar age",
      abs(resin.cycle_age_years(CORRECT, 4.902) - 747 / 365.25) < 0.1,
      str(round(resin.cycle_age_years(CORRECT, 4.902), 2)))
check("correct unit: acceleration ~1.0",
      abs(resin.cycle_age_acceleration(CORRECT, 4.902) - 1.0) < 0.05,
      str(round(resin.cycle_age_acceleration(CORRECT, 4.902), 3)))
check("correct unit: no excess cycles",
      resin.excess_cycles_lifetime(CORRECT, 4.902) < 1.0,
      str(round(resin.excess_cycles_lifetime(CORRECT, 4.902), 2)))

check("under-regenerating clamps excess at zero",
      resin.excess_cycles_lifetime(
          {"total_regens_since_install": 50, "days_since_install": 747}, 4.902) == 0.0)
check("missing expected interval is None",
      resin.cycle_age_years(REAL, None) is None)
check("zero expected interval is None",
      resin.cycle_age_years(REAL, 0) is None)
check("missing datapoints is None",
      resin.cycle_age_acceleration({}, 4.902) is None)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("all checks passed")
