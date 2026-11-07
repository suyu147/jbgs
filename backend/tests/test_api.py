import io
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import delete

from app.config import APP_DATA_ROOT, settings
from app.database import engine
from app import main as api
from app import services
from app.main import app
from app.models import AuditLog, LearningPath, MatchReport, RoleDefinitionDraft
from sqlalchemy.orm import Session


client = TestClient(app)


def test_publish_definition_rejects_missing_cross_source_evidence():
    try:
        api._validate_publishable_definition(
            {
                "core_responsibilities": ["测试职责"],
                "required_skills": ["测试技能"],
                "bonus_skills": ["加分技能"],
                "application_scenarios": ["测试场景"],
                "posting_count": 5,
                "source_count": 1,
                "evidence_record_count": 5,
            },
            "new_role",
        )
    except api.HTTPException as exc:
        assert exc.status_code == 409
        assert "2 个来源" in exc.detail
    else:
        raise AssertionError("单来源新岗位不应通过发布证据门禁")


def payload(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["requestId"].startswith("req_")
    return body["data"]


def test_capability_radar_uses_stable_dimensions_and_current_percentages():
    axes = api._capability_radar_axes({
        "skillScore": 72.4,
        "breadthScore": 75,
        "workStyleScore": 68,
        "dimensions": [
            {"name": "skills", "score": 72.4},
            {"name": "experience", "score": 66.7},
            {"name": "education", "score": 80},
        ],
        "educationProfile": {"current": 66.7, "target": 69.2},
        "experienceProfile": {"current": 37.5, "target": 58.4},
        "radarTargets": {"skills": 78.2, "experience": 58.4, "education": 69.2, "breadth": 74.5, "workStyle": 76.3},
        "gaps": [{"skill": "不应成为雷达轴", "importance": 99, "status": "matched"}],
    })
    assert [axis["name"] for axis in axes] == ["技能", "经验", "学历", "能力广度", "综合素养"]
    assert [axis["current"] for axis in axes] == [72.4, 37.5, 66.7, 75, 68]
    assert [axis["target"] for axis in axes] == [78.2, 58.4, 69.2, 74.5, 76.3]
    assert any(axis["target"] < 100 for axis in axes)


def login_headers(role: str = "admin") -> dict[str, str]:
    username = settings.admin_username if role == "admin" else settings.personal_username
    password = settings.admin_password if role == "admin" else settings.personal_password
    result = payload(client.post("/api/v1/auth/login", json={"username": username, "password": password, "portal": role}))
    return {"Authorization": f"Bearer {result['accessToken']}"}


def test_authentication_separates_personal_and_admin_portals():
    personal_headers = login_headers("personal")
    me = payload(client.get("/api/v1/auth/me", headers=personal_headers))
    assert me["role"] == "personal"
    denied = client.get("/api/v1/datasets", headers=personal_headers)
    assert denied.status_code == 403
    dashboard_denied = client.get("/api/v1/admin/dashboard", headers=personal_headers)
    assert dashboard_denied.status_code == 403
    mismatch = client.post(
        "/api/v1/auth/login",
        json={"username": settings.personal_username, "password": settings.personal_password, "portal": "admin"},
    )
    assert mismatch.status_code == 403


def test_job_filter_route_precedes_dynamic_job_detail(monkeypatch):
    expected = {
        "fields": [], "skills": [], "trends": [], "postingBuckets": [],
        "sourceCounts": [], "lastSeenBuckets": [], "sorts": [],
    }
    monkeypatch.setattr(api, "job_filter_options", lambda: expected)
    assert payload(client.get("/api/v1/jobs/filters")) == expected


def test_graph_accepts_time_period_entity_type(monkeypatch):
    expected = {"viewMode": "entity", "nodes": [], "edges": []}
    monkeypatch.setattr(api, "graph_data", lambda *args, **kwargs: expected)
    response = client.get(
        "/api/v1/graph",
        params={"viewMode": "entity", "entityType": "period", "limit": 40},
    )
    assert response.status_code == 200
    assert payload(response) == expected


def test_evolution_pdf_compacts_six_skill_forecasts_per_page():
    trend = {
        "series": [
            {
                "skillId": "skill_1",
                "skill": "测试技能",
                "points": [
                    {"period": "2025", "value": 20, "sampleSize": 10},
                    {"period": "2026", "value": 30, "sampleSize": 12},
                ],
            }
        ]
    }
    forecast = {
        "horizon": 3,
        "scenario": "baseline",
        "granularity": "year",
        "skills": [
            {
                "skillId": f"skill_{index}",
                "skill": f"测试技能 {index}",
                "currentDemand": 30,
                "futureDemand": 45,
                "confidence": 0.78,
                "points": [
                    {"period": "2025", "value": 20, "lower": 20, "upper": 20, "observed": True},
                    {"period": "2026", "value": 30, "lower": 30, "upper": 30, "observed": True},
                    {"period": "2027", "value": 36, "lower": 31, "upper": 41, "observed": False},
                    {"period": "2028", "value": 45, "lower": 36, "upper": 54, "observed": False},
                ],
            }
            for index in range(7)
        ],
    }
    content = api._build_evolution_report_pdf("测试岗位", trend, trend, forecast)
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) == 4
    assert reader.metadata.title == "职能洞察 - 测试岗位岗位能力演化趋势报告"


def test_read_only_product_flow():
    admin_headers = login_headers("admin")
    health = payload(client.get("/api/v1/health"))
    assert health["neo4j"] and health["mysql"]

    overview = payload(client.get("/api/v1/overview"))
    assert overview["postingCount"] >= 20_000
    jobs = payload(client.get("/api/v1/jobs", params={"pageSize": 5}))
    assert jobs["items"] and jobs["total"] >= 100
    role_id = jobs["items"][0]["id"]

    detail = payload(client.get(f"/api/v1/jobs/{role_id}"))
    assert detail["skills"]
    assert payload(client.get(f"/api/v1/jobs/{role_id}/skills"))["total"] > 0
    payload(client.get(f"/api/v1/jobs/{role_id}/aliases"))
    payload(client.get(f"/api/v1/jobs/{role_id}/postings"))
    payload(client.get(f"/api/v1/jobs/{role_id}/changes"))

    graph = payload(client.get("/api/v1/graph", params={"roleId": role_id, "limit": 40}))
    assert graph["nodes"] and graph["edges"]
    graph_filters = payload(client.get("/api/v1/graph/filters"))
    stack = next(item for item in graph_filters["techStacks"] if item["count"] > 0)
    stack_graph = payload(
        client.get(
            "/api/v1/graph",
            params={"viewMode": "stack", "techStack": stack["value"], "limit": 40},
        )
    )
    assert stack_graph["viewMode"] == "stack"
    assert stack_graph["nodes"] and stack_graph["statistics"]["roleCount"] > 0
    node_id = graph["nodes"][0]["id"]
    payload(client.get(f"/api/v1/graph/nodes/{node_id}"))
    payload(client.get(f"/api/v1/graph/nodes/{node_id}/neighbors", params={"limit": 20}))

    trends = payload(client.get("/api/v1/evolution/trends", params={"roleId": role_id, "granularity": "year"}))
    assert "series" in trends and "warning" in trends
    assert len(trends["series"]) <= 12
    forecast = payload(client.get("/api/v1/forecasts/overview", params={"roleId": role_id, "granularity": "year"}))
    assert forecast["modelVersion"] == "job-posting-market-share-eb-theilsen-v2.0"
    assert all(
        point["value"] > 0
        for occupation in forecast["occupations"]
        for point in occupation["points"]
        if point["observed"]
    )
    trend_skill_ids = {item["skillId"] for item in trends["series"]}
    forecast_skill_ids = {item["skillId"] for item in forecast["skills"]}
    assert forecast_skill_ids
    assert forecast_skill_ids == trend_skill_ids
    occupation_name = forecast["occupations"][0]["roleName"]
    searched_forecast = payload(client.get("/api/v1/forecasts/overview", params={"keyword": occupation_name}))
    assert searched_forecast["scopeKeyword"] == occupation_name
    assert any(item["roleName"] == occupation_name for item in searched_forecast["occupations"])
    location_forecast = payload(
        client.get(
            "/api/v1/forecasts/overview",
            params={"location": "北京", "granularity": "month"},
        )
    )
    assert location_forecast["scopeLocation"] == "北京"
    assert location_forecast["occupations"]
    assert all(
        point["value"] > 0
        for occupation in location_forecast["occupations"]
        for point in occupation["points"]
        if point["observed"]
    )
    evolution_pdf = client.get("/api/v1/evolution/report", params={"roleId": role_id, "format": "pdf"})
    assert evolution_pdf.status_code == 200
    assert evolution_pdf.content.startswith(b"%PDF")
    assert "filename*=UTF-8''" in evolution_pdf.headers["content-disposition"]
    payload(client.get("/api/v1/evolution/candidates"))
    payload(client.get("/api/v1/datasets", params={"pageSize": 5}, headers=admin_headers))
    payload(client.get("/api/v1/reviews", headers=admin_headers))
    quality = payload(client.get("/api/v1/quality/summary", headers=admin_headers))
    assert quality["evaluation"]["passed"] is True
    payload(client.get("/api/v1/admin/versions", headers=admin_headers))
    dashboard = payload(client.get("/api/v1/admin/dashboard", headers=admin_headers))
    assert dashboard["graph"]["postingCount"] >= 20_000
    assert dashboard["graph"]["entityCounts"]["Certificate"] > 0
    assert len(dashboard["monthlyEvidence"]) >= 12
    assert dashboard["monthlyEvidence"] == sorted(dashboard["monthlyEvidence"], key=lambda item: item["period"])
    assert dashboard["locations"] and dashboard["locations"][0]["postingCount"] > 0
    assert {item["key"] for item in dashboard["governance"]["funnel"]} == {
        "candidates", "pending", "approved", "published", "withdrawn",
    }
    assert dashboard["quality"]["totalChecks"] > 0
    assert dashboard["system"]["neo4j"] and dashboard["system"]["mysql"]
    capabilities = payload(client.get("/api/v1/agent/capabilities"))
    assert capabilities["fallback"] == "rules"


def test_admin_version_lifecycle_and_quality_report_exports():
    headers = login_headers("admin")
    suffix = uuid4().hex[:12]
    role_id = f"role_test_{suffix}"
    version_id = f"version_test_{suffix}"
    definition = {
        "posting_count": 5,
        "source_count": 2,
        "evidence_record_count": 5,
        "core_responsibilities": ["验证岗位版本生命周期"],
        "required_skills": [{"skill_name": "Python"}],
        "bonus_skills": [{"skill_name": "数据分析"}],
        "application_scenarios": [{"scenario": "管理台验收"}],
    }
    draft_id = ""
    try:
        api.neo4j.query(
            "CREATE (r:JobRole {role_id:$role_id,role_name:$role_name}) "
            "CREATE (v:RoleDefinitionVersion {version_id:$version_id,status:'published',candidate_type:'new_role',definition_json:$definition,published_at:datetime()}) "
            "CREATE (r)-[:HAS_VERSION]->(v)",
            {
                "role_id": role_id,
                "role_name": "自动化测试岗位",
                "version_id": version_id,
                "definition": json.dumps(definition, ensure_ascii=False),
            },
        )

        first = payload(client.post(f"/api/v1/admin/versions/{version_id}/draft", headers=headers))
        second = payload(client.post(f"/api/v1/admin/versions/{version_id}/draft", headers=headers))
        draft_id = first["draftId"]
        assert first["created"] is True
        assert second["created"] is False and second["draftId"] == draft_id

        unpublished = payload(client.post(f"/api/v1/admin/versions/{version_id}/unpublish", headers=headers))
        assert unpublished["status"] == "withdrawn"
        republished = payload(client.post(f"/api/v1/admin/versions/{version_id}/publish", headers=headers))
        assert republished["status"] == "published"

        json_response = client.get("/api/v1/quality/report", params={"format": "json"}, headers=headers)
        assert json_response.status_code == 200
        assert json_response.json()["score"] >= 0
        csv_response = client.get("/api/v1/quality/report", params={"format": "csv"}, headers=headers)
        assert csv_response.status_code == 200
        assert "JD 字段精确准确率" in csv_response.content.decode("utf-8-sig")
        pdf_response = client.get("/api/v1/quality/report", params={"format": "pdf"}, headers=headers)
        assert pdf_response.status_code == 200 and pdf_response.content.startswith(b"%PDF")
    finally:
        api.neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id}) OPTIONAL MATCH (r)-[:HAS_VERSION]->(v:RoleDefinitionVersion) DETACH DELETE r,v",
            {"role_id": role_id},
        )
        with Session(engine) as db:
            if draft_id:
                db.execute(delete(RoleDefinitionDraft).where(RoleDefinitionDraft.id == draft_id))
            db.execute(delete(AuditLog).where(AuditLog.target_id.in_([version_id, draft_id])))
            db.commit()


def test_emerging_role_signal_tracks_publish_and_unpublish_status():
    headers = login_headers("admin")
    suffix = uuid4().hex[:12]
    role_id = f"role_signal_{suffix}"
    version_id = f"version_signal_{suffix}"
    definition = {
        "job_category": "测试岗位族",
        "first_seen": "2026-01",
        "latest_seen": "2026-07",
        "posting_count": 6,
        "source_count": 2,
        "evidence_record_count": 6,
        "candidate_reason": "recent_first_seen_multi_source_minimum_5_postings_plus_emerging_term",
        "core_responsibilities": ["验证新岗位发布状态同步"],
        "required_skills": [{"skill_name": "Python"}],
        "bonus_skills": [{"skill_name": "数据分析"}],
        "application_scenarios": ["自动化回归测试"],
        "publication_title": "新岗位发现",
    }
    evidence = [
        {"type": "job_posting", "recordId": f"record_{index}", "source": f"source_{index % 2}", "period": "2026-07"}
        for index in range(6)
    ]
    with Session(engine) as db:
        draft = RoleDefinitionDraft(
            role_id=role_id,
            role_name="状态同步测试岗位",
            candidate_type="new_role",
            status="approved",
            definition=definition,
            evidence=evidence,
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        draft_id = draft.id

    try:
        api.neo4j.query(
            "CREATE (r:JobRole {role_id:$role_id,role_name:$role_name}) "
            "CREATE (v:RoleDefinitionVersion {version_id:$version_id,status:'approved',definition_json:$definition,"
            "candidate_type:'new_role',display_title:'新岗位发现',draft_id:$draft_id,created_at:datetime()}) "
            "CREATE (r)-[:HAS_VERSION]->(v)",
            {"role_id": role_id, "role_name": "状态同步测试岗位", "version_id": version_id, "definition": json.dumps(definition, ensure_ascii=False), "draft_id": draft_id},
        )
        with Session(engine) as db:
            approved = next(item for item in services._forecast_emerging_roles(db, 3) if item["id"] == draft_id)
        assert approved["reviewStatus"] == "approved" and approved["canOpenJob"] is False

        published = payload(client.post(f"/api/v1/admin/versions/{version_id}/publish", headers=headers))
        assert published["status"] == "published"
        detail = payload(client.get(f"/api/v1/forecasts/emerging-roles/{draft_id}"))
        assert detail["reviewStatus"] == "published" and detail["canOpenJob"] is True
        assert len(detail["evidence"]) == 6 and detail["sourceCount"] == 2

        admin_detail = payload(client.get(f"/api/v1/admin/versions/{version_id}", headers=headers))
        assert admin_detail["draftId"] == draft_id and len(admin_detail["evidence"]) == 6

        api.neo4j.query(
            "MATCH (v:RoleDefinitionVersion {version_id:$version_id}) REMOVE v.draft_id",
            {"version_id": version_id},
        )
        legacy_detail = payload(client.get(f"/api/v1/admin/versions/{version_id}", headers=headers))
        assert legacy_detail["draftId"] == draft_id and len(legacy_detail["evidence"]) == 6

        withdrawn = payload(client.post(f"/api/v1/admin/versions/{version_id}/unpublish", headers=headers))
        assert withdrawn["status"] == "withdrawn"
        detail = payload(client.get(f"/api/v1/forecasts/emerging-roles/{draft_id}"))
        assert detail["reviewStatus"] == "withdrawn" and detail["canOpenJob"] is False
    finally:
        api.neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id}) OPTIONAL MATCH (r)-[:HAS_VERSION]->(v:RoleDefinitionVersion) DETACH DELETE r,v",
            {"role_id": role_id},
        )
        with Session(engine) as db:
            db.execute(delete(RoleDefinitionDraft).where(RoleDefinitionDraft.id == draft_id))
            db.execute(delete(AuditLog).where(AuditLog.target_id.in_([version_id, draft_id])))
            db.commit()


def test_agent_session_role_title_rename_persistence_and_delete():
    jobs = payload(client.get("/api/v1/jobs", params={"pageSize": 1}))
    role_id = jobs["items"][0]["id"]
    role_name = jobs["items"][0]["name"]
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "请解释这个岗位的趋势", "roleId": role_id, "roleName": role_name},
    )
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    session_id = next(item["sessionId"] for item in events if item.get("type") == "done")
    sessions = payload(client.get("/api/v1/agent/sessions"))
    assert any(
        item["id"] == session_id and item["title"] == role_name and item["messageCount"] >= 2
        for item in sessions["items"]
    )

    renamed_title = f"{role_name}成长规划"
    renamed = payload(client.patch(f"/api/v1/agent/sessions/{session_id}", json={"title": f"  {renamed_title}  "}))
    assert renamed["title"] == renamed_title
    detail = payload(client.get(f"/api/v1/agent/sessions/{session_id}"))
    assert detail["title"] == renamed_title
    assert len(detail["messages"]) >= 2

    follow_up = client.post(
        "/api/v1/agent/chat",
        json={"message": "再解释一下核心技能", "sessionId": session_id, "roleId": role_id, "roleName": role_name},
    )
    assert follow_up.status_code == 200
    persisted = payload(client.get(f"/api/v1/agent/sessions/{session_id}"))
    assert persisted["title"] == renamed_title
    assert len(persisted["messages"]) >= 4

    assert client.patch(f"/api/v1/agent/sessions/{session_id}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/v1/agent/sessions/{session_id}", json={"title": "名" * 61}).status_code == 422
    assert client.patch("/api/v1/agent/sessions/agent_missing", json={"title": "不存在"}).status_code == 404

    deleted = payload(client.delete(f"/api/v1/agent/sessions/{session_id}"))
    assert deleted["id"] == session_id
    assert client.get(f"/api/v1/agent/sessions/{session_id}").status_code == 404


def test_agent_session_without_role_name_uses_new_chat_title():
    response = client.post("/api/v1/agent/chat", json={"message": "你好"})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    session_id = next(item["sessionId"] for item in events if item.get("type") == "done")
    try:
        detail = payload(client.get(f"/api/v1/agent/sessions/{session_id}"))
        assert detail["title"] == "新对话"
    finally:
        client.delete(f"/api/v1/agent/sessions/{session_id}")


def test_agent_session_is_persisted_after_streaming_fallback():
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "请说明当前岗位趋势", "roleName": "数据工程师"},
    )
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    session_id = next(item["sessionId"] for item in events if item.get("type") == "done")
    try:
        sessions = payload(client.get("/api/v1/agent/sessions"))
        current = next(item for item in sessions["items"] if item["id"] == session_id)
        assert current["title"] == "数据工程师"
        assert current["messageCount"] >= 2
    finally:
        client.delete(f"/api/v1/agent/sessions/{session_id}")


def test_jd_recommendation_match_learning_and_exports():
    parsed = payload(
        client.post(
            "/api/v1/jd/parse",
            json={"text": "职位名称：数据工程师。岗位职责：负责数据处理。任职要求：本科，3 年经验，熟悉 Python、Spark、Hive。"},
        )
    )
    assert parsed["title"] == "数据工程师"
    assert {item["skill_name"] for item in parsed["skills"]} >= {"Python", "Spark", "Hive"}

    recommendations = payload(
        client.post("/api/v1/matching/recommendations", json={"skills": ["Python", "Spark", "Hive"], "limit": 5})
    )
    assert len(recommendations["items"]) == 5
    target = recommendations["items"][0]
    report_id = ""
    try:
        matched = payload(
            client.post(
                "/api/v1/matching/manual",
                json={
                    "targetRoleId": target["roleId"],
                    "skills": ["Python", "Spark", "Hive"],
                    "education": "本科",
                    "experienceYears": 3,
                    "certificates": [],
                    "workStyleScore": 64,
                },
            )
        )
        report_id = matched["reportId"]
        assert 0 <= matched["score"] <= 100
        assert matched["workStyleScore"] == 64
        learning = payload(client.post("/api/v1/learning-paths", params={"reportId": report_id}))
        assert learning["stages"]
        assert all(stage["planVersion"] == "learning-v3-linked-courses" for stage in learning["stages"])
        assert all(stage["weeklyTasks"] and stage["acceptanceCriteria"] for stage in learning["stages"])
        linked_courses = [course for stage in learning["stages"] for course in stage.get("courses", [])]
        assert all(isinstance(course, dict) and course.get("name") for course in linked_courses)
        assert all(not course.get("url") or str(course["url"]).startswith(("http://", "https://")) for course in linked_courses)
        report_payload = payload(client.get(f"/api/v1/reports/{report_id}"))
        assert report_payload["id"] == report_id
        assert "graphSummary" in report_payload and "evolutionSummary" in report_payload
        csv_response = client.get(f"/api/v1/reports/{report_id}", params={"format": "csv"})
        assert csv_response.status_code == 200 and "skill,status" in csv_response.text
        pdf_response = client.get(f"/api/v1/reports/{report_id}", params={"format": "pdf"})
        assert pdf_response.status_code == 200 and pdf_response.content.startswith(b"%PDF")
        assert "filename*=UTF-8''" in pdf_response.headers["content-disposition"]
        pdf = PdfReader(io.BytesIO(pdf_response.content))
        assert len(pdf.pages) >= 2
        assert pdf.metadata.title == f"{matched['roleName']}-个人能力诊断"
        pdf_text = "".join(page.extract_text() or "" for page in pdf.pages)
        assert "重要度" not in pdf_text and "bonus" not in pdf_text
        assert "岗位能力图谱" not in pdf_text and "岗位能力演化" not in pdf_text
        if any(course.get("url") for course in linked_courses):
            annotations = [annotation.get_object() for page in pdf.pages for annotation in (page.get("/Annots") or [])]
            uris = [annotation.get("/A", {}).get("/URI") for annotation in annotations if annotation.get("/A")]
            assert any(uri and str(uri).startswith(("http://", "https://")) for uri in uris)
    finally:
        if report_id:
            with Session(engine) as db:
                db.execute(delete(LearningPath).where(LearningPath.match_report_id == report_id))
                db.execute(delete(MatchReport).where(MatchReport.id == report_id))
                db.commit()
            (Path(APP_DATA_ROOT) / "reports" / f"{report_id}.pdf").unlink(missing_ok=True)


def test_direct_route_flow_for_framework_independent_coverage():
    report_id = ""
    with Session(engine) as db:
        try:
            assert api.health()["data"]["status"] == "healthy"
            assert api.agent_capabilities()["data"]["chatEndpoint"] == "/api/v1/agent/chat"
            assert api.get_overview(db)["data"]["postingCount"] >= 20_000
            jobs = api.get_jobs(keyword="", field="", page=1, pageSize=3)["data"]
            role_id = jobs["items"][0]["id"]
            detail = api.get_job(role_id)["data"]
            api.get_job_aliases(role_id)
            api.get_job_skills(role_id)
            api.get_job_postings(role_id)
            api.get_job_changes(role_id)
            graph = api.get_graph(
                keyword="", roleId=role_id, limit=30, viewMode="role", techStack="", skillTier="", seniority=""
            )["data"]
            assert api.get_graph_filters()["data"]["techStacks"]
            node_id = graph["nodes"][0]["id"]
            api.get_graph_node(node_id)
            api.get_graph_neighbors(node_id, limit=20)
            api.get_trends(role_id, "year")
            report = api.get_evolution_report(role_id, "pdf", 3, "baseline", "year", db)
            assert report.media_type == "application/pdf" and report.body.startswith(b"%PDF")
            api.get_evolution_compare(role_id, "2025", "2026", "year")
            api.get_evolution_candidates("pending", db)
            api.parse_job_description(
                api.JDParseRequest(text="职位名称：数据工程师。岗位职责：负责数据处理。任职要求：本科，3 年经验，熟悉 Python、Spark、Hive。")
            )
            recommendation = api.matching_recommendations(
                api.RecommendationRequest(skills=["Python", "Spark", "Hive"], limit=3)
            )["data"]["items"][0]
            matched = api.manual_match(
                api.MatchRequest(
                    targetRoleId=recommendation["roleId"],
                    skills=[item["name"] for item in detail["skills"][:3]],
                    education="本科",
                    experienceYears=3,
                ),
                db,
            )["data"]
            report_id = matched["reportId"]
            api.learning_path(report_id, db)
            assert api.get_report(report_id, "json", db)["data"]["id"] == report_id
            assert "skill,status" in api.get_report(report_id, "csv", db).body.decode("utf-8-sig")
            assert api.get_report(report_id, "pdf", db).body.startswith(b"%PDF")
            api.datasets(page=1, pageSize=5, db=db)
            api.reviews(status="pending", db=db)
            api.graph_versions()
            assert api.quality_summary(db)["data"]["evaluation"]["passed"] is True
        finally:
            if report_id:
                db.execute(delete(LearningPath).where(LearningPath.match_report_id == report_id))
                db.execute(delete(MatchReport).where(MatchReport.id == report_id))
                db.commit()
                (Path(APP_DATA_ROOT) / "reports" / f"{report_id}.pdf").unlink(missing_ok=True)
