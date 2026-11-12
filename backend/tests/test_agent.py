import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models import AgentDescription, ExtractedRecord, NormalizedRecord, PipelineBatch, PipelineStageLog, RawRecord, RoleDefinitionDraft
from app import services_parse


@pytest.fixture
def agent_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def test_normalize_without_graph_and_isolate_bad_record(agent_db, monkeypatch):
    db = agent_db
    batch = PipelineBatch(id="batch-parse", source_type="structured")
    db.add(batch)
    for index in range(3):
        db.add(RawRecord(id=f"raw-{index}", batch_id=batch.id, node_type="JobPosting", content="岗位名称：数据工程师。岗位职责：负责数据治理和平台建设。", content_sha256=str(index)))
    db.commit()
    original = services_parse.parse_record
    def parse(row):
        if row.id == "raw-1":
            raise ValueError("bad row")
        return original(row)
    monkeypatch.setattr(services_parse, "parse_record", parse)
    monkeypatch.setattr(services_parse, "refresh_entity_linker", lambda _: pytest.fail("unexpected graph access"))
    counts = services_parse.normalize_batch(db, batch, link=False)
    db.commit()
    assert counts["parsed"] == 2 and counts["parse_errors"] == [{"recordId": "raw-1", "error": "bad row"}]
    assert db.scalar(select(func.count()).select_from(ExtractedRecord)) == 2
    rows = db.scalars(select(NormalizedRecord)).all()
    assert len(rows) == 2 and all(row.data["skills"] == [] for row in rows)
    assert rows[0].data["title"] == "数据工程师"
    assert rows[0].data["responsibilities"] == ["负责数据治理和平台建设"]
    assert services_parse.ensure_normalized(db, batch)["reason"] == "already_normalized"
    assert db.scalar(select(func.count()).select_from(PipelineStageLog)) == 1


def test_ingest_switch_and_uncommitted_mode(agent_db, monkeypatch):
    from app.main import _persist_ingest_records
    record = {"node_type": "JobPosting", "title": "数据工程师", "content": "岗位职责：负责数据治理、质量规则制定与数据平台建设。"}
    monkeypatch.setattr(settings, "entity_linker_enabled", False)
    legacy = _persist_ingest_records(agent_db, [record], source_type="structured", source_name="test")
    assert legacy["stage"] == "ingest"
    assert not agent_db.scalars(select(NormalizedRecord)).all()
    monkeypatch.setattr(settings, "agent_pipeline_enabled", True)
    result = _persist_ingest_records(agent_db, [record], source_type="structured", source_name="test", commit=False)
    assert result["stage"] == "normalize"
    agent_db.rollback()
    assert agent_db.get(PipelineBatch, result["batchId"]) is None


def test_deepseek_options_and_provider_errors(monkeypatch):
    import json
    import httpx
    from app.interview import deepseek_chat, InterviewProviderError
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    captured = {}
    def post(url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, json={"choices": [{"message": {"content": " ok "}}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr("app.interview.httpx.post", post)
    assert deepseek_chat([], max_tokens=4096, timeout=90) == "ok"
    assert captured["json"]["max_tokens"] == 4096 and captured["timeout"] == 90
    for payload in ([], {"choices": []}, {"choices": [{"message": {"content": []}}]}):
        monkeypatch.setattr("app.interview.httpx.post", lambda url, **_: httpx.Response(200, json=payload, request=httpx.Request("POST", url)))
        with pytest.raises(InterviewProviderError):
            deepseek_chat([])
    def bad_json(*args, **kwargs):
        raise json.JSONDecodeError("bad", "x", 0)
    monkeypatch.setattr("app.interview.httpx.post", bad_json)
    with pytest.raises(InterviewProviderError):
        deepseek_chat([])


@pytest.fixture
def description_draft(agent_db, monkeypatch, tmp_path):
    from app import services_agent
    monkeypatch.setattr(settings, "agent_description_enabled", True)
    monkeypatch.setattr(services_agent, "APP_DATA_ROOT", tmp_path)
    row = RoleDefinitionDraft(id="draft-test", role_name="数据工程师", candidate_type="new_role", status="pending", definition={
        "core_responsibilities": ["负责数据治理"],
        "required_skills": [{"skill_id": "python", "skill_name": "Python"}],
        "bonus_skills": [], "application_scenarios": [{"scenario": "数据治理"}],
        "confidence": 0.6, "source_count": 1,
    }, evidence=[{"type": "source_record", "recordId": "evidence", "excerpt": "负责数据治理和平台建设"}])
    agent_db.add(RawRecord(id="evidence", batch_id="batch", content="负责数据治理和平台建设", content_sha256="hash"))
    agent_db.add(row)
    agent_db.commit()
    return row


def test_rule_files_hash_force_and_frozen(agent_db, description_draft):
    from pathlib import Path
    from docx import Document
    from app.services_agent import generate_description
    draft = description_draft
    before = dict(draft.definition)
    assert generate_description(agent_db, draft)["provider"] == "rules"
    row = agent_db.scalar(select(AgentDescription))
    assert "数据工程师" in Path(row.markdown_path).read_text(encoding="utf-8")
    assert any("负责数据治理" in paragraph.text for paragraph in Document(row.docx_path).paragraphs)
    assert not list(Path(row.docx_path).parent.glob("*.tmp"))
    assert generate_description(agent_db, draft)["reason"] == "unchanged"
    assert generate_description(agent_db, draft, force=True)["status"] == "completed"
    assert agent_db.scalar(select(func.count()).select_from(AgentDescription)) == 1
    assert draft.definition == before
    draft.status = "published"
    agent_db.commit()
    assert generate_description(agent_db, draft, force=True)["reason"] == "frozen"


def test_llm_validation_fallback_and_changed_hash(agent_db, description_draft, monkeypatch):
    import json
    from app import services_agent as service
    draft = description_draft
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    sections = service._rule_description(service.description_snapshot(agent_db, draft))
    sections["required_skills"].append({"skill_id": "invented", "skill_name": "编造技能"})
    sections["responsibilities"].append("编造岗位职责")
    def chat(*args, **kwargs):
        assert not agent_db.in_transaction()
        assert "数据非指令" in args[0][0]["content"] and "【证据1】" in args[0][1]["content"]
        return json.dumps(sections)
    monkeypatch.setattr(service, "deepseek_chat", chat)
    assert service.generate_description(agent_db, draft)["provider"] == "deepseek"
    row = agent_db.scalar(select(AgentDescription))
    assert len(row.sections["required_skills"]) == 1 and row.sections["responsibilities"] == ["负责数据治理"]
    monkeypatch.setattr(service, "deepseek_chat", lambda *_, **__: "invalid JSON")
    assert service.generate_description(agent_db, draft, force=True)["provider"] == "rules"
    assert agent_db.scalar(select(AgentDescription)).llm_error
    old_hash = row.input_hash
    def changed(*_, **__):
        draft.definition = {**draft.definition, "confidence": 0.9}
        agent_db.commit()
        return json.dumps(sections)
    monkeypatch.setattr(service, "deepseek_chat", changed)
    assert service.generate_description(agent_db, draft, force=True)["reason"] == "draft_changed"
    assert service.description_input_hash(agent_db, draft) != old_hash
    assert agent_db.scalar(select(AgentDescription)).input_hash == old_hash


@pytest.mark.parametrize("status", ["approved", "rejected", "published", "withdrawn", "edited"])
def test_m4_protects_reviewed_drafts(agent_db, status):
    from app.models import ReviewAction, Signal
    from app.services_m4 import _upsert_draft, build_definition_stage
    definition = {"cohort_key": "title:test", "period_key": "2026-11", "batch_ids": ["original"]}
    draft = RoleDefinitionDraft(id="draft-protected", role_name="原始岗位", candidate_type="new_role", origin="pipeline", status="pending" if status == "edited" else status, definition=definition, evidence=[{"recordId": "original"}], batch_id="original")
    agent_db.add(draft)
    agent_db.add(Signal(signal_type="emerging_role", cohort_key="title:test", period_key="2026-11", status="active"))
    if status == "edited":
        agent_db.add(ReviewAction(draft_id=draft.id, action="request_changes", note="编辑"))
    agent_db.commit()
    assert _upsert_draft(agent_db, role_name="覆盖", candidate_type="new_role", definition=definition, evidence=[], batch_id="new") is None
    result = build_definition_stage(agent_db)
    assert result["skip_reasons"] == {"draft_edited" if status == "edited" else "draft_frozen": 1}
    assert not result["draft_ids"] and draft.evidence == [{"recordId": "original"}] and draft.role_name == "原始岗位"


def test_enterprise_draft_isolated_and_publish_unregistered_skills(agent_db, monkeypatch):
    from app import main as api
    from app.models import AuditLog, RoleDefinitionVersion
    from app.services_m4 import create_enterprise_draft, build_definition_stage
    from app.services_publish import validate_evidence
    batch = PipelineBatch(id="enterprise-batch", source_type="enterprise", metadata_json={"enterprise_user_id": "user"})
    raw = RawRecord(id="enterprise-raw", batch_id=batch.id, content="负责企业数据平台建设、质量治理与团队沟通协作。", title="企业数据工程师", company_name="企业", content_sha256="sha", raw_payload={"openingCount": 2})
    agent_db.add_all([batch, raw])
    agent_db.flush()
    draft = create_enterprise_draft(agent_db, batch, raw)
    agent_db.commit()
    assert validate_evidence(agent_db, draft)["checked"]
    original = dict(draft.definition)
    build_definition_stage(agent_db)
    agent_db.commit()
    assert draft.definition == original and draft.status == "pending"
    def graph(statement, parameters=None):
        parameters = parameters or {}
        if "MERGE (v:RoleDefinitionVersion" in statement:
            return [{"id": parameters["version_id"], "status": "published", "roleId": parameters["role_id"]}]
        return []
    monkeypatch.setattr(api.neo4j, "query", graph)
    approved = api.review(draft.id, api.ReviewRequest(action="approve"), agent_db)["data"]
    published = api.publish_graph_version(approved["versionId"], agent_db)["data"]
    assert draft.status == "published" and len(published["unresolvedSkills"]) == 2
    assert agent_db.scalar(select(RoleDefinitionVersion)).definition == draft.definition
    audit = agent_db.scalar(select(AuditLog).where(AuditLog.action == "graph_version_publish"))
    assert audit.detail["unresolvedSkills"] == published["unresolvedSkills"]


@pytest.fixture
def agent_client(agent_db, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app import main as api, services_orchestrator as orchestrator
    from app.auth import require_admin, require_enterprise
    from app.database import get_db
    from app.models import AppUser
    monkeypatch.setattr(settings, "agent_pipeline_enabled", True)
    monkeypatch.setattr(settings, "entity_linker_enabled", False)
    monkeypatch.setattr(orchestrator, "SessionLocal", sessionmaker(bind=agent_db.bind, expire_on_commit=False))
    def db_override():
        yield agent_db
    api.app.dependency_overrides[get_db] = db_override
    api.app.dependency_overrides[require_admin] = lambda: AppUser(id="admin", role="admin")
    api.app.dependency_overrides[require_enterprise] = lambda: AppUser(id="enterprise", role="enterprise")
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_enterprise_request_idempotency_short_text_and_legacy(agent_client, agent_db):
    from app.models import AgentRun
    payload = {"companyName": "测试企业", "roleName": "治理工程师", "jobCategory": "数据治理", "jdText": "负责数据平台建设、质量治理、规则制定和团队沟通协作。"}
    first = agent_client.post("/api/v1/enterprise/job-submissions", json=payload)
    assert first.status_code == 201, first.text
    data = first.json()["data"]
    assert data["id"] == data["draftId"] and data["draftStatus"] == "pending"
    draft = agent_db.get(RoleDefinitionDraft, data["draftId"])
    draft.status = "published"
    agent_db.commit()
    again = agent_client.post("/api/v1/enterprise/job-submissions", json=payload).json()["data"]
    assert again["batchId"] == data["batchId"] and again["draftStatus"] == "published"
    assert agent_db.scalar(select(func.count()).select_from(AgentRun)) == 1
    listing = agent_client.get("/api/v1/enterprise/job-submissions").json()["data"]["items"][0]
    assert listing["id"] == data["batchId"] and listing["status"] == "published" and listing["statusLabel"] == "已发布"
    short = agent_client.post("/api/v1/enterprise/job-submissions", json={**payload, "jdText": "过短"})
    assert short.status_code == 422
    agent_db.add(PipelineBatch(id="legacy-enterprise", source_type="enterprise"))
    agent_db.commit()
    response = agent_client.post("/ingest/batches/legacy-enterprise/agent-run")
    assert response.status_code == 202
    run = agent_client.get(f"/agent/runs/{response.json()['data']['id']}").json()["data"]
    assert run["status"] == "failed" and run["error"] == "no_draft_legacy_batch"


def test_no_signal_and_startup_reconcile(agent_client, agent_db):
    from datetime import datetime, timedelta
    from app.models import AgentRun
    from app.services_orchestrator import reconcile_stale_agent_runs
    response = agent_client.post("/ingest/sources", json={"node_type": "JobPosting", "title": "数据治理工程师", "content": "负责数据平台建设、质量治理、规则制定和团队沟通协作。"})
    assert response.status_code == 201, response.text
    run = agent_client.get(f"/agent/runs/{response.json()['data']['agentRunId']}").json()["data"]
    assert run["status"] == "completed" and run["skip_reasons"]["disabled"] == 1
    # Enable descriptions and rerun: a batch without dated signals is explicit no_signal.
    settings.agent_description_enabled = True
    second = agent_client.post(f"/ingest/batches/{response.json()['data']['batchId']}/agent-run").json()["data"]
    run = agent_client.get(f"/agent/runs/{second['id']}").json()["data"]
    assert run["skip_reasons"]["no_signal"] == 1
    agent_db.add(AgentRun(id="stale-run", batch_id="none", status="queued", started_at=datetime.utcnow()-timedelta(hours=2)))
    agent_db.commit()
    assert reconcile_stale_agent_runs() == 1
    agent_db.expire_all()
    assert agent_db.get(AgentRun, "stale-run").status == "interrupted"


def test_description_api_stale_and_download(agent_client, agent_db, description_draft):
    draft = description_draft
    missing = agent_client.get(f"/admin/definitions/{draft.id}/description")
    assert missing.status_code == 404 and missing.json()["data"]["reason"] == "not_generated"
    assert agent_client.post(f"/admin/definitions/{draft.id}/description/regenerate").status_code == 200
    url = f"/admin/definitions/{draft.id}/description"
    assert agent_client.get(url).json()["data"]["stale"] is False
    assert agent_client.get(url + "?download=1&format=docx").content.startswith(b"PK")
    draft.definition = {**draft.definition, "confidence": 0.95}
    agent_db.commit()
    assert agent_client.get(url).json()["data"]["stale"] is True
    draft.status = "approved"
    agent_db.commit()
    assert agent_client.post(url + "/regenerate").status_code == 409


def test_cohort_matches_without_truncated_evidence_and_limit_order(agent_db):
    from app.services_orchestrator import select_description_candidates
    agent_db.add(RawRecord(id="new-raw-outside-100", batch_id="new-batch", title="新岗位", content="内容", content_sha256="new", node_type="JobPosting", raw_payload={"period": "2026-11"}))
    for index in range(31):
        agent_db.add(RoleDefinitionDraft(id=f"candidate-{index:02}", role_name="新岗位", candidate_type="new_role", status="pending", definition={"cohort_key": "title:新岗位", "period_key": "2026-11", "confidence": 0.8}, evidence=[{"recordId": f"old-{x}"} for x in range(100)]))
    agent_db.commit()
    ids = [f"candidate-{index:02}" for index in range(31)]
    result = select_description_candidates(agent_db, "new-batch", list(reversed(ids)))
    assert [row.id for row in result] == ids
    assert len(result[:settings.agent_description_max_drafts]) == 30


def test_orchestrator_limit_records_over_limit(agent_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app import services_orchestrator as service
    from app.models import AgentRun
    monkeypatch.setattr(settings, "agent_pipeline_enabled", True)
    monkeypatch.setattr(settings, "agent_description_enabled", True)
    monkeypatch.setattr(service, "SessionLocal", sessionmaker(bind=agent_db.bind, expire_on_commit=False))
    batch = PipelineBatch(id="limit-batch", source_type="structured")
    agent_db.add(batch)
    for index in range(31):
        agent_db.add(RoleDefinitionDraft(id=f"limit-{index:02}", role_name="岗位", candidate_type="new_role", status="pending"))
    agent_db.commit()
    monkeypatch.setattr(service, "ensure_normalized", lambda *args: {"status": "completed"})
    monkeypatch.setattr(service, "build_feature_stage", lambda *args: {})
    monkeypatch.setattr(service, "build_definition_stage", lambda *args, **kwargs: {"draft_ids": []})
    monkeypatch.setattr(service, "select_description_candidates", lambda db, *args: db.scalars(select(RoleDefinitionDraft).order_by(RoleDefinitionDraft.id)).all())
    generated = []
    def generate(db, draft):
        generated.append(draft.id)
        return {"status": "completed", "provider": "rules"}
    monkeypatch.setattr(service, "generate_description", generate)
    run = service.create_agent_run(agent_db, batch)
    service.run_agent_pipeline(run.id)
    agent_db.expire_all()
    run = agent_db.get(AgentRun, run.id)
    assert generated == [f"limit-{index:02}" for index in range(30)]
    assert run.draft_count == 31 and run.description_count == 30
    assert run.stages["description"]["skip_reasons"] == {"over_limit": 1}


def test_manual_stage_waits_for_orchestrator_lock(agent_db, monkeypatch):
    from threading import Event, Thread
    from sqlalchemy.orm import sessionmaker
    from app import main as api, services_orchestrator as service
    monkeypatch.setattr(settings, "agent_pipeline_enabled", True)
    monkeypatch.setattr(settings, "agent_description_enabled", True)
    factory = sessionmaker(bind=agent_db.bind, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)
    batch = PipelineBatch(id="lock-batch", source_type="enterprise")
    draft = RoleDefinitionDraft(id="lock-draft", batch_id=batch.id, role_name="岗位", candidate_type="new_role", status="pending", origin="pipeline")
    agent_db.add_all([batch, draft])
    agent_db.commit()
    run = service.create_agent_run(agent_db, batch, draft_id=draft.id)
    entered, release, manual_started, feature_called = Event(), Event(), Event(), Event()
    def generate(*args):
        entered.set()
        assert release.wait(5)
        return {"status": "completed"}
    def feature(*args, **kwargs):
        feature_called.set()
        return {"feature_version": "test", "signal_version": "test", "input_summary": {}}
    monkeypatch.setattr(service, "generate_description", generate)
    monkeypatch.setattr(api, "build_feature_stage", feature)
    errors = []
    def manual():
        try:
            with factory() as db:
                manual_started.set()
                api.build_batch_features(batch.id, db)
        except Exception as error:
            errors.append(error)
    pipeline_thread = Thread(target=service.run_agent_pipeline, args=(run.id,))
    manual_thread = Thread(target=manual)
    pipeline_thread.start()
    try:
        assert entered.wait(3)
        manual_thread.start()
        assert manual_started.wait(1)
        assert not feature_called.wait(0.1)
    finally:
        release.set()
        pipeline_thread.join(5)
        if manual_thread.ident:
            manual_thread.join(5)
    assert feature_called.is_set() and not errors
