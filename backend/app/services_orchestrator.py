"""Single-process, serial local automation; no external task queue."""

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AgentRun, EntityLink, NormalizedRecord, PipelineBatch, PipelineStageLog, RawRecord, ReviewAction, RoleDefinitionDraft
from .services_agent import generate_description
from .services_feature import _norm_title, build_feature_stage, period_from_record
from .services_m4 import build_definition_stage
from .services_parse import ensure_normalized


PIPELINE_LOCK = threading.Lock()


@contextmanager
def pipeline_guard():
    acquired = PIPELINE_LOCK.acquire(timeout=600)
    try:
        yield acquired
    finally:
        if acquired:
            PIPELINE_LOCK.release()


def create_agent_run(db: Session, batch: PipelineBatch, *, trigger: str = "ingest", draft_id: str = "") -> AgentRun:
    scope = "enterprise" if batch.source_type == "enterprise" else "batch"
    if scope == "enterprise" and not draft_id:
        draft_id = db.scalar(select(RoleDefinitionDraft.id).where(RoleDefinitionDraft.batch_id == batch.id,
                                                                 RoleDefinitionDraft.origin == "pipeline").limit(1)) or ""
    row = AgentRun(batch_id=batch.id, draft_id=draft_id, trigger=trigger, scope=scope,
                   status="queued", started_at=datetime.utcnow())
    db.add(row)
    db.commit()
    return row


def serialize_agent_run(row: AgentRun) -> dict:
    reasons = Counter()
    for value in (row.stages or {}).values():
        if isinstance(value, dict):
            reasons.update(value.get("skip_reasons") or {})
            if value.get("reason"):
                reasons[value["reason"]] += 1
    return {"id": row.id, "batchId": row.batch_id, "draftId": row.draft_id, "trigger": row.trigger,
            "scope": row.scope, "status": row.status, "stages": row.stages or {}, "skip_reasons": dict(reasons),
            "draftCount": row.draft_count, "descriptionCount": row.description_count,
            "llmUsed": row.llm_used, "error": row.error,
            "startedAt": row.started_at.isoformat() if row.started_at else None,
            "finishedAt": row.finished_at.isoformat() if row.finished_at else None}


def batch_cohort_keys(db: Session, batch_id: str) -> set[tuple[str, str]]:
    normalized = {row.raw_record_id: row.data or {} for row in db.scalars(select(NormalizedRecord).where(NormalizedRecord.batch_id == batch_id))}
    roles = {}
    for row in db.scalars(select(EntityLink).where(EntityLink.batch_id == batch_id,
        EntityLink.entity_type == "JobRole", EntityLink.status == "accepted").order_by(EntityLink.created_at, EntityLink.id)):
        if row.entity_id:
            roles.setdefault(row.raw_record_id, row.entity_id)
    result = set()
    for raw in db.scalars(select(RawRecord).where(RawRecord.batch_id == batch_id)):
        if raw.node_type not in {"JobPosting", "", "JobRole"}:
            continue
        period = period_from_record(raw)
        if period:
            title = _norm_title(raw.title or normalized.get(raw.id, {}).get("title"))
            cohort = f"role:{roles[raw.id]}" if raw.id in roles else f"title:{title or raw.id}"
            result.add((period[0], cohort))
    return result


def select_description_candidates(db: Session, batch_id: str, draft_ids: list[str]) -> list[RoleDefinitionDraft]:
    keys = batch_cohort_keys(db, batch_id)
    edited = set(db.scalars(select(ReviewAction.draft_id)).all())
    rows = db.scalars(select(RoleDefinitionDraft).where(RoleDefinitionDraft.id.in_(draft_ids), RoleDefinitionDraft.status == "pending")).all() if draft_ids else []
    candidates = [row for row in rows if row.id not in edited and
                  ((row.definition or {}).get("period_key"), (row.definition or {}).get("cohort_key")) in keys]
    # Stable sort keeps ascending IDs within equal descending period/confidence.
    candidates.sort(key=lambda row: row.id)
    candidates.sort(key=lambda row: float((row.definition or {}).get("confidence") or 0), reverse=True)
    candidates.sort(key=lambda row: str((row.definition or {}).get("period_key") or ""), reverse=True)
    return candidates


def _save_stage(db: Session, run: AgentRun, name: str, result: dict, *, log: bool = False) -> None:
    run.stages = {**(run.stages or {}), name: result}
    if log:
        batch = db.get(PipelineBatch, run.batch_id)
        batch.stage, batch.status = name, "completed"
        batch.statistics = {**(batch.statistics or {}), name: result}
        db.add(PipelineStageLog(batch_id=run.batch_id, stage=name, status="completed", statistics=result))
    db.commit()


def run_agent_pipeline(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if not run or run.status != "queued":
            return
        with pipeline_guard() as acquired:
            try:
                # Discard the pre-lock read snapshot (MySQL REPEATABLE READ).
                db.rollback()
                run = db.get(AgentRun, run_id)
                if run.status != "queued":
                    return
                if not acquired:
                    run.status, run.finished_at = "skipped", datetime.utcnow()
                    _save_stage(db, run, "pipeline", {"status": "skipped", "reason": "busy"})
                    return
                if not settings.agent_pipeline_enabled:
                    run.status, run.finished_at = "skipped", datetime.utcnow()
                    _save_stage(db, run, "pipeline", {"status": "skipped", "reason": "disabled"})
                    return
                run.status = "running"
                db.commit()
                batch = db.get(PipelineBatch, run.batch_id)
                if batch is None:
                    raise ValueError("batch_not_found")
                if run.scope == "enterprise":
                    draft = db.get(RoleDefinitionDraft, run.draft_id) if run.draft_id else None
                    if draft is None:
                        raise ValueError("no_draft_legacy_batch")
                    candidates = [draft] if draft.status == "pending" else []
                    _save_stage(db, run, "feature", {"status": "skipped", "reason": "enterprise_scope"})
                    _save_stage(db, run, "definition", {"status": "skipped", "reason": "enterprise_scope"})
                else:
                    _save_stage(db, run, "normalize", ensure_normalized(db, batch))
                    _save_stage(db, run, "feature", {"status": "completed", **build_feature_stage(db)}, log=True)
                    result = build_definition_stage(db, batch_id=None)
                    _save_stage(db, run, "definition", {"status": "completed", **result}, log=True)
                    candidates = select_description_candidates(db, batch.id, result["draft_ids"])
                run.draft_count = len(candidates)
                db.commit()
                if not settings.agent_description_enabled:
                    result = {"status": "skipped", "reason": "disabled"}
                elif not candidates:
                    result = {"status": "skipped", "reason": "frozen" if run.scope == "enterprise" else "no_signal"}
                else:
                    limit = max(0, settings.agent_description_max_drafts)
                    reasons = Counter()
                    if len(candidates) > limit:
                        reasons["over_limit"] = len(candidates) - limit
                    results = []
                    for candidate in candidates[:limit]:
                        item = {"draftId": candidate.id, **generate_description(db, candidate)}
                        results.append(item)
                        if item.get("reason"):
                            reasons[item["reason"]] += 1
                        run.description_count += int(item["status"] == "completed")
                        run.llm_used = run.llm_used or bool(item.get("llm_used"))
                        _save_stage(db, run, "description", {"status": "running", "items": results, "skip_reasons": dict(reasons)})
                    result = {"status": "completed" if results else "skipped", "items": results, "skip_reasons": dict(reasons)}
                run.status, run.finished_at = "completed", datetime.utcnow()
                _save_stage(db, run, "description", result)
            except Exception as error:
                db.rollback()
                run = db.get(AgentRun, run_id)
                if run:
                    run.status, run.error, run.finished_at = "failed", str(error), datetime.utcnow()
                    db.commit()


def reconcile_stale_agent_runs() -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=settings.agent_run_stale_minutes)
    with SessionLocal() as db:
        rows = db.scalars(select(AgentRun).where(AgentRun.status.in_(["queued", "running"]), AgentRun.started_at < cutoff)).all()
        for row in rows:
            row.status, row.error, row.finished_at = "interrupted", "interrupted", datetime.utcnow()
        db.commit()
        return len(rows)
