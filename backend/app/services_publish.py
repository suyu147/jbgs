"""M5 review and publish primitives.

Review state is kept in MySQL.  A publish operation writes the Neo4j version
first and then records the matching MySQL version state.  The caller persists
the compensation task when either side fails.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RawRecord, RoleDefinitionDraft, RoleDefinitionVersion, uid


class PublishValidationError(ValueError):
    pass


def validate_evidence(db: Session, draft: RoleDefinitionDraft) -> dict:
    """Validate only new pipeline evidence; legacy rows retain their exemption."""
    if draft.origin == "legacy" or draft.evidence_grade == "legacy":
        return {"grade": "legacy", "checked": False, "evidenceCount": len(draft.evidence or [])}
    evidence = draft.evidence or []
    if not evidence:
        raise PublishValidationError("候选缺少证据，不能发布")
    record_ids = []
    for item in evidence:
        if not isinstance(item, dict):
            raise PublishValidationError("证据格式不正确，不能发布")
        if item.get("type") != "source_record" or not str(item.get("recordId") or "").strip():
            raise PublishValidationError("source_record 证据必须带 recordId")
        record_ids.append(str(item["recordId"]))
    raws = db.scalars(select(RawRecord).where(RawRecord.id.in_(set(record_ids)))).all()
    if len({row.id for row in raws}) != len(set(record_ids)):
        raise PublishValidationError("证据中的 recordId 无法解引用到 raw_records")
    definition = draft.definition or {}
    if definition.get("source_type") == "enterprise_job_submission":
        if len(record_ids) < 1:
            raise PublishValidationError("企业提交至少需要 1 条证据")
    elif draft.candidate_type == "skill_change":
        if not record_ids or float(definition.get("confidence") or 0) < 0.6:
            raise PublishValidationError("能力更新至少需要 1 条可追溯证据且置信度不低于 0.6")
    else:
        source_count = int(definition.get("source_count") or 0)
        evidence_count = int(definition.get("evidence_record_count") or len(set(record_ids)))
        confidence = float(definition.get("confidence") or 0)
        if source_count < 3 or evidence_count < 5 or confidence < 0.6:
            raise PublishValidationError("岗位定义未达到 M5 证据门禁：至少 3 个来源、5 条证据且置信度不低于 0.6")
    return {"grade": draft.evidence_grade or "source_record", "checked": True, "evidenceCount": len(set(record_ids))}


def version_id_for_draft(draft: RoleDefinitionDraft) -> str:
    return f"version_{draft.id}"


def upsert_approved_version(db: Session, draft: RoleDefinitionDraft, role_id: str) -> RoleDefinitionVersion:
    existing = db.scalar(
        select(RoleDefinitionVersion)
        .where(RoleDefinitionVersion.draft_id == draft.id)
        .order_by(RoleDefinitionVersion.created_at.desc())
        .limit(1)
    )
    if existing and existing.status not in {"withdrawn", "published"}:
        existing.role_id = role_id or existing.role_id
        existing.definition = draft.definition or {}
        existing.evidence = draft.evidence or []
        existing.status = "approved"
        return existing
    version = RoleDefinitionVersion(
        id=uid("version"), version_id=version_id_for_draft(draft), draft_id=draft.id,
        role_id=role_id or draft.role_id or "", role_name=draft.role_name,
        candidate_type=draft.candidate_type, status="approved", definition=draft.definition or {},
        evidence=draft.evidence or [], origin=draft.origin, batch_id=draft.batch_id,
        evidence_grade=draft.evidence_grade,
    )
    db.add(version)
    return version


def publish_neo4j_version(neo4j, version: RoleDefinitionVersion) -> dict:
    """Create/update the authoritative Neo4j version node idempotently."""
    definition = version.definition or {}
    rows = neo4j.query(
        "MERGE (r:JobRole {role_id:$role_id}) SET r.role_name=coalesce(r.role_name,$role_name) "
        "MERGE (v:RoleDefinitionVersion {version_id:$version_id}) "
        "SET v.status='published',v.definition_json=$definition,v.candidate_type=$candidate_type,"
        "v.display_title=$display_title,v.draft_id=$draft_id,v.published_at=datetime(),v.withdrawn_at=NULL "
        "MERGE (r)-[:HAS_VERSION]->(v) "
        "WITH r,v "
        "OPTIONAL MATCH (r)-[:HAS_VERSION]->(other:RoleDefinitionVersion {status:'published'}) "
        "WHERE other.version_id<>$version_id SET other.status='withdrawn',other.withdrawn_at=datetime() "
        "SET r.is_published=true,r.active_version_id=$version_id,r.discovery_title=$display_title,r.published_at=datetime() "
        "RETURN v.version_id AS id,v.status AS status,r.role_id AS roleId,r.discovery_title AS displayTitle",
        {
            "role_id": version.role_id, "role_name": version.role_name,
            "version_id": version.version_id,
            "definition": json.dumps(definition, ensure_ascii=False),
            "candidate_type": version.candidate_type,
            "display_title": str(definition.get("publication_title") or "岗位定义发布")[:24],
            "draft_id": version.draft_id,
        },
    )
    if not rows:
        raise PublishValidationError("Neo4j 未返回发布版本")
    return rows[0]


def mark_published(version: RoleDefinitionVersion, result: dict) -> None:
    version.status = "published"
    version.published_at = datetime.utcnow()
    version.withdrawn_at = None
    version.publish_result = result or {}


def mark_withdrawn(version: RoleDefinitionVersion) -> None:
    version.status = "withdrawn"
    version.withdrawn_at = datetime.utcnow()

