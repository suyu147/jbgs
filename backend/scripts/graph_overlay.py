from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def query(
    url: str,
    database: str,
    user: str,
    password: str,
    statement: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    payload = {
        "statements": [
            {
                "statement": statement,
                "parameters": parameters or {},
                "resultDataContents": ["row"],
            }
        ]
    }
    request = Request(
        f"{url.rstrip('/')}/db/{database}/tx/commit",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message", "Neo4j query failed"))
    result = body["results"][0]
    columns = result["columns"]
    return [dict(zip(columns, item["row"], strict=False)) for item in result["data"]]


def export_overlay(args: argparse.Namespace) -> None:
    version_rows = query(
        args.url,
        args.database,
        args.user,
        args.password,
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion) "
        "RETURN r.role_id AS roleId,properties(r) AS roleProperties,"
        "v.version_id AS versionId,properties(v) AS versionProperties "
        "ORDER BY r.role_id,v.published_at,v.version_id",
    )
    role_map: dict[str, dict[str, Any]] = {}
    versions: list[dict[str, Any]] = []
    for row in version_rows:
        role_id = str(row["roleId"])
        role_map[role_id] = {"role_id": role_id, "props": row["roleProperties"]}
        versions.append(
            {
                "role_id": role_id,
                "version_id": str(row["versionId"]),
                "props": row["versionProperties"],
            }
        )
    assets = query(
        args.url,
        args.database,
        args.user,
        args.password,
        "MATCH (d:DatasetAsset) RETURN d.dataset_id AS datasetId,properties(d) AS properties "
        "ORDER BY d.dataset_id",
    )
    overlay = {
        "schemaVersion": "career-insight-graph-overlay-v1",
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "sourceDatabase": args.database,
        "roles": list(role_map.values()),
        "versions": versions,
        "datasetAssets": [
            {"dataset_id": str(row["datasetId"]), "props": row["properties"]}
            for row in assets
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "roles": len(overlay["roles"]),
                "versions": len(versions),
                "datasetAssets": len(overlay["datasetAssets"]),
            },
            ensure_ascii=False,
        )
    )


def apply_overlay(args: argparse.Namespace) -> None:
    overlay = json.loads(Path(args.input).read_text(encoding="utf-8"))
    roles = overlay.get("roles", [])
    versions = overlay.get("versions", [])
    assets = overlay.get("datasetAssets", [])
    query(
        args.url,
        args.database,
        args.user,
        args.password,
        "UNWIND $rows AS row MERGE (r:JobRole {role_id:row.role_id}) SET r += row.props",
        {"rows": roles},
    )
    query(
        args.url,
        args.database,
        args.user,
        args.password,
        "UNWIND $rows AS row MATCH (r:JobRole {role_id:row.role_id}) "
        "MERGE (v:RoleDefinitionVersion {version_id:row.version_id}) SET v += row.props "
        "MERGE (r)-[:HAS_VERSION]->(v)",
        {"rows": versions},
    )
    query(
        args.url,
        args.database,
        args.user,
        args.password,
        "UNWIND $rows AS row MERGE (d:DatasetAsset {dataset_id:row.dataset_id}) SET d += row.props",
        {"rows": assets},
    )
    schema_statements = (
        "CREATE CONSTRAINT role_version_id IF NOT EXISTS FOR (v:RoleDefinitionVersion) REQUIRE v.version_id IS UNIQUE",
        "CREATE CONSTRAINT dataset_asset_id IF NOT EXISTS FOR (d:DatasetAsset) REQUIRE d.dataset_id IS UNIQUE",
        "CREATE INDEX requires_skill_edge_id IF NOT EXISTS FOR ()-[rel:REQUIRES_SKILL]-() ON (rel.edge_id)",
        "CREATE INDEX requires_skill_version_id IF NOT EXISTS FOR ()-[rel:REQUIRES_SKILL]-() ON (rel.version_id)",
        "CREATE FULLTEXT INDEX job_role_search IF NOT EXISTS FOR (r:JobRole) ON EACH [r.role_name,r.aliases]",
        "CREATE FULLTEXT INDEX skill_search IF NOT EXISTS FOR (s:Skill) ON EACH [s.entity_name,s.aliases_canonical]",
    )
    for statement in schema_statements:
        query(args.url, args.database, args.user, args.password, statement)
    counts = query(
        args.url,
        args.database,
        args.user,
        args.password,
        "MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() WITH nodes,count(r) AS relationships "
        "RETURN nodes,relationships,"
        "count { (:RoleDefinitionVersion) } AS versions,"
        "count { (:DatasetAsset) } AS datasetAssets,"
        "count { (:TimePeriod) } AS timePeriods,"
        "count { (:SkillDemandSnapshot) } AS snapshots",
    )[0]
    print(json.dumps(counts, ensure_ascii=False))


def normalize_graph(args: argparse.Namespace) -> None:
    statements = (
        (
            "MATCH (j:Job),(p:JobPosting) WHERE j.record_id=p.record_id AND elementId(j)<>elementId(p) "
            "SET p += properties(j),p:Job"
        ),
        (
            "MATCH (j:Job)-[source:REQUIRES_SKILL]->(s:Skill) "
            "MATCH (p:JobPosting {record_id:j.record_id}) WHERE elementId(j)<>elementId(p) "
            "MERGE (p)-[target:REQUIRES_SKILL]->(s) SET target += properties(source)"
        ),
        (
            "MATCH (j:Job),(p:JobPosting) WHERE j.record_id=p.record_id AND elementId(j)<>elementId(p) "
            "DETACH DELETE j"
        ),
        (
            "MATCH (o:OccupationRequirement),(r:Requirement) "
            "WHERE o.requirement_id=r.requirement_id AND elementId(o)<>elementId(r) "
            "MATCH (standard:OccupationStandard)-[source:HAS_REQUIREMENT]->(r) "
            "MERGE (standard)-[target:HAS_REQUIREMENT]->(o) SET target += properties(source)"
        ),
        (
            "MATCH (o:OccupationRequirement),(r:Requirement) "
            "WHERE o.requirement_id=r.requirement_id AND elementId(o)<>elementId(r) "
            "MATCH (r)-[source:MAPS_TO_SKILL]->(skill:Skill) "
            "MERGE (o)-[target:MAPS_TO_SKILL]->(skill) SET target += properties(source)"
        ),
        (
            "MATCH (o:OccupationRequirement),(r:Requirement) "
            "WHERE o.requirement_id=r.requirement_id AND elementId(o)<>elementId(r) "
            "SET o += properties(r)"
        ),
        (
            "MATCH (o:OccupationRequirement),(r:Requirement) "
            "WHERE o.requirement_id=r.requirement_id AND elementId(o)<>elementId(r) "
            "DETACH DELETE r"
        ),
        "MATCH (o:OccupationRequirement) SET o:Requirement",
    )
    for statement in statements:
        query(args.url, args.database, args.user, args.password, statement)
    counts = query(
        args.url,
        args.database,
        args.user,
        args.password,
        "MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() WITH nodes,count(r) AS relationships "
        "RETURN nodes,relationships,"
        "count { (:Job:JobPosting) } AS unifiedPostings,"
        "count { (:OccupationRequirement:Requirement) } AS unifiedRequirements,"
        "count { (:TimePeriod) } AS timePeriods,"
        "count { (:SkillDemandSnapshot) } AS snapshots",
    )[0]
    print(json.dumps(counts, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export or apply Career Insight admin graph overlay")
    parser.add_argument("mode", choices=("export", "apply", "normalize"))
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", required=True)
    parser.add_argument("--output")
    parser.add_argument("--input")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.mode == "export":
        if not args.output:
            raise SystemExit("--output is required for export")
        export_overlay(args)
    elif args.mode == "apply":
        if not args.input:
            raise SystemExit("--input is required for apply")
        apply_overlay(args)
    else:
        normalize_graph(args)


if __name__ == "__main__":
    main()
