"""M4 dual engines: discovery candidates and capability-update drafts.

The service consumes persisted M3 signals and raw/normalized records only.  It
does not call Neo4j; publishing remains the sole graph-writing boundary.
"""

from __future__ import annotations

import re
import hashlib
from collections import Counter, defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EntityLink, FeatureSnapshot, NormalizedRecord, PipelineBatch, RawRecord, ReviewAction, RoleDefinitionDraft, Signal, uid
from .services_agent import FROZEN_STATUSES


DEFINITION_VERSION = "definition-v1"
SOURCE_EVIDENCE_GRADE = "source_record"
PIPELINE_ORIGIN = "pipeline"
SUPPORTED_SIGNALS = {"emerging_role", "capability_shift"}


def _text(value: object) -> str:
    return str(value or "").strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = _text(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _confidence(source_count: int, evidence_count: int, coverage: float | None = None) -> float:
    """Use observable support ratios; no LLM or hidden weighting is involved."""
    source_ratio = min(max(source_count, 0) / 3, 1.0)
    evidence_ratio = min(max(evidence_count, 0) / 5, 1.0)
    value = (source_ratio + evidence_ratio) / 2
    if coverage is not None:
        value = min(value, max(0.0, min(float(coverage), 1.0)))
    return round(value, 4)


def _period_sort_key(period: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d{4})-(\d{2}|Q[1-4])$", _text(period))
    if not match:
        return (0, 0, 0)
    year = int(match.group(1))
    part = match.group(2)
    month = int(part) if part.isdigit() else int(part[1:]) * 3
    return year, month, 1 if part.startswith("Q") else 0


def _load_context(db: Session, evidence_ids: Iterable[str]) -> tuple[dict[str, RawRecord], dict[str, NormalizedRecord], dict[str, list[EntityLink]]]:
    ids = _unique(evidence_ids)
    if not ids:
        return {}, {}, {}
    raws = {row.id: row for row in db.scalars(select(RawRecord).where(RawRecord.id.in_(ids))).all()}
    normalized = {
        row.raw_record_id: row
        for row in db.scalars(select(NormalizedRecord).where(NormalizedRecord.raw_record_id.in_(ids))).all()
    }
    links: dict[str, list[EntityLink]] = defaultdict(list)
    for row in db.scalars(select(EntityLink).where(EntityLink.raw_record_id.in_(ids))).all():
        links[row.raw_record_id].append(row)
    return raws, normalized, links


def _evidence_rows(raws: dict[str, RawRecord], evidence_ids: Iterable[str]) -> list[dict]:
    rows: list[dict] = []
    for record_id in _unique(evidence_ids):
        raw = raws.get(record_id)
        if not raw:
            continue
        payload = raw.raw_payload or {}
        rows.append(
            {
                "type": "source_record",
                "recordId": raw.id,
                "source": raw.source_canonical,
                "period": payload.get("published_date_clean") or payload.get("published_date") or payload.get("period") or payload.get("time_id") or "",
                "sourceLocator": raw.source_locator or {},
                "excerpt": _text(raw.content)[:320],
                "confidence": SOURCE_EVIDENCE_GRADE,
            }
        )
    return rows


def _role_name(cohort_key: str, raws: dict[str, RawRecord], links: dict[str, list[EntityLink]]) -> str:
    role_id = cohort_key.split(":", 1)[1] if cohort_key.startswith("role:") else ""
    titles: list[str] = []
    for record_id, raw in raws.items():
        if role_id:
            role_links = [item for item in links.get(record_id, []) if item.entity_type == "JobRole" and item.entity_id == role_id]
            if role_links:
                titles.append(role_links[0].surface_form)
        titles.append(raw.title)
    if titles:
        return sorted(_unique(titles), key=lambda value: (len(value), value))[0][:255]
    return cohort_key.split(":", 1)[1][:255] if ":" in cohort_key else cohort_key[:255]


def _skills_for_records(
    normalized: dict[str, NormalizedRecord], links: dict[str, list[EntityLink]],
) -> list[dict]:
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    record_sets: dict[str, set[str]] = defaultdict(set)
    for record_id, row in normalized.items():
        data = row.data or {}
        for skill in data.get("skills") or []:
            if not isinstance(skill, dict) or skill.get("link_status", "accepted") != "accepted":
                continue
            skill_id = _text(skill.get("skill_id"))
            if not skill_id:
                continue
            names[skill_id] = _text(skill.get("skill_name") or skill.get("surface_form")) or skill_id
            record_sets[skill_id].add(record_id)
        for link in links.get(record_id, []):
            if link.entity_type != "Skill" or link.status != "accepted" or not link.entity_id:
                continue
            skill_id = _text(link.entity_id)
            names.setdefault(skill_id, _text(link.surface_form) or skill_id)
            record_sets[skill_id].add(record_id)
    for skill_id, records in record_sets.items():
        counts[skill_id] = len(records)
    total = max(len(normalized), 1)
    return [
        {
            "skill_id": skill_id,
            "skill_name": names[skill_id],
            "evidence_count": count,
            "posting_penetration": round(count / total, 4),
        }
        for skill_id, count in counts.most_common(8)
    ]


def _responsibilities(raws: dict[str, RawRecord], normalized: dict[str, NormalizedRecord]) -> list[str]:
    values: list[str] = []
    for row in normalized.values():
        values.extend(_text(item) for item in (row.data or {}).get("responsibilities") or [] if _text(item))
    if not values:
        for raw in raws.values():
            values.extend(part.strip(" -·•") for part in re.split(r"[。；;\n]", _text(raw.content)) if len(part.strip()) >= 8)
    return _unique(values)[:6]


def _schema_definition(definition: dict, candidate_type: str) -> dict | None:
    """Return a normalized definition only when it satisfies the M4 schema."""
    if not isinstance(definition, dict):
        return None
    required = {"job_category", "first_seen", "latest_seen", "posting_count", "source_count", "candidate_reason", "definition_status"}
    if not required.issubset(definition):
        return None
    if not _text(definition.get("candidate_reason")) or not _text(definition.get("definition_status")):
        return None
    if not isinstance(definition.get("posting_count"), int) or not isinstance(definition.get("source_count"), int):
        return None
    if candidate_type in {"new_role", "definition_update"}:
        for field in ("core_responsibilities", "required_skills", "bonus_skills", "application_scenarios"):
            if not isinstance(definition.get(field), list):
                return None
        for item in definition["required_skills"] + definition["bonus_skills"]:
            if not isinstance(item, dict) or not _text(item.get("skill_id")) or not _text(item.get("skill_name")):
                return None
    elif candidate_type == "skill_change":
        if not isinstance(definition.get("changes"), list):
            return None
        for item in definition["changes"]:
            if not isinstance(item, dict) or not _text(item.get("skill_id")) or item.get("change_type") not in {"increase", "decrease"}:
                return None
    return definition


def _existing_draft(db: Session, candidate_type: str, cohort_key: str, period_key: str) -> RoleDefinitionDraft | None:
    rows = db.scalars(select(RoleDefinitionDraft).where(RoleDefinitionDraft.candidate_type == candidate_type, RoleDefinitionDraft.origin == PIPELINE_ORIGIN)).all()
    for row in rows:
        definition = row.definition or {}
        if definition.get("cohort_key") == cohort_key and definition.get("period_key") == period_key:
            return row
    return None


def _upsert_draft(
    db: Session, *, role_name: str, candidate_type: str, definition: dict, evidence: list[dict], batch_id: str,
) -> RoleDefinitionDraft | None:
    cohort_key = _text(definition.get("cohort_key"))
    period_key = _text(definition.get("period_key"))
    draft = _existing_draft(db, candidate_type, cohort_key, period_key)
    if draft and _draft_skip_reason(db, draft):
        return None
    if not draft:
        draft = RoleDefinitionDraft(
            id=uid("draft"), role_name=role_name, candidate_type=candidate_type,
            origin=PIPELINE_ORIGIN, batch_id=batch_id, evidence_grade=SOURCE_EVIDENCE_GRADE,
        )
        db.add(draft)
    if cohort_key.startswith("role:"):
        draft.role_id = cohort_key.split(":", 1)[1]
    definition = {**definition, "batch_ids": _unique([*((draft.definition or {}).get("batch_ids") or []), *(definition.get("batch_ids") or [])])}
    draft.definition = definition
    draft.evidence = evidence
    draft.origin = PIPELINE_ORIGIN
    if not draft.batch_id:
        draft.batch_id = batch_id
    draft.evidence_grade = SOURCE_EVIDENCE_GRADE
    draft.status = "pending"
    return draft


def _draft_skip_reason(db: Session, draft: RoleDefinitionDraft) -> str:
    if draft.status in FROZEN_STATUSES:
        return "draft_frozen"
    if db.scalar(select(ReviewAction.id).where(ReviewAction.draft_id == draft.id).limit(1)):
        return "draft_edited"
    return ""


def create_enterprise_draft(db: Session, batch: PipelineBatch, raw: RawRecord) -> RoleDefinitionDraft:
    payload = raw.raw_payload or {}
    responsibilities = payload.get("responsibilities") or [part.strip() for part in re.split(r"[。；;\n]", raw.content) if part.strip()]
    def skills(field: str, placeholder: str) -> list[dict]:
        values = payload.get(field) or [placeholder]
        return [{"skill_id": f"enterprise_skill:{hashlib.sha256(str(value).encode()).hexdigest()[:20]}",
                 "skill_name": str(value), "evidence_count": 1} for value in values]
    period = raw.created_at.strftime("%Y-%m")
    definition = {
        "source_type": "enterprise_job_submission", "enterprise_name": raw.company_name,
        "enterprise_user_id": (batch.metadata_json or {}).get("enterprise_user_id", ""),
        "posting_count": int(payload.get("openingCount") or 1), "source_count": 1,
        "evidence_record_count": 1, "confidence": 0.6, "definition_status": "human_review_required",
        "cohort_key": f"enterprise:{raw.id}", "period_key": period, "batch_id": batch.id, "batch_ids": [batch.id],
        "job_category": payload.get("job_category", ""), "location": payload.get("city", ""),
        "first_seen": period, "latest_seen": period, "candidate_reason": "企业提交岗位，待人工复核。",
        "core_responsibilities": responsibilities,
        "required_skills": skills("requiredSkills", "待补充必备技能"),
        "bonus_skills": skills("bonusSkills", "待补充加分技能"),
        "application_scenarios": [{"scenario": str(value), "evidence_count": 1} for value in payload.get("applicationScenarios") or ["企业岗位招聘"]],
    }
    draft = RoleDefinitionDraft(
        role_name=raw.title, candidate_type="new_role", origin=PIPELINE_ORIGIN, status="pending",
        batch_id=batch.id, evidence_grade=SOURCE_EVIDENCE_GRADE, definition=definition,
        evidence=[{"type": "source_record", "recordId": raw.id, "content_sha256": raw.content_sha256,
                   "source": "jdText", "excerpt": raw.content[:500]}],
    )
    db.add(draft)
    db.flush()
    return draft


def _capability_changes(db: Session, signal: Signal, current: FeatureSnapshot | None, raws: dict[str, RawRecord], normalized: dict[str, NormalizedRecord], links: dict[str, list[EntityLink]]) -> list[dict]:
    metrics = (current.metrics if current else {}) or {}
    share_changes = metrics.get("skill_share_change") or {}
    names = {item["skill_id"]: item["skill_name"] for item in _skills_for_records(normalized, links)}
    changes = []
    for skill_id, change in sorted(share_changes.items(), key=lambda item: (-abs(float(item[1] or 0)), item[0]))[:8]:
        value = float(change or 0)
        changes.append({
            "skill_id": _text(skill_id),
            "skill_name": names.get(_text(skill_id), _text(skill_id)),
            "change_type": "increase" if value >= 0 else "decrease",
            "change_pp": round(value * 100, 2),
            "analysis_note": "基于相邻周期技能占比差异生成，待人工复核。",
        })
    return changes


def build_definition_stage(db: Session, *, batch_id: str | None = None, period_key: str | None = None) -> dict:
    """Create or update M4 drafts from persisted, evidence-backed signals."""
    query = select(Signal).where(Signal.signal_type.in_(SUPPORTED_SIGNALS), Signal.status == "active")
    if period_key:
        query = query.where(Signal.period_key == period_key)
    signals = db.scalars(query.order_by(Signal.period_key, Signal.cohort_key)).all()
    feature_rows = {
        (row.cohort_key, row.period_key, row.granularity): row
        for row in db.scalars(select(FeatureSnapshot)).all()
    }
    created = updated = skipped = 0
    reasons: Counter[str] = Counter()
    draft_ids: list[str] = []
    for signal in signals:
        candidate_type = "new_role" if signal.signal_type == "emerging_role" else "skill_change"
        existing = _existing_draft(db, candidate_type, signal.cohort_key, signal.period_key)
        reason = _draft_skip_reason(db, existing) if existing else ""
        if reason:
            skipped += 1
            reasons[reason] += 1
            continue
        evidence_ids = _unique(signal.evidence_ids or [])
        raws, normalized, links = _load_context(db, evidence_ids)
        evidence = _evidence_rows(raws, evidence_ids)
        evidence_ids = [item["recordId"] for item in evidence]
        if batch_id:
            evidence = [item for item in evidence if raws[item["recordId"]].batch_id == batch_id]
            evidence_ids = [item["recordId"] for item in evidence]
            raws, normalized, links = _load_context(db, evidence_ids)
        source_count = len({_text(raws[item].source_canonical) for item in evidence_ids if _text(raws[item].source_canonical)})
        evidence_count = len(evidence_ids)
        metrics = (signal.metrics or {}).copy()
        coverage = None
        feature = feature_rows.get((signal.cohort_key, signal.period_key, signal.granularity))
        if feature:
            coverage = float((feature.metrics or {}).get("coverage") or 0)
        confidence = _confidence(source_count, evidence_count, coverage)
        if signal.signal_type == "emerging_role" and (source_count < 3 or evidence_count < 5 or confidence < 0.6):
            skipped += 1
            reasons["new_role_evidence_threshold"] += 1
            continue
        if signal.signal_type == "capability_shift" and (not evidence_ids or confidence < 0.6):
            skipped += 1
            reasons["capability_evidence_threshold"] += 1
            continue
        role_name = _role_name(signal.cohort_key, raws, links)
        batch_ids = _unique(raws[item].batch_id for item in evidence_ids)
        draft_batch = batch_id or (batch_ids[0] if len(batch_ids) == 1 else (batch_ids[0] if batch_ids else ""))
        common = {
            "job_category": "",
            "first_seen": signal.period_key,
            "latest_seen": signal.period_key,
            "posting_count": int(metrics.get("posting_count") or evidence_count),
            "source_count": source_count,
            "candidate_reason": f"由 {signal.signal_type} 信号在 {signal.period_key} 周期触发，待人工复核。",
            "definition_status": "human_review_required",
            "confidence": confidence,
            "signal_type": signal.signal_type,
            "signal_id": signal.id,
            "period_key": signal.period_key,
            "cohort_key": signal.cohort_key,
            "batch_ids": batch_ids,
            "evidence_record_count": evidence_count,
            "definition_version": DEFINITION_VERSION,
        }
        if signal.signal_type == "emerging_role":
            skills = _skills_for_records(normalized, links)
            required = skills[:5]
            bonus = skills[5:8]
            definition = {
                **common,
                "core_responsibilities": _responsibilities(raws, normalized),
                "required_skills": required,
                "bonus_skills": bonus,
                "application_scenarios": [{"scenario": "招聘市场观测", "evidence_count": evidence_count}],
            }
            candidate_type = "new_role"
        else:
            current = feature
            changes = _capability_changes(db, signal, current, raws, normalized, links)
            definition = {**common, "changes": changes}
            candidate_type = "skill_change"
        definition = _schema_definition(definition, candidate_type)
        if definition is None:
            skipped += 1
            reasons["schema_validation"] += 1
            continue
        existing = _existing_draft(db, candidate_type, signal.cohort_key, signal.period_key)
        draft = _upsert_draft(db, role_name=role_name, candidate_type=candidate_type, definition=definition, evidence=evidence, batch_id=draft_batch)
        if draft is None:
            skipped += 1
            reasons[_draft_skip_reason(db, existing) if existing else "draft_changed"] += 1
            continue
        draft_ids.append(draft.id)
        if existing:
            updated += 1
        else:
            created += 1
    return {
        "definition_version": DEFINITION_VERSION,
        "signals_considered": len(signals),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "skip_reasons": dict(reasons),
        "draft_ids": [item for item in draft_ids if item],
        "batch_id": batch_id or "",
    }


def serialize_definition_draft(row: RoleDefinitionDraft) -> dict:
    return {
        "id": row.id,
        "roleId": row.role_id,
        "roleName": row.role_name,
        "candidateType": row.candidate_type,
        "status": row.status,
        "origin": row.origin,
        "batchId": row.batch_id,
        "evidenceGrade": row.evidence_grade,
        "definition": row.definition,
        "evidence": row.evidence,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
    }
