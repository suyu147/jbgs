"""M6 graph projection and bitemporal relationship queries.

Neo4j is the authoritative read source after publish.  Relationships created
by this module are versioned by ``edge_id`` and retain valid/recorded times so
current, as-of, and exact-version reads can share one representation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def edge_id_for(role_id: str, skill_id: str, tier: str, version_id: str) -> str:
    return f"{role_id}:{skill_id}:{tier}:{version_id}"


def _skill_items(version: Any) -> list[dict]:
    definition = getattr(version, "definition", None) or {}
    candidate_type = str(getattr(version, "candidate_type", "") or "")
    items: list[dict] = []
    if candidate_type in {"new_role", "definition_update"}:
        for tier, field in (("core", "required_skills"), ("bonus", "bonus_skills")):
            for item in definition.get(field) or []:
                if isinstance(item, str):
                    item = {"skill_name": item}
                if isinstance(item, dict):
                    skill_id = str(item.get("skill_id") or "").strip()
                    skill_name = str(item.get("skill_name") or item.get("name") or "").strip()
                    if skill_id or skill_name:
                        items.append({
                            "skill_id": skill_id,
                            "skill_name": skill_name,
                            "tier": str(item.get("tier") or tier),
                            "confidence": float(item.get("confidence") or 1.0),
                        })
    elif candidate_type == "skill_change":
        for item in definition.get("changes") or []:
            if not isinstance(item, dict):
                continue
            skill_id = str(item.get("skill_id") or "").strip()
            skill_name = str(item.get("skill_name") or item.get("name") or "").strip()
            if skill_id or skill_name:
                items.append({
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "tier": str(item.get("tier") or "core"),
                    "confidence": float(item.get("confidence") or 1.0),
                    "change_type": str(item.get("change_type") or "increase"),
                })
    return items


def project_role_version(neo4j, version: Any) -> dict:
    """Project one published version's skill edges idempotently.

    Every increase/definition skill gets a new edge for this version.  Any
    previous open edge for the same role/skill is closed first.  Decreases
    close the previous open edge without creating a replacement edge.
    """
    role_id = str(getattr(version, "role_id", "") or "")
    version_id = str(getattr(version, "version_id", "") or "")
    if not role_id or not version_id:
        raise ValueError("关系投影缺少 role_id 或 version_id")
    items = _skill_items(version)
    definition = getattr(version, "definition", None) or {}
    version_properties = {
        "role_family": definition.get("job_category") or definition.get("role_family") or "",
        "job_categories": definition.get("job_category") or "",
        "first_seen": definition.get("first_seen") or "",
        "last_seen": definition.get("latest_seen") or "",
        "posting_count": int(definition.get("posting_count") or 0),
        "source_count": int(definition.get("source_count") or 0),
    }
    candidate_type = str(getattr(version, "candidate_type", "") or "")
    if candidate_type == "new_role":
        version_properties.update({"trend_label": "新岗位发现", "trend_direction": "new"})
    elif candidate_type == "skill_change":
        changes = [float(item.get("change_pp") or 0) for item in definition.get("changes", []) if isinstance(item, dict)]
        average = sum(changes) / len(changes) if changes else 0
        version_properties.update({
            "trend_label": "需求量上升" if average >= 1.5 else "需求量有所下降" if average <= -1.5 else "需求稳定",
            "trend_direction": "up" if average >= 1.5 else "down" if average <= -1.5 else "stable",
            "trend_change_pp": round(average, 2),
        })
    version_properties = {key: value for key, value in version_properties.items() if value not in (None, "", 0)}
    neo4j.query(
        "MATCH (v:RoleDefinitionVersion {version_id:$version_id}) SET v += $properties "
        "RETURN v.version_id AS versionId",
        {"version_id": version_id, "properties": version_properties},
    )
    projected = 0
    closed = 0
    skipped: list[str] = []
    if str(getattr(version, "candidate_type", "") or "") in {"new_role", "definition_update"}:
        rows = neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->() "
            "WHERE rel.valid_to IS NULL AND coalesce(rel.version_id,'')<>$version_id "
            "SET rel.valid_to=datetime(),rel.active=false RETURN count(rel) AS closed",
            {"role_id": role_id, "version_id": version_id},
        )
        closed += int((rows[0].get("closed") or 0) if rows else 0)
    for item in items:
        skill_id = item["skill_id"]
        if not skill_id and item["skill_name"]:
            rows = neo4j.query(
                "MATCH (s:Skill) WHERE toLower(coalesce(s.entity_name,s.name,''))=toLower($name) "
                "RETURN s.skill_id AS id LIMIT 2",
                {"name": item["skill_name"]},
            )
            if len(rows) != 1:
                skipped.append(item["skill_name"])
                continue
            skill_id = str(rows[0].get("id") or "")
        if not skill_id:
            skipped.append(item["skill_name"] or "unknown")
            continue
        edge_id = edge_id_for(role_id, skill_id, item["tier"], version_id)
        if item.get("change_type") == "decrease":
            rows = neo4j.query(
                "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->(s:Skill {skill_id:$skill_id}) "
                "WHERE rel.valid_to IS NULL SET rel.valid_to=datetime(),rel.active=false "
                "RETURN count(rel) AS closed",
                {"role_id": role_id, "skill_id": skill_id},
            )
            closed += int((rows[0].get("closed") or 0) if rows else 0)
            continue
        rows = neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id}),(s:Skill {skill_id:$skill_id}) "
            "OPTIONAL MATCH (r)-[old:REQUIRES_SKILL]->(s) "
            "WHERE old.valid_to IS NULL AND coalesce(old.edge_id,'')<>$edge_id "
            "WITH r,s,collect(old) AS olds "
            "FOREACH (rel IN olds | SET rel.valid_to=datetime(),rel.active=false) "
            "MERGE (r)-[rel:REQUIRES_SKILL {edge_id:$edge_id}]->(s) "
            "SET rel.version_id=$version_id,rel.valid_from=coalesce(rel.valid_from,datetime()),"
            "rel.valid_to=NULL,rel.recorded_at=coalesce(rel.recorded_at,datetime()),rel.active=true,"
            "rel.definition_managed=true,rel.skill_tier=$tier,rel.confidence=$confidence "
            "RETURN size([old IN olds WHERE old IS NOT NULL]) AS closed,rel.edge_id AS edgeId",
            {
                "role_id": role_id,
                "skill_id": skill_id,
                "edge_id": edge_id,
                "version_id": version_id,
                "tier": item["tier"],
                "confidence": item["confidence"],
            },
        )
        if rows:
            closed += int(rows[0].get("closed") or 0)
            projected += 1
        else:
            skipped.append(item["skill_name"] or skill_id)
    if skipped:
        raise ValueError(f"技能关系投影缺少唯一技能资产：{', '.join(skipped[:8])}")
    return {
        "roleId": role_id,
        "versionId": version_id,
        "projected": projected,
        "closed": closed,
        "skipped": skipped,
        "projectionVersion": "graph-v1-bitemporal",
    }


def close_version_edges(neo4j, role_id: str, version_id: str) -> dict:
    rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->() "
        "WHERE rel.version_id=$version_id AND rel.valid_to IS NULL "
        "SET rel.valid_to=datetime(),rel.active=false "
        "RETURN count(rel) AS closed",
        {"role_id": role_id, "version_id": version_id},
    )
    return {"roleId": role_id, "versionId": version_id, "closed": int((rows[0].get("closed") or 0) if rows else 0)}


def _view_clause(view: str, as_of: str, version_id: str) -> tuple[str, dict]:
    if view == "version":
        return "rel.version_id=$version_id", {"version_id": version_id}
    if view == "as_of":
        return "rel.valid_from <= datetime($as_of) AND (rel.valid_to IS NULL OR rel.valid_to > datetime($as_of))", {"as_of": as_of}
    return "rel.valid_to IS NULL AND coalesce(rel.active,true)=true", {}


def role_skill_view(neo4j, role_id: str, *, view: str = "current", as_of: str = "", version_id: str = "") -> dict:
    normalized_view = "as_of" if view in {"as-of", "as_of"} else view
    if normalized_view not in {"current", "as_of", "version"}:
        raise ValueError("view 必须是 current、as_of 或 version")
    if normalized_view == "as_of" and not as_of:
        raise ValueError("as_of 视图需要 as_of 参数")
    if normalized_view == "as_of":
        try:
            datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("as_of 必须是 ISO 8601 时间") from exc
    if normalized_view == "version" and not version_id:
        raise ValueError("version 视图需要 version_id 参数")
    clause, params = _view_clause(normalized_view, as_of, version_id)
    params["role_id"] = role_id
    rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->(s:Skill) "
        f"WHERE {clause} "
        "RETURN s.skill_id AS id,s.entity_name AS name,toFloat(rel.penetration_rate) AS weight,"
        "toInteger(rel.source_count) AS sourceCount,toInteger(rel.evidence_count) AS evidenceCount,"
        "rel.confidence AS confidence,rel.skill_tier AS tier,rel.edge_id AS edgeId,"
        "rel.version_id AS versionId,rel.valid_from AS validFrom,rel.valid_to AS validTo,"
        "rel.recorded_at AS recordedAt ORDER BY weight DESC,name",
        params,
    )
    version_rows = neo4j.query(
        "MATCH (v:RoleDefinitionVersion {version_id:$version_id}) RETURN properties(v) AS properties LIMIT 1",
        {"version_id": version_id},
    ) if normalized_view == "version" else []
    return {
        "roleId": role_id,
        "view": normalized_view,
        "asOf": as_of or None,
        "versionId": version_id or None,
        "items": rows,
        "total": len(rows),
        "versionProperties": (version_rows[0].get("properties") or {}) if version_rows else {},
    }


def role_graph_view(neo4j, role_id: str, *, view: str = "current", as_of: str = "", version_id: str = "") -> dict:
    skills = role_skill_view(neo4j, role_id, view=view, as_of=as_of, version_id=version_id)
    normalized_view = skills["view"]
    if normalized_view == "version":
        role_rows = neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id})-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$version_id}) "
            "RETURN r.role_id AS id,r.role_name AS name,r.is_published AS isPublished,"
            "v.version_id AS versionId,properties(v) AS properties LIMIT 1",
            {"role_id": role_id, "version_id": version_id},
        )
    elif normalized_view == "as_of":
        role_rows = neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id})-[:HAS_VERSION]->(v:RoleDefinitionVersion) "
            "WHERE v.published_at <= datetime($as_of) AND (v.withdrawn_at IS NULL OR v.withdrawn_at > datetime($as_of)) "
            "WITH r,v ORDER BY v.published_at DESC LIMIT 1 "
            "RETURN r.role_id AS id,r.role_name AS name,r.is_published AS isPublished,"
            "v.version_id AS versionId,properties(v) AS properties LIMIT 1",
            {"role_id": role_id, "as_of": as_of},
        )
    else:
        role_rows = neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id}) OPTIONAL MATCH (r)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:r.active_version_id}) "
            "RETURN r.role_id AS id,r.role_name AS name,r.active_version_id AS activeVersionId,"
            "r.is_published AS isPublished,v.version_id AS versionId,properties(v) AS properties LIMIT 1",
            {"role_id": role_id},
        )
    role = role_rows[0] if role_rows else None
    if role and role.get("properties"):
        role["properties"] = role["properties"]
    return {"role": role, **skills}

