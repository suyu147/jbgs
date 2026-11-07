import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import engine
from app.models import EntityLink, FeatureSnapshot, NormalizedRecord, PipelineBatch, RawRecord, RoleDefinitionDraft, Signal
from app.services_m4 import build_definition_stage


@pytest.fixture
def db_session():
    with Session(engine) as db:
        yield db
        db.rollback()
        db.execute(delete(RoleDefinitionDraft).where(RoleDefinitionDraft.origin == "pipeline"))
        db.execute(delete(Signal).where(Signal.id.like("sig_m4_%")))
        db.execute(delete(FeatureSnapshot).where(FeatureSnapshot.id.like("feature_m4_%")))
        db.execute(delete(EntityLink).where(EntityLink.batch_id == "batch_m4"))
        db.execute(delete(NormalizedRecord).where(NormalizedRecord.batch_id == "batch_m4"))
        db.execute(delete(RawRecord).where(RawRecord.batch_id == "batch_m4"))
        db.execute(delete(PipelineBatch).where(PipelineBatch.id == "batch_m4"))
        db.commit()


def _record(db, index: int, source: str) -> RawRecord:
    row = RawRecord(
        id=f"raw_m4_{index}", batch_id="batch_m4", source_record_id=f"ext_m4_{index}", node_type="JobPosting",
        source_canonical=source, company_name="企业", title="智能数据工程师",
        content="负责建设数据平台并维护数据质量，参与模型和业务系统的交付。",
        raw_payload={"published_date_clean": "2025-05-15"}, source_locator={"row": index},
        metadata_json={}, content_sha256=f"sha_m4_{index}",
    )
    db.add(row)
    db.add(NormalizedRecord(
        id=f"norm_m4_{index}", batch_id="batch_m4", raw_record_id=row.id,
        data={"title": row.title, "responsibilities": ["建设数据平台并维护数据质量"], "skills": [{"skill_id": "skill:python", "skill_name": "Python", "link_status": "accepted"}]},
        linker_version="test",
    ))
    db.add(EntityLink(
        id=f"link_m4_{index}", batch_id="batch_m4", raw_record_id=row.id, entity_type="Skill",
        surface_form="Python", normalized_surface_form="python", entity_id="skill:python", confidence=1,
        status="accepted", candidates=[],
    ))
    return row


def test_definition_stage_creates_traceable_new_role(db_session):
    batch = PipelineBatch(id="batch_m4", source_type="upload", source_name="m4.csv")
    db_session.add(batch)
    rows = [_record(db_session, index, source) for index, source in enumerate(("a", "b", "c", "a", "b"), 1)]
    db_session.add(FeatureSnapshot(
        id="feature_m4_new", period_key="2025-05", granularity="month", cohort_key="title:智能数据工程师",
        cohort_basis="title", metrics={"posting_count": 5, "coverage": 1, "top5_skills": ["skill:python"]},
        evidence_ids=[row.id for row in rows], input_summary={}, feature_version="test",
    ))
    db_session.add(Signal(
        id="sig_m4_new", signal_type="emerging_role", cohort_key="title:智能数据工程师", period_key="2025-05",
        granularity="month", severity="high", status="active", metrics={"posting_count": 5, "source_count": 3},
        evidence_ids=[row.id for row in rows], suppression_key="emerging_role:title:智能数据工程师", signal_version="test",
    ))
    db_session.commit()

    result = build_definition_stage(db_session, batch_id="batch_m4")
    db_session.commit()
    draft = db_session.scalar(db_session.query(RoleDefinitionDraft).filter_by(origin="pipeline").statement)
    assert result["created"] == 1
    assert draft is not None
    assert draft.candidate_type == "new_role"
    assert draft.batch_id == "batch_m4"
    assert draft.evidence_grade == "source_record"
    assert len(draft.evidence) == 5
    assert draft.definition["cohort_key"] == "title:智能数据工程师"
    assert draft.definition["required_skills"][0]["skill_id"] == "skill:python"


def test_definition_stage_rejects_new_role_without_source_threshold(db_session):
    batch = PipelineBatch(id="batch_m4", source_type="upload", source_name="m4.csv")
    db_session.add(batch)
    rows = [_record(db_session, index, "only") for index in range(1, 6)]
    db_session.add(Signal(
        id="sig_m4_low", signal_type="emerging_role", cohort_key="title:智能数据工程师", period_key="2025-05",
        granularity="month", severity="medium", status="active", metrics={"posting_count": 5, "source_count": 1},
        evidence_ids=[row.id for row in rows], suppression_key="emerging_role:title:智能数据工程师", signal_version="test",
    ))
    db_session.commit()
    result = build_definition_stage(db_session, batch_id="batch_m4")
    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["skip_reasons"]["new_role_evidence_threshold"] == 1
