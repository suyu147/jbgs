from datetime import datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import engine
from app.models import AuditLog, RawRecord, ReviewAction, ReviewComment, RoleDefinitionDraft, RoleDefinitionVersion
from app.services_publish import PublishValidationError, publish_neo4j_version, validate_evidence


@pytest.fixture
def db_session():
    with Session(engine) as db:
        yield db
        db.rollback()
        db.execute(delete(RoleDefinitionVersion).where(RoleDefinitionVersion.version_id.like("version_m5_%")))
        db.execute(delete(RoleDefinitionDraft).where(RoleDefinitionDraft.id.like("draft_m5_%")))
        db.execute(delete(RawRecord).where(RawRecord.id.like("raw_m5_%")))
        db.commit()


def _raw(db, index: int, source: str) -> RawRecord:
    row = RawRecord(
        id=f"raw_m5_{index}", batch_id="batch_m5", source_record_id="", node_type="JobPosting",
        source_canonical=source, company_name="企业", title="数据工程师",
        content="负责数据平台建设、数据质量治理和业务系统交付。",
        raw_payload={}, source_locator={"row": index}, metadata_json={}, content_sha256=f"sha_m5_{index}",
    )
    db.add(row)
    return row


def test_pipeline_publish_evidence_requires_resolvable_records(db_session):
    draft = RoleDefinitionDraft(
        id="draft_m5_source", role_name="数据工程师", candidate_type="new_role", origin="pipeline",
        batch_id="batch_m5", evidence_grade="source_record",
        definition={"source_count": 3, "evidence_record_count": 5, "confidence": 0.8},
        evidence=[{"type": "source_record", "recordId": f"raw_m5_{index}"} for index in range(1, 6)],
    )
    for index, source in enumerate(("a", "b", "c", "a", "b"), 1):
        _raw(db_session, index, source)
    db_session.flush()
    assert validate_evidence(db_session, draft) == {"grade": "source_record", "checked": True, "evidenceCount": 5}
    draft.evidence[0]["recordId"] = "dangling-record"
    with pytest.raises(PublishValidationError, match="无法解引用"):
        validate_evidence(db_session, draft)


def test_legacy_publish_evidence_is_exempt(db_session):
    draft = RoleDefinitionDraft(
        id="draft_m5_legacy", role_name="旧岗位", candidate_type="new_role", origin="legacy",
        evidence_grade="legacy", definition={}, evidence=[{"type": "curated_reference"}],
    )
    assert validate_evidence(db_session, draft)["checked"] is False


def test_neo4j_version_write_is_idempotent_merge():
    class FakeNeo4j:
        statement = ""
        parameters = {}

        def query(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters
            return [{"id": parameters["version_id"], "status": "published", "roleId": parameters["role_id"]}]

    version = RoleDefinitionVersion(
        id="mysql_m5_version", version_id="version_m5_publish", draft_id="draft_m5", role_id="role_m5",
        role_name="数据工程师", candidate_type="new_role", status="approved", definition={"required_skills": []},
        evidence=[], origin="legacy", batch_id="", evidence_grade="legacy", publish_result={},
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    graph = FakeNeo4j()
    result = publish_neo4j_version(graph, version)
    assert result["status"] == "published"
    assert "MERGE (v:RoleDefinitionVersion {version_id:$version_id})" in graph.statement
    assert "CREATE (v:RoleDefinitionVersion" not in graph.statement
    assert graph.parameters["version_id"] == version.version_id


def test_approve_creates_mysql_version_without_calling_neo4j(db_session, monkeypatch):
    from app import main as api

    draft = RoleDefinitionDraft(
        id="draft_m5_approve", role_name="旧岗位复核", candidate_type="new_role", status="pending",
        definition={
            "core_responsibilities": ["职责"], "required_skills": ["技能"],
            "bonus_skills": ["加分技能"], "application_scenarios": ["场景"],
        }, evidence=[{"type": "curated_reference"}], origin="legacy", batch_id="", evidence_grade="legacy",
    )
    db_session.add(draft)
    db_session.commit()

    def unexpected_graph_write(*args, **kwargs):
        raise AssertionError("approve must not call Neo4j")

    monkeypatch.setattr(api.neo4j, "query", unexpected_graph_write)
    result = api.review(draft.id, api.ReviewRequest(action="approve", note="通过"), db_session)["data"]
    assert result["status"] == "approved"
    assert db_session.query(RoleDefinitionVersion).filter_by(version_id=result["versionId"]).count() == 0
    assert db_session.query(ReviewAction).filter_by(draft_id=draft.id, action="approve").count() == 1
    assert db_session.query(ReviewComment).filter_by(draft_id=draft.id, action="approve").count() == 1
    db_session.delete(draft)
    db_session.query(ReviewAction).filter_by(draft_id="draft_m5_approve").delete()
    db_session.query(ReviewComment).filter_by(draft_id="draft_m5_approve").delete()
    db_session.query(AuditLog).filter_by(target_id="draft_m5_approve").delete()
    db_session.commit()
