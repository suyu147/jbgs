import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import engine
from app.models import EntityLink, FeatureSnapshot, NormalizedRecord, PipelineBatch, RawRecord, Signal
from app.services_feature import build_feature_stage, normalize_period


@pytest.fixture
def db_session():
    with Session(engine) as db:
        yield db
        db.rollback()
        db.execute(delete(Signal))
        db.execute(delete(FeatureSnapshot))
        db.execute(delete(EntityLink).where(EntityLink.batch_id == "batch_m3"))
        db.execute(delete(NormalizedRecord).where(NormalizedRecord.batch_id == "batch_m3"))
        db.execute(delete(RawRecord).where(RawRecord.batch_id == "batch_m3"))
        db.execute(delete(PipelineBatch).where(PipelineBatch.id == "batch_m3"))
        db.commit()


def _raw(db, batch_id, title, month, source, index):
    record = RawRecord(
        id=f"raw_m3_{index}", batch_id=batch_id, source_record_id=f"ext_{index}", node_type="JobPosting",
        source_canonical=source, company_name="企业", title=title, content="这是一段长度足够用于特征计算的岗位描述内容。",
        raw_payload={"published_date_clean": f"{month}-15"}, source_locator={"row": index},
        metadata_json={}, content_sha256=f"sha_{index}",
    )
    db.add(record)
    return record


def test_period_normalization_contract():
    assert normalize_period("2025-01-31") == ("2025-01", "month")
    assert normalize_period("2025Q2") == ("2025-Q2", "quarter")
    assert normalize_period("2025年第3季度") == ("2025-Q3", "quarter")
    assert normalize_period("time_2025_08") == ("2025-08", "month")


def test_feature_stage_distinct_postings_coverage_and_signals(db_session):
    batch = PipelineBatch(id="batch_m3", source_type="upload", source_name="m3.csv")
    db_session.add(batch)
    index = 0
    # Five distinct postings in the first month, with one duplicate observation.
    for source in ("a", "b"):
        for _ in range(5):
            index += 1
            raw = _raw(db_session, batch.id, "数据工程师", "2025-01", source, index)
            db_session.add(EntityLink(id=f"link_m3_{index}", batch_id=batch.id, raw_record_id=raw.id, entity_type="JobRole", surface_form="数据工程师", normalized_surface_form="数据工程师", entity_id="role:data", confidence=1, status="accepted", candidates=[]))
            db_session.add(EntityLink(id=f"skill_m3_{index}", batch_id=batch.id, raw_record_id=raw.id, entity_type="Skill", surface_form="Python", normalized_surface_form="python", entity_id="skill:python", confidence=1, status="accepted", candidates=[]))
            db_session.add(NormalizedRecord(id=f"norm_m3_{index}", batch_id=batch.id, raw_record_id=raw.id, data={"title": "数据工程师"}, linker_version="test"))
    index += 1
    duplicate = _raw(db_session, batch.id, "数据工程师", "2025-01", "a", index)
    duplicate.duplicate_of = "raw_m3_1"
    db_session.add(NormalizedRecord(id=f"norm_m3_{index}", batch_id=batch.id, raw_record_id=duplicate.id, data={"title": "数据工程师"}, linker_version="test"))
    # A later period has a different top skill, producing capability shift and skill surge.
    for source in ("a", "b"):
        for _ in range(6):
            index += 1
            raw = _raw(db_session, batch.id, "数据工程师", "2025-02", source, index)
            db_session.add(EntityLink(id=f"link_m3_{index}", batch_id=batch.id, raw_record_id=raw.id, entity_type="JobRole", surface_form="数据工程师", normalized_surface_form="数据工程师", entity_id="role:data", confidence=1, status="accepted", candidates=[]))
            db_session.add(EntityLink(id=f"skill_m3_{index}", batch_id=batch.id, raw_record_id=raw.id, entity_type="Skill", surface_form="Rust", normalized_surface_form="rust", entity_id="skill:rust", confidence=1, status="accepted", candidates=[]))
            db_session.add(NormalizedRecord(id=f"norm_m3_{index}", batch_id=batch.id, raw_record_id=raw.id, data={"title": "数据工程师"}, linker_version="test"))
    db_session.commit()
    result = build_feature_stage(db_session, batch_id=batch.id)
    db_session.commit()
    snapshot = db_session.query(FeatureSnapshot).filter_by(period_key="2025-01", cohort_key="role:role:data").first()
    assert snapshot is not None
    assert snapshot.metrics["posting_count"] == 10
    assert snapshot.metrics["coverage"] == 1
    assert result["feature_count"] == 2
    assert db_session.query(Signal).filter(Signal.signal_type == "capability_shift").count() >= 1
    # Recompute is idempotent for snapshots and signals.
    second = build_feature_stage(db_session, batch_id=batch.id)
    db_session.commit()
    assert second["feature_count"] == 2
    assert db_session.query(FeatureSnapshot).count() == 2
