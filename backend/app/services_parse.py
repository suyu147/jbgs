"""Parser registry for the batch extraction and normalization stage."""

from dataclasses import dataclass
from typing import Callable
from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .linker import ACTIVE_LINKER, LINKER_VERSION, EntityLinker, normalize_surface, refresh_entity_linker
from .models import EntityLink, ExtractedRecord, NormalizedRecord, PipelineBatch, PipelineStageLog, RawRecord
from .services import parse_jd


@dataclass(frozen=True)
class Parser:
    name: str
    version: str
    parse: Callable[[RawRecord], dict]


def _parse_job_posting(record: RawRecord) -> dict:
    return parse_jd(record.content)


def _parse_structured(record: RawRecord) -> dict:
    return {key: value for key, value in (record.raw_payload or {}).items()
            if not str(key).startswith("__")}


PARSER_REGISTRY = {
    "JobPosting": Parser("job_posting", "job-posting-parser-v1", _parse_job_posting),
}
DEFAULT_PARSER = Parser("structured", "structured-parser-v1", _parse_structured)


def parse_record(record: RawRecord) -> tuple[str, str, dict]:
    parser = PARSER_REGISTRY.get(record.node_type, DEFAULT_PARSER)
    return parser.name, parser.version, parser.parse(record)


def parse_batch(db: Session, batch: PipelineBatch) -> dict:
    rows = db.scalars(select(RawRecord).where(RawRecord.batch_id == batch.id)).all()
    errors, parsed_count = [], 0
    for raw in rows:
        try:
            # Isolate a bad parser or row without rolling back other records.
            with db.begin_nested():
                name, version, data = parse_record(raw)
                if not isinstance(data, dict):
                    raise ValueError("parser must return an object")
                extracted = db.scalar(select(ExtractedRecord).where(
                    ExtractedRecord.batch_id == batch.id, ExtractedRecord.raw_record_id == raw.id))
                if extracted is None:
                    extracted = ExtractedRecord(batch_id=batch.id, raw_record_id=raw.id)
                    db.add(extracted)
                extracted.parser_name, extracted.parser_version = name, version
                extracted.data = deepcopy(data)
                normalized = db.scalar(select(NormalizedRecord).where(
                    NormalizedRecord.batch_id == batch.id, NormalizedRecord.raw_record_id == raw.id))
                if normalized is None:
                    normalized = NormalizedRecord(batch_id=batch.id, raw_record_id=raw.id)
                    db.add(normalized)
                normalized.data, normalized.linker_version = deepcopy(data), LINKER_VERSION
            parsed_count += 1
        except Exception as error:
            errors.append({"recordId": raw.id, "error": str(error)})
    return {"processed": len(rows), "parsed": parsed_count, "parse_errors": errors}


def link_batch(db: Session, batch: PipelineBatch, active_linker: EntityLinker) -> dict:
    linked_count = 0
    rows = db.scalars(select(RawRecord).where(RawRecord.batch_id == batch.id)).all()
    for raw in rows:
        normalized = db.scalar(select(NormalizedRecord).where(
            NormalizedRecord.batch_id == batch.id, NormalizedRecord.raw_record_id == raw.id))
        if normalized is None:
            continue
        parsed = deepcopy(normalized.data or {})
        surfaces = []
        if raw.node_type == "JobPosting":
            surfaces = [("JobRole", parsed.get("title") or raw.title), ("Company", raw.company_name),
                        ("City", parsed.get("city") or raw.raw_payload.get("city") or raw.raw_payload.get("city_canonical", "")),
                        ("Education", parsed.get("education") or raw.raw_payload.get("education") or raw.raw_payload.get("education_canonical", ""))]
        results = []
        for entity_type, surface in surfaces:
            if not surface:
                continue
            if entity_type == "City":
                active_linker.add_dynamic_city(surface)
            results.append((entity_type, surface, active_linker.link(entity_type, surface)))
        for skill in parsed.get("skills", []):
            skill["raw_record_id"] = raw.id
            surface = skill.get("surface_form") or skill.get("skill_name", "")
            if surface:
                results.append(("Skill", surface, {
                    "entity_id": skill.get("skill_id") or None, "confidence": float(skill.get("confidence") or 0),
                    "status": skill.get("link_status") or "new_candidate", "candidates": skill.get("link_candidates") or [],
                }))
        for entity_type, surface, result in results:
            normalized_surface = normalize_surface(surface)
            row = db.scalar(select(EntityLink).where(
                EntityLink.batch_id == batch.id, EntityLink.raw_record_id == raw.id,
                EntityLink.entity_type == entity_type, EntityLink.normalized_surface_form == normalized_surface))
            if row is None:
                row = EntityLink(batch_id=batch.id, raw_record_id=raw.id, entity_type=entity_type,
                                 surface_form=surface, normalized_surface_form=normalized_surface)
                db.add(row)
            row.entity_id, row.confidence, row.status = result["entity_id"], result["confidence"], result["status"]
            row.candidates = result["candidates"]
            row.entity_origin = "synthetic" if entity_type in {"City", "Education"} else "asset"
            row.linker_version = LINKER_VERSION
            db.flush()
            linked_count += 1
        normalized.data = parsed
        extracted = db.scalar(select(ExtractedRecord).where(
            ExtractedRecord.batch_id == batch.id, ExtractedRecord.raw_record_id == raw.id))
        if extracted:
            extracted.data = deepcopy(parsed)
    db.flush()
    return {"links": linked_count, "unresolved": db.scalar(select(func.count()).select_from(EntityLink).where(
        EntityLink.batch_id == batch.id, EntityLink.status == "unresolved")) or 0}


def normalize_batch(db: Session, batch: PipelineBatch, *, link: bool | None = None, write_log: bool = True) -> dict:
    enabled = settings.entity_linker_enabled if link is None else link
    active_linker = refresh_entity_linker(db) if enabled else EntityLinker()
    token = ACTIVE_LINKER.set(active_linker)
    try:
        counts = parse_batch(db, batch)
        counts.update(link_batch(db, batch, active_linker) if enabled else {"links": 0, "unresolved": 0})
        batch.metadata_json = {**(batch.metadata_json or {}), "linker_version": LINKER_VERSION,
                               "linker_enabled": enabled, "linker_missing_eligibility": active_linker.missing_eligibility}
        batch.status, batch.stage = "completed", "normalize"
        if write_log:
            db.add(PipelineStageLog(batch_id=batch.id, stage="normalize", status="completed", statistics=counts))
        db.flush()
        return counts
    finally:
        ACTIVE_LINKER.reset(token)


def ensure_normalized(db: Session, batch: PipelineBatch) -> dict:
    log = db.scalar(select(PipelineStageLog).where(
        PipelineStageLog.batch_id == batch.id, PipelineStageLog.stage == "normalize"))
    if log:
        return {"status": "skipped", "reason": "already_normalized", **(log.statistics or {})}
    return {"status": "completed", **normalize_batch(db, batch)}
