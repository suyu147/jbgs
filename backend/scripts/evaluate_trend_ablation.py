"""Quantify the effect of time-volume correction and robust smoothing."""

from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import APP_DATA_ROOT  # noqa: E402
from app.neo4j_client import neo4j  # noqa: E402
from app.services import _normalize_role_demand_points, _published_role_clause  # noqa: E402


SUITE = "trend-ablation-20260825-v01"


def max_jump(values: list[float]) -> float:
    return max((abs(right - left) for left, right in zip(values, values[1:])), default=0.0)


def coefficient_of_variation(values: list[float]) -> float:
    mean = statistics.fmean(values) if values else 0.0
    return statistics.pstdev(values) / mean if mean else 0.0


def main() -> int:
    target = APP_DATA_ROOT / "quality" / SUITE
    target.mkdir(parents=True, exist_ok=True)
    role_rows = neo4j.query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE {_published_role_clause()} "
        "AND j.time_status='valid_monthly' "
        "AND toString(coalesce(j.posted_month_canonical,'')) =~ '\\d{4}-\\d{2}' "
        "WITH r,toString(j.posted_month_canonical) AS period,count(j) AS postingCount "
        "WITH r,collect({period:period,value:postingCount,sampleSize:postingCount}) AS points,"
        "sum(postingCount) AS sampleSize,count(*) AS months "
        "WHERE months>=3 AND sampleSize>=6 "
        "RETURN r.role_id AS roleId,r.role_name AS roleName,points,sampleSize "
        "ORDER BY sampleSize DESC,r.role_id LIMIT 24"
    )
    market_rows = neo4j.query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE {_published_role_clause()} "
        "AND j.time_status='valid_monthly' "
        "AND toString(coalesce(j.posted_month_canonical,'')) =~ '\\d{4}-\\d{2}' "
        "WITH toString(j.posted_month_canonical) AS period,count(j) AS marketCount "
        "RETURN period,marketCount ORDER BY period"
    )
    periods = sorted(str(item["period"]) for item in market_rows)
    recent_periods = periods[-6:]
    recent_reference = neo4j.query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE {_published_role_clause()} "
        "AND j.time_status='valid_monthly' AND toString(j.posted_month_canonical) IN $periods "
        "WITH r,count(j) AS recentCount RETURN max(recentCount) AS value",
        {"periods": recent_periods},
    )
    max_recent = max(int((recent_reference[0] if recent_reference else {}).get("value") or 0), 1)
    rows = []
    for role in role_rows:
        raw_map = {str(item["period"]): float(item["value"]) for item in role.get("points") or []}
        raw_values = [raw_map.get(period, 0.0) for period in periods]
        raw_max = max(raw_values) or 1.0
        raw_index = [value / raw_max * 100 for value in raw_values]
        adjusted = _normalize_role_demand_points(role.get("points") or [], market_rows, max_recent)
        adjusted_values = [float(item["value"]) for item in adjusted]
        raw_jump = max_jump(raw_index)
        adjusted_jump = max_jump(adjusted_values)
        rows.append(
            {
                "role_id": role["roleId"],
                "role_name": role["roleName"],
                "sample_size": int(role.get("sampleSize") or 0),
                "observed_months": len(raw_map),
                "raw_zero_months": sum(value == 0 for value in raw_values),
                "adjusted_zero_months": sum(value == 0 for value in adjusted_values),
                "raw_max_jump": round(raw_jump, 2),
                "adjusted_max_jump": round(adjusted_jump, 2),
                "jump_reduction_pct": round((raw_jump - adjusted_jump) / raw_jump * 100, 2) if raw_jump else 0,
                "raw_variation": round(coefficient_of_variation(raw_index), 4),
                "adjusted_variation": round(coefficient_of_variation(adjusted_values), 4),
            }
        )
    reductions = [float(item["jump_reduction_pct"]) for item in rows]
    summary = {
        "suite": SUITE,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "roleSamples": len(rows),
        "marketMonths": len(periods),
        "rawZeroMonths": sum(int(item["raw_zero_months"]) for item in rows),
        "adjustedZeroMonths": sum(int(item["adjusted_zero_months"]) for item in rows),
        "medianMaxJumpReduction": round(statistics.median(reductions), 2) if reductions else 0,
        "meanRawVariation": round(statistics.fmean(float(item["raw_variation"]) for item in rows), 4) if rows else 0,
        "meanAdjustedVariation": round(statistics.fmean(float(item["adjusted_variation"]) for item in rows), 4) if rows else 0,
        "method": "raw posting-count index versus market-share correction, empirical Bayes shrinkage and trailing robust smoothing",
        "passed": bool(rows and all(int(item["adjusted_zero_months"]) == 0 for item in rows) and statistics.median(reductions) > 50),
    }
    with (target / "role_trend_ablation.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (target / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
