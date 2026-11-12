import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine
from app.main import app
from app.models import EntityLink, ExtractedRecord, NormalizedRecord, PipelineBatch, PipelineStageLog, RawRecord, RoleDefinitionDraft
from app.pipeline import _split_txt, normalize_node_type, read_upload
from app.linker import EntityLinker


client = TestClient(app)


def test_node_type_uses_explicit_type_and_unique_primary_key_before_column_score():
    assert normalize_node_type({"node_type": "Skill", "record_id": "r1", "skill_id": "s1"}) == "Skill"
    assert normalize_node_type({"skill_id": "s1", "entity_name": "Python", "company_name": "ignored"}) == "Skill"


def test_node_type_reports_ambiguous_or_unparseable_rows():
    with pytest.raises(HTTPException) as ambiguous:
        normalize_node_type({"job_title": "岗位", "skill_name": "Python"})
    assert ambiguous.value.status_code == 422
    with pytest.raises(HTTPException) as unresolved:
        normalize_node_type({"unknown": "value"})
    assert unresolved.value.status_code == 422


def test_txt_split_strategy_and_line_locators():
    rows, metadata = read_upload(
        "岗位.txt",
        "职位名称：数据工程师\n负责数据平台建设与治理，熟悉 Python 和 SQL。\n====\n职位名称：算法工程师\n负责模型研发和上线，掌握机器学习算法。".encode(),
    )
    assert metadata["split_strategy"] == "explicit_separator"
    assert rows[0]["title"] == "数据工程师"
    assert rows[0]["__locator"] == {"lineStart": 1, "lineEnd": 2}
    assert rows[1]["__locator"] == {"lineStart": 4, "lineEnd": 5}
    _, fallback = _split_txt("正文第一行\n正文第二行")
    assert fallback == "whole_file"


def test_entity_linker_respects_match_tiers_ties_and_dynamic_city_cap():
    linker = EntityLinker([
        {"id": "s-python", "type": "Skill", "name": "Python", "aliases": ["蟒蛇语言"]},
        {"id": "s-pythan", "type": "Skill", "name": "Pythan", "aliases": []},
        {"id": "r-data", "type": "JobRole", "name": "数据工程师", "aliases": []},
    ])
    assert linker.link("Skill", "Python")["confidence"] == 1.0
    assert linker.link("Skill", "蟒蛇语言")["confidence"] == 0.9
    assert linker.link("JobRole", "数据工程师") ["status"] == "accepted"
    tied = linker.link("Skill", "Pythin")
    assert tied["status"] == "unresolved" and tied["entity_id"] is None
    assert linker.link("Company", "未登记企业")["status"] == "new_candidate"
    for index in range(25):
        linker.add_dynamic_city(f"测试城市{index}")
    assert linker.dynamic_city_count == 20
    assert linker.link("City", "测试城市19")["entity_id"] == "city:测试城市19"


def test_csv_fixed_aliases_read_without_guessing_columns():
    rows, metadata = read_upload(
        "roles.csv",
        "record_id,source_canonical,company_name,job_title,description\nr1,平台甲,公司甲,数据工程师,负责数据平台治理与建设，要求熟悉Python和SQL".encode(),
    )
    assert metadata["adapter"] == "csv"
    assert rows[0]["record_id"] == "r1"


def test_ingest_sources_persists_traceable_batch_and_dataset_file_upload_is_gone():
    Base.metadata.create_all(engine)
    login = client.post("/api/v1/auth/login", json={
        "username": settings.admin_username, "password": settings.admin_password, "portal": "admin",
    })
    headers = {"Authorization": f"Bearer {login.json()['data']['accessToken']}"}
    response = client.post("/ingest/sources", headers=headers, json={
        "records": [{
            "record_id": "external-1", "node_type": "JobPosting", "company_name": "测试企业",
            "job_title": "数据治理工程师", "description": "负责数据治理平台建设，维护数据质量并推进标准落地。",
            "source_canonical": "测试平台", "headcount": 8,
        }],
    })
    assert response.status_code == 201, response.text
    result = response.json()["data"]
    detail = client.get(f"/ingest/batches/{result['batchId']}", headers=headers)
    assert detail.status_code == 200, detail.text
    record = detail.json()["data"]["records"][0]
    assert record["sourceRecordId"] == "external-1"
    assert record["nodeType"] == "JobPosting"
    assert record["content"].startswith("负责数据治理")
    assert detail.json()["data"]["stages"][0]["status"] == "completed"
    gone = client.post("/api/v1/datasets", headers=headers, files={
        "file": ("roles.csv", b"record_id,description\nr1,content long enough for validation", "text/csv"),
    }, data={"name": "legacy upload"})
    assert gone.status_code == 410
    with Session(engine) as db:
        db.execute(delete(PipelineStageLog).where(PipelineStageLog.batch_id == result["batchId"]))
        db.execute(delete(RawRecord).where(RawRecord.batch_id == result["batchId"]))
        db.execute(delete(PipelineBatch).where(PipelineBatch.id == result["batchId"]))
        db.commit()


def test_enterprise_submission_only_ingests_raw_record(monkeypatch):
    Base.metadata.create_all(engine)
    from app import main as api

    monkeypatch.setattr("app.services_parse.parse_jd", lambda _: {})
    login = client.post("/api/v1/auth/login", json={
        "username": settings.enterprise_username, "password": settings.enterprise_password, "portal": "enterprise",
    })
    headers = {"Authorization": f"Bearer {login.json()['data']['accessToken']}"}
    response = client.post("/api/v1/enterprise/job-submissions", headers=headers, json={
        "companyName": "接入测试企业", "roleName": "数据治理工程师", "jobCategory": "数据技术",
        "openingCount": 4, "responsibilities": ["建设数据治理体系"], "requiredSkills": ["Python"],
        "jdText": "负责数据治理平台建设，制定数据标准、质量规则并推动跨团队的数据治理实践。",
    })
    assert response.status_code == 201, response.text
    batch_id = response.json()["data"]["batchId"]
    assert response.json()["data"]["accepted"] == 1
    with Session(engine) as db:
        raw = db.query(RawRecord).filter_by(batch_id=batch_id).one()
        assert raw is not None
        assert raw.company_name == "接入测试企业" and raw.title == "数据治理工程师"
        assert raw.raw_payload["openingCount"] == 4
        assert db.query(RoleDefinitionDraft).filter(RoleDefinitionDraft.evidence.contains([{"recordId": raw.id}])).count() == 0
        db.execute(delete(PipelineStageLog).where(PipelineStageLog.batch_id == batch_id))
        db.execute(delete(RawRecord).where(RawRecord.batch_id == batch_id))
        db.execute(delete(PipelineBatch).where(PipelineBatch.id == batch_id))
        db.commit()


def test_enabled_linker_persists_extraction_and_unresolved_links(monkeypatch):
    Base.metadata.create_all(engine)
    from app import main as api
    from app.linker import EntityLinker

    monkeypatch.setattr(api.settings, "entity_linker_enabled", True)
    monkeypatch.setattr("app.services_parse.refresh_entity_linker", lambda db: EntityLinker(
        [{"id": "skill-python", "type": "Skill", "name": "Python", "aliases": ["蟒蛇语言"]}],
        missing_eligibility={"Skill": 3},
    ))
    login = client.post("/api/v1/auth/login", json={
        "username": settings.admin_username, "password": settings.admin_password, "portal": "admin",
    })
    headers = {"Authorization": f"Bearer {login.json()['data']['accessToken']}"}
    response = client.post("/ingest/sources", headers=headers, json={
        "node_type": "JobPosting", "company_name": "未登记企业", "title": "未知岗位", "city": "火星市",
        "content": "岗位名称：未知岗位。工作地点：火星。任职要求：熟悉 Python，掌握陌生技能治理与分析。",
    })
    assert response.status_code == 201, response.text
    batch_id = response.json()["data"]["batchId"]
    detail = client.get(f"/ingest/batches/{batch_id}", headers=headers).json()["data"]
    assert detail["metadata"]["linker_version"] == "entity-linker-v1"
    assert detail["metadata"]["linker_missing_eligibility"] == {"Skill": 3}
    assert len([row for row in detail["stages"] if row["stage"] == "normalize"]) == 1
    assert any(item["entityType"] == "Company" and item["status"] == "new_candidate" for item in detail["entityLinks"])
    assert any(item["entityType"] == "City" and item["origin"] == "synthetic" for item in detail["entityLinks"])
    with Session(engine) as db:
        assert db.query(ExtractedRecord).filter_by(batch_id=batch_id).count() == 1
        assert db.query(NormalizedRecord).filter_by(batch_id=batch_id).count() == 1
        assert db.query(EntityLink).filter_by(batch_id=batch_id, status="new_candidate").count() >= 1
        db.execute(delete(EntityLink).where(EntityLink.batch_id == batch_id))
        db.execute(delete(ExtractedRecord).where(ExtractedRecord.batch_id == batch_id))
        db.execute(delete(NormalizedRecord).where(NormalizedRecord.batch_id == batch_id))
        db.execute(delete(PipelineStageLog).where(PipelineStageLog.batch_id == batch_id))
        db.execute(delete(RawRecord).where(RawRecord.batch_id == batch_id))
        db.execute(delete(PipelineBatch).where(PipelineBatch.id == batch_id))
        db.commit()
