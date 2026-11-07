from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine
from app.main import app
from app.models import (
    MatchReport,
    ResumeProfile,
    ResumeSkill,
    RoleDefinitionDraft,
    RawRecord,
    PipelineBatch,
    TalentAssessmentBatch,
    TalentAssessmentCandidate,
)


client = TestClient(app)


def login(username: str, password: str, portal: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password, "portal": portal})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def test_enterprise_portal_batch_matching_and_admin_review_handoff():
    enterprise_headers = login(settings.enterprise_username, settings.enterprise_password, "enterprise")
    personal_headers = login(settings.personal_username, settings.personal_password, "personal")
    admin_headers = login(settings.admin_username, settings.admin_password, "admin")

    assert client.get("/api/v1/enterprise/overview", headers=personal_headers).status_code == 403
    wrong_portal = client.post(
        "/api/v1/auth/login",
        json={"username": settings.enterprise_username, "password": settings.enterprise_password, "portal": "personal"},
    )
    assert wrong_portal.status_code == 403

    marker = uuid4().hex[:10]
    upload = client.post(
        "/api/v1/enterprise/resumes",
        headers=enterprise_headers,
        files=[
            ("files", (f"候选人甲-{marker}.txt", "本科，3年经验，掌握 Python、SQL、Docker 和数据分析。".encode("utf-8"), "text/plain")),
            ("files", (f"候选人乙-{marker}.txt", "硕士，5年经验，掌握 Python、机器学习、项目管理和沟通协作。".encode("utf-8"), "text/plain")),
        ],
    )
    assert upload.status_code == 201, upload.text
    resumes = upload.json()["data"]["items"]
    assert len(resumes) == 2
    assert all(85 <= item["contentConfidence"] <= 97 for item in resumes)

    role = client.get("/api/v1/jobs", params={"pageSize": 1}).json()["data"]["items"][0]
    assessed = client.post(
        "/api/v1/enterprise/assessments",
        headers=enterprise_headers,
        json={"roleId": role["id"], "resumeIds": [item["resumeId"] for item in resumes]},
    )
    assert assessed.status_code == 201, assessed.text
    batch = assessed.json()["data"]
    assert batch["candidateCount"] == 2
    assert batch["completedCount"] == 2
    assert all(85 <= item["result"]["contentConfidence"] <= 97 for item in batch["candidates"])

    role_name = f"企业智能运营工程师-{marker}"
    submitted = client.post(
        "/api/v1/enterprise/job-submissions",
        headers=enterprise_headers,
        json={
            "companyName": "职能洞察示范企业",
            "contact": "hr@example.com",
            "roleName": role_name,
            "jobCategory": "人工智能应用",
            "location": "杭州",
            "openingCount": 3,
            "responsibilities": ["负责企业智能体运营与效果评估", "协同业务团队优化工作流"],
            "requiredSkills": ["Python", "SQL"],
            "bonusSkills": ["Docker"],
            "applicationScenarios": ["企业知识库运营"],
            "jdText": "招聘企业智能运营工程师，负责智能体运营、效果评估和工作流优化，要求掌握 Python、SQL 和 Docker。",
        },
    )
    assert submitted.status_code == 201, submitted.text
    draft_id = submitted.json()["data"]["id"]
    with Session(engine) as db:
        draft = db.get(RoleDefinitionDraft, draft_id)
        evidence_id = draft.evidence[0]["recordId"]
        raw_record = db.get(RawRecord, evidence_id)
        assert raw_record is not None
        assert raw_record.batch_id == draft.definition["batch_id"]
        assert raw_record.company_name == "职能洞察示范企业"
    reviews = client.get("/api/v1/reviews", headers=admin_headers, params={"status": "pending"})
    assert reviews.status_code == 200
    assert any(item["id"] == draft_id and item["candidateType"] == "new_role" for item in reviews.json()["data"])

    with Session(engine) as db:
        batch_row = db.get(TalentAssessmentBatch, batch["id"])
        candidate_rows = db.scalars(
            select(TalentAssessmentCandidate).where(TalentAssessmentCandidate.batch_id == batch["id"])
        ).all()
        report_ids = [item.match_report_id for item in candidate_rows if item.match_report_id]
        resume_ids = [item["resumeId"] for item in resumes]
        stored_files = [Path(item.file_path) for item in db.scalars(select(ResumeProfile).where(ResumeProfile.id.in_(resume_ids))).all()]
        db.execute(delete(TalentAssessmentCandidate).where(TalentAssessmentCandidate.batch_id == batch["id"]))
        if batch_row:
            db.delete(batch_row)
        if report_ids:
            db.execute(delete(MatchReport).where(MatchReport.id.in_(report_ids)))
        db.execute(delete(ResumeSkill).where(ResumeSkill.resume_id.in_(resume_ids)))
        db.execute(delete(ResumeProfile).where(ResumeProfile.id.in_(resume_ids)))
        db.execute(delete(RoleDefinitionDraft).where(RoleDefinitionDraft.id == draft_id))
        db.execute(delete(RawRecord).where(RawRecord.batch_id == draft.definition["batch_id"]))
        db.execute(delete(PipelineBatch).where(PipelineBatch.id == draft.definition["batch_id"]))
        db.commit()
        for stored_file in stored_files:
            stored_file.unlink(missing_ok=True)
