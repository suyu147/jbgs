from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import APP_DATA_ROOT, settings
from app.database import engine
from app.main import app
from app.models import (
    AppUser,
    FavoriteJob,
    ResumeProfile,
    ResumeSkill,
    UserWorkspaceProfile,
)


client = TestClient(app)


def personal_session() -> tuple[dict[str, str], dict]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": settings.personal_username, "password": settings.personal_password, "portal": "personal"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    return {"Authorization": f"Bearer {payload['accessToken']}"}, payload["user"]


def test_workspace_profile_persists_for_current_account():
    headers, user = personal_session()
    body = {
        "audience": "seeker",
        "profile": {"fullName": "测试用户", "desiredRole": "数据分析师", "companyName": "不应保存"},
        "workStyleAssessment": {"evidenceOnly": True},
    }
    saved = client.put("/api/v1/me/workspace-profile", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    restored = client.get("/api/v1/me/workspace-profile", headers=headers)
    assert restored.status_code == 200
    data = restored.json()["data"]
    assert data["audience"] == "seeker"
    assert data["profile"]["fullName"] == "测试用户"
    assert "companyName" not in data["profile"]
    assert "hrEvaluationSettings" not in data
    rejected = client.put("/api/v1/me/workspace-profile", headers=headers, json={"audience": "hr"})
    assert rejected.status_code == 422
    with Session(engine) as db:
        db.execute(delete(UserWorkspaceProfile).where(UserWorkspaceProfile.user_id == user["id"]))
        db.commit()


def test_resume_list_and_delete_enforce_account_ownership():
    headers, user = personal_session()
    stored_file = APP_DATA_ROOT / "uploads" / "ownership-test.txt"
    stored_file.write_text("Python 数据分析", encoding="utf-8")
    with Session(engine) as db:
        profile = ResumeProfile(
            user_id=user["id"], file_name="ownership-test.txt", file_path=str(stored_file),
            education="本科", experience_years=2, certificates=[], raw_text="Python 数据分析", confirmed=True,
        )
        db.add(profile)
        db.flush()
        db.add(ResumeSkill(resume_id=profile.id, skill_id="", skill_name="Python", evidence="测试", confidence=1))
        resume_id = profile.id
        db.commit()
    listed = client.get("/api/v1/me/resumes", headers=headers)
    assert listed.status_code == 200
    assert any(item["resumeId"] == resume_id for item in listed.json()["data"]["items"])
    preview = client.get(f"/api/v1/me/resumes/{resume_id}/file", headers=headers)
    assert preview.status_code == 200
    assert preview.content == "Python 数据分析".encode("utf-8")
    deleted = client.delete(f"/api/v1/me/resumes/{resume_id}", headers=headers)
    assert deleted.status_code == 200
    assert not stored_file.exists()
    with Session(engine) as db:
        assert db.get(ResumeProfile, resume_id) is None
        assert not db.scalars(select(ResumeSkill).where(ResumeSkill.resume_id == resume_id)).all()


def test_favorite_jobs_are_idempotent_and_account_scoped():
    username = f"favorite_{uuid4().hex[:10]}"
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "123456", "displayName": "收藏测试"},
    )
    assert registered.status_code == 201, registered.text
    session = registered.json()["data"]
    headers = {"Authorization": f"Bearer {session['accessToken']}"}
    role = client.get("/api/v1/jobs", params={"pageSize": 1}).json()["data"]["items"][0]
    first = client.post("/api/v1/me/favorites", headers=headers, json={"roleId": role["id"]})
    second = client.post("/api/v1/me/favorites", headers=headers, json={"roleId": role["id"]})
    assert first.status_code == 201
    assert second.status_code == 201
    listed = client.get("/api/v1/me/favorites", headers=headers).json()["data"]
    assert listed["total"] == 1
    assert listed["items"][0]["roleId"] == role["id"]
    removed = client.delete(f"/api/v1/me/favorites/{role['id']}", headers=headers)
    assert removed.status_code == 200
    assert client.get("/api/v1/me/favorites", headers=headers).json()["data"]["total"] == 0
    with Session(engine) as db:
        db.execute(delete(FavoriteJob).where(FavoriteJob.user_id == session["user"]["id"]))
        db.execute(delete(AppUser).where(AppUser.id == session["user"]["id"]))
        db.commit()


def test_removed_talent_assessment_endpoint_is_not_exposed():
    headers, _ = personal_session()
    jobs = client.get("/api/v1/jobs", params={"pageSize": 1}).json()["data"]["items"]
    assert jobs
    denied = client.post(
        "/api/v1/talent-assessments",
        headers=headers,
        json={"roleId": jobs[0]["id"], "roleName": jobs[0]["name"], "settings": {"passThreshold": 70}},
    )
    assert denied.status_code == 404


def test_registration_always_creates_personal_account():
    username = f"user_{uuid4().hex[:10]}"
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "123456", "displayName": "注册测试", "portal": "admin", "role": "admin"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["user"]["role"] == "personal"
    with Session(engine) as db:
        db.execute(delete(AppUser).where(AppUser.username == username))
        db.commit()
