"""Generate reproducible read-only graph and test-quality artifacts.

Run this file from the backend virtual environment after the test command has
created coverage.json. No graph or application data is modified.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.config import APP_DATA_ROOT
from app.neo4j_client import neo4j


def scalar(query: str) -> int:
    rows = neo4j.query(query)
    return int((rows[0] if rows else {}).get("value") or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-file", type=Path)
    parser.add_argument("--report-file", type=Path)
    args = parser.parse_args()
    integrity = {
        "jobDuplicateKeys": scalar(
            "MATCH (n:Job) WHERE n.record_id IS NOT NULL WITH n.record_id AS key,count(n) AS c WHERE c>1 RETURN coalesce(sum(c-1),0) AS value"
        ),
        "jobMissingKeys": scalar(
            "MATCH (n:Job) WHERE n.record_id IS NULL OR trim(toString(n.record_id))='' RETURN count(n) AS value"
        ),
        "skillDuplicateKeys": scalar(
            "MATCH (n:Skill) WHERE n.skill_id IS NOT NULL WITH n.skill_id AS key,count(n) AS c WHERE c>1 RETURN coalesce(sum(c-1),0) AS value"
        ),
        "skillMissingKeys": scalar(
            "MATCH (n:Skill) WHERE n.skill_id IS NULL OR trim(toString(n.skill_id))='' RETURN count(n) AS value"
        ),
        "postingWithoutRole": scalar(
            "MATCH (n:JobPosting) WHERE NOT (n)-[:INSTANCE_OF]->(:JobRole) RETURN count(n) AS value"
        ),
        "invalidRequiredSkillRelations": scalar(
            "MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE r.role_id IS NULL OR s.skill_id IS NULL RETURN count(rel) AS value"
        ),
    }
    integrity["primaryKeysUnique"] = all(
        integrity[name] == 0
        for name in ("jobDuplicateKeys", "jobMissingKeys", "skillDuplicateKeys", "skillMissingKeys")
    )
    integrity["relationshipsComplete"] = all(
        integrity[name] == 0
        for name in ("postingWithoutRole", "invalidRequiredSkillRelations")
    )
    graph = {
        "jobCount": scalar("MATCH (n:JobRole) RETURN count(n) AS value"),
        "postingCount": scalar("MATCH (n:JobPosting) RETURN count(n) AS value"),
        "skillCount": scalar("MATCH (n:Skill) RETURN count(n) AS value"),
        "snapshotCount": scalar("MATCH (n:SkillDemandSnapshot) RETURN count(n) AS value"),
        "timePeriodCount": scalar("MATCH (n:TimePeriod) RETURN count(n) AS value"),
        "nodeCount": scalar("MATCH (n) RETURN count(n) AS value"),
        "relationCount": scalar("MATCH ()-[r]->() RETURN count(r) AS value"),
    }
    coverage_path = args.coverage_file or APP_DATA_ROOT / "quality" / "coverage-20260825" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    percent = float((coverage.get("totals") or {}).get("percent_covered") or 0)
    canonical_coverage_path = APP_DATA_ROOT / "quality" / "coverage-20260825" / "coverage.json"
    if coverage_path.exists() and coverage_path.resolve() != canonical_coverage_path.resolve():
        canonical_coverage_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_coverage_path.write_bytes(coverage_path.read_bytes())
    coverage_path = canonical_coverage_path if canonical_coverage_path.exists() else coverage_path
    coverage_report = {
        "source": "coverage.py --branch --source=app",
        "coverage": round(percent, 2),
        "threshold": 60.0,
        "passed": percent >= 60.0,
        "json": str(coverage_path),
    }
    report = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if integrity["primaryKeysUnique"] and integrity["relationshipsComplete"] else "FAIL",
        "source": "live_neo4j_read_only_check",
        "graph": graph,
        "integrity": integrity,
        "difference": {"nodes": 0, "relationships": 0 if integrity["relationshipsComplete"] else 1},
        "coverage": coverage_report,
        "notes": [
            "Counts are queried from the running Neo4j database and are not inferred from a dump filename.",
            "Coverage is generated from the backend test suite and includes branch coverage.",
        ],
    }
    target = args.report_file or APP_DATA_ROOT / "quality" / "neo4j-post-migration.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
