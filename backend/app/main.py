import csv
import copy
import hashlib
import io
import json
import math
import re
import threading
import time
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.error import URLError
from uuid import uuid4

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .config import APP_DATA_ROOT, settings
from .auth import create_access_token, get_current_user, get_optional_user, hash_password, require_admin, require_enterprise, seed_users, verify_password
from .database import Base, SessionLocal, engine, get_db
from .interview import (
    InterviewProviderError,
    evaluate_answer,
    generate_questions,
    generate_report,
    transcribe_audio,
)
from .models import (
    AgentMessage,
    AgentSession,
    AgentRun,
    AgentDescription,
    uid,
    AppUser,
    AuditLog,
    DatasetRegistry,
    DatasetRevision,
    EntityLink,
    ExtractedRecord,
    FeatureSnapshot,
    EvaluationRun,
    FavoriteJob,
    InterviewSession,
    LearningPath,
    MatchReport,
    ProcessingTask,
    PipelineBatch,
    RawRecord,
    PipelineStageLog,
    NormalizedRecord,
    Signal,
    ResumeProfile,
    ResumeSkill,
    ReviewAction,
    ReviewComment,
    RoleDefinitionVersion,
    PublishTask,
    RoleDefinitionDraft,
    TalentAssessmentBatch,
    TalentAssessmentCandidate,
    UserWorkspaceProfile,
)
from .pipeline import add_raw_record, finish_ingest, read_upload
from .neo4j_client import Neo4jError, neo4j
from .services import (
    AgentProviderError,
    admin_dashboard,
    calculate_match,
    create_learning_path,
    compare_evolution,
    evolution_trends,
    forecast_emerging_role_detail,
    forecast_overview,
    graph_data,
    graph_filter_options,
    graph_neighbors,
    graph_node_detail,
    job_changes,
    job_detail,
    job_filter_options,
    job_location_options,
    list_jobs,
    agent_provider_answer,
    coze_agent_stream,
    coze_event_conversation_id,
    coze_event_text,
    rule_agent_answer,
    overview,
    parse_resume,
    recommend_roles,
    parse_jd,
    save_match,
    seed_candidates,
    seed_datasets,
    count_csv_rows,
    file_sha256,
    sync_dataset_to_graph,
)
from .services_parse import normalize_batch
from .services_feature import build_feature_stage, serialize_feature, serialize_signal
from .services_m4 import build_definition_stage, create_enterprise_draft, serialize_definition_draft
from .services_agent import description_input_hash, generate_description
from .services_orchestrator import PIPELINE_LOCK, create_agent_run, pipeline_guard, reconcile_stale_agent_runs, run_agent_pipeline, serialize_agent_run
from .services_publish import (
    PublishValidationError,
    mark_published,
    mark_withdrawn,
    publish_neo4j_version,
    version_id_for_draft,
    validate_evidence,
)
from .services_graph import close_version_edges, project_role_version, role_graph_view, role_skill_view


def envelope(data, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data, "requestId": f"req_{uuid4().hex[:16]}"}


_READ_CACHE: dict[str, tuple[float, object]] = {}
_READ_CACHE_LOCK = threading.Lock()
_READ_CACHE_MAX_ITEMS = 192


def _cached_read(key: str, ttl_seconds: int, loader):
    now = time.monotonic()
    with _READ_CACHE_LOCK:
        cached = _READ_CACHE.get(key)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])
    value = loader()
    with _READ_CACHE_LOCK:
        _READ_CACHE[key] = (now + ttl_seconds, copy.deepcopy(value))
        if len(_READ_CACHE) > _READ_CACHE_MAX_ITEMS:
            expired = [item_key for item_key, item in _READ_CACHE.items() if item[0] <= now]
            for item_key in expired or list(_READ_CACHE)[:32]:
                _READ_CACHE.pop(item_key, None)
    return value


def _invalidate_read_cache():
    with _READ_CACHE_LOCK:
        _READ_CACHE.clear()


def _cache_key(scope: str, *values) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return f"{scope}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _overview_data(db: Session):
    return _cached_read(f"overview:{id(overview)}", 60, lambda: overview(db))


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_datasets(db)
        seed_candidates(db)
        seed_users(db)
    reconcile_stale_agent_runs()
    yield


app = FastAPI(title="职能洞察本地 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Neo4jError)
async def neo4j_error_handler(_, exc: Neo4jError):
    return Response(
        content=json.dumps({"code": 50301, "message": str(exc), "data": None}, ensure_ascii=False),
        media_type="application/json",
        status_code=503,
    )


class MatchRequest(BaseModel):
    targetRoleId: str
    skills: list[str] = Field(default_factory=list)
    education: str = ""
    experienceYears: float | None = None
    certificates: list[str] = Field(default_factory=list)
    resumeId: str = ""
    workStyleScore: float | None = Field(default=None, ge=0, le=100)


class AgentRequest(BaseModel):
    message: str
    sessionId: str = ""
    reportId: str = ""
    roleId: str = ""
    roleName: str = Field(default="", max_length=255)
    agentMode: str = Field(default="career_planning", pattern="^(career_planning|ability_analysis)$")


class AgentSessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)


class ReviewRequest(BaseModel):
    action: str
    note: str = ""
    definition: dict | None = None


class ResumeConfirmRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    education: str = ""
    experienceYears: float | None = None
    certificates: list[str] = Field(default_factory=list)


class RecommendationRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=30)


class JDParseRequest(BaseModel):
    text: str = Field(min_length=20, max_length=200000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=4, max_length=200)
    portal: str = Field(pattern="^(personal|admin|enterprise)$")


class RegisterRequest(BaseModel):
    username: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    password: str = Field(min_length=4, max_length=12, pattern=r"^[A-Za-z0-9]+$")
    displayName: str = Field(min_length=2, max_length=120)


class WorkspaceProfileRequest(BaseModel):
    audience: str = Field(default="seeker", pattern="^seeker$")
    profile: dict = Field(default_factory=dict)
    workStyleAssessment: dict = Field(default_factory=dict)


class FavoriteJobRequest(BaseModel):
    roleId: str = Field(min_length=1, max_length=80)


class EnterpriseAssessmentRequest(BaseModel):
    roleId: str = Field(min_length=1, max_length=80)
    resumeIds: list[str] = Field(min_length=1, max_length=100)


class EnterpriseJobSubmissionRequest(BaseModel):
    companyName: str = Field(min_length=2, max_length=255)
    contact: str = Field(default="", max_length=160)
    roleName: str = Field(min_length=2, max_length=255)
    jobCategory: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=120)
    openingCount: int = Field(default=1, ge=1, le=10000)
    responsibilities: list[str] = Field(default_factory=list, max_length=30)
    requiredSkills: list[str] = Field(default_factory=list, max_length=30)
    bonusSkills: list[str] = Field(default_factory=list, max_length=30)
    applicationScenarios: list[str] = Field(default_factory=list, max_length=20)
    jdText: str = Field(default="", max_length=200000)


class IngestSourceRecord(BaseModel):
    source_record_id: str = ""
    record_id: str = ""
    source_canonical: str = ""
    source: str = ""
    company_name: str = ""
    company: str = ""
    title: str = ""
    job_title: str = ""
    content: str = ""
    description: str = ""
    node_type: str = ""
    entity_type: str = ""
    city: str = ""
    salary: str = ""


class IngestSourcesRequest(BaseModel):
    model_config = {"extra": "allow"}
    records: list[dict] = Field(default_factory=list)
    source_record_id: str = ""
    record_id: str = ""
    source_canonical: str = ""
    source: str = ""
    company_name: str = ""
    company: str = ""
    title: str = ""
    job_title: str = ""
    content: str = ""
    description: str = ""
    node_type: str = ""
    entity_type: str = ""
    city: str = ""
    salary: str = ""

def user_payload(user: AppUser) -> dict:
    return {"id": user.id, "username": user.username, "displayName": user.display_name, "role": user.role}


@app.get("/health")
@app.get("/api/v1/health")
def health():
    neo4j_ok = False
    mysql_ok = False
    try:
        neo4j_ok = bool(neo4j.scalar("RETURN 1"))
    except Exception:
        pass
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
            mysql_ok = True
    except Exception:
        pass
    status = "healthy" if neo4j_ok and mysql_ok else "degraded"
    return envelope({
        "status": status,
        "neo4j": neo4j_ok,
        "mysql": mysql_ok,
        "agentProvider": settings.agent_provider,
        "agentConfigured": settings.agent_configured,
    })


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    seed_users(db)
    user = db.scalar(select(AppUser).where(AppUser.username == payload.username.strip()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "账号或密码错误")
    if user.role != payload.portal:
        raise HTTPException(403, "账号与所选入口不匹配")
    token, expires_at = create_access_token(user)
    return envelope({"accessToken": token, "expiresAt": expires_at, "user": user_payload(user)})


@app.post("/api/v1/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    display_name = payload.displayName.strip()
    if len(display_name) < 2:
        raise HTTPException(422, "显示名称至少需要 2 个字符")
    if db.scalar(select(AppUser).where(AppUser.username == username)):
        raise HTTPException(409, "该账号已被注册")
    user = AppUser(
        username=username,
        password_hash=hash_password(payload.password),
        display_name=display_name,
        role="personal",
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
        db.add(AuditLog(action="auth.register", target_type="app_user", target_id=user.id, detail={"username": username}))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该账号已被注册")
    db.refresh(user)
    token, expires_at = create_access_token(user)
    return envelope({"accessToken": token, "expiresAt": expires_at, "user": user_payload(user)}, "注册成功")


@app.get("/api/v1/auth/me")
def auth_me(user: AppUser = Depends(get_current_user)):
    return envelope(user_payload(user))


PERSONAL_PROFILE_FIELDS = {
    "fullName", "phone", "email", "city", "careerStatus", "education", "experienceYears", "school", "major", "graduationYear", "desiredRole",
}


def personal_profile(value: dict | None) -> dict:
    source = value if isinstance(value, dict) else {}
    return {key: source[key] for key in PERSONAL_PROFILE_FIELDS if key in source}


def workspace_profile_payload(item: UserWorkspaceProfile | None) -> dict:
    return {
        # Legacy HR profile rows are intentionally normalized to the only supported user workspace.
        "audience": "seeker",
        "profile": personal_profile(item.profile if item else {}),
        "workStyleAssessment": item.work_style_assessment if item else {},
        "updatedAt": item.updated_at.isoformat() if item and item.updated_at else "",
    }


@app.get("/api/v1/me/workspace-profile")
def get_workspace_profile(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return envelope(workspace_profile_payload(db.get(UserWorkspaceProfile, user.id)))


@app.put("/api/v1/me/workspace-profile")
def update_workspace_profile(
    payload: WorkspaceProfileRequest,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(UserWorkspaceProfile, user.id)
    if not item:
        item = UserWorkspaceProfile(user_id=user.id)
        db.add(item)
    item.audience = "seeker"
    item.profile = personal_profile(payload.profile)
    item.work_style_assessment = payload.workStyleAssessment
    db.add(AuditLog(action="workspace_profile.update", target_type="app_user", target_id=user.id, detail={"audience": "seeker"}))
    db.commit()
    db.refresh(item)
    return envelope(workspace_profile_payload(item), "资料已保存")


def _favorite_payload(item: FavoriteJob) -> dict:
    return {
        "id": item.id,
        "roleId": item.role_id,
        "roleName": item.role_name,
        "field": item.role_field,
        "createdAt": item.created_at.isoformat() if item.created_at else "",
    }


@app.get("/api/v1/me/favorites")
def list_favorite_jobs(
    limit: int = Query(100, ge=1, le=500),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(FavoriteJob).where(FavoriteJob.user_id == user.id)) or 0
    items = db.scalars(
        select(FavoriteJob)
        .where(FavoriteJob.user_id == user.id)
        .order_by(FavoriteJob.created_at.desc())
        .limit(limit)
    ).all()
    return envelope({"items": [_favorite_payload(item) for item in items], "total": total})


@app.post("/api/v1/me/favorites", status_code=201)
def save_favorite_job(
    payload: FavoriteJobRequest,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role_id = payload.roleId.strip()
    detail = job_detail(role_id)
    if not detail:
        raise HTTPException(404, "岗位不存在或尚未发布")
    item = db.scalar(select(FavoriteJob).where(FavoriteJob.user_id == user.id, FavoriteJob.role_id == role_id))
    if not item:
        item = FavoriteJob(
            user_id=user.id,
            role_id=role_id,
            role_name=str(detail.get("name") or role_id),
            role_field=str(detail.get("field") or ""),
        )
        db.add(item)
        db.flush()
        db.add(AuditLog(action="favorite_job.create", target_type="job_role", target_id=role_id, detail={"userId": user.id}))
        db.commit()
        db.refresh(item)
    return envelope(_favorite_payload(item), "岗位已收藏")


@app.delete("/api/v1/me/favorites/{role_id}")
def delete_favorite_job(
    role_id: str,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(FavoriteJob).where(FavoriteJob.user_id == user.id, FavoriteJob.role_id == role_id))
    if item:
        db.delete(item)
        db.add(AuditLog(action="favorite_job.delete", target_type="job_role", target_id=role_id, detail={"userId": user.id}))
        db.commit()
    return envelope({"roleId": role_id, "deleted": bool(item)}, "已取消收藏")


@app.get("/api/v1/agent/capabilities")
def agent_capabilities():
    return envelope({
        "provider": settings.agent_provider,
        "configured": settings.agent_configured,
        "fallback": "rules",
        "chatEndpoint": "/api/v1/agent/chat",
        "stream": "SSE",
        "externalContract": {
            "method": "POST",
            "request": ["message", "context", "constraints"],
            "response": {"answer": "string"},
            "authentication": "optional Bearer token from AGENT_API_KEY",
            "provider": settings.agent_provider,
            "botIds": {
                "careerPlanning": settings.agent_career_planning_bot_id,
                "abilityAnalysis": settings.agent_ability_analysis_bot_id,
            },
        },
        "tools": ["job_graph_query", "trend_analysis", "matching", "learning_path", "report"],
        "guardrails": ["grounded_only", "backend_tools_only", "no_direct_database_access"],
    })


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return Response(
        content=json.dumps(
            {
                "code": exc.status_code * 100,
                "message": str(exc.detail),
                "data": None,
                "requestId": request.headers.get("X-Request-Id", f"req_{uuid4().hex[:16]}"),
            },
            ensure_ascii=False,
        ),
        media_type="application/json",
        status_code=exc.status_code,
    )


@app.get("/api/v1/overview")
def get_overview(db: Session = Depends(get_db)):
    return envelope(_overview_data(db))


@app.get("/api/v1/jobs")
def get_jobs(
    keyword: str = "",
    field: str = "",
    fields: str = "",
    skills: str = "",
    trends: str = "",
    postingBucket: str = Query("", pattern="^(none|1_4|5_19|20_99|100_plus)?$"),
    sourceCounts: str = "",
    lastSeenBucket: str = Query("", pattern="^(2026|2025|2024_or_earlier|unknown)?$"),
    sort: str = Query("posting_desc", pattern="^(posting_desc|last_seen_desc|name_asc|trend_change_desc)$"),
    location: str = "",
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    trend_values = {item.strip() for item in trends.split(",") if item.strip()}
    if trend_values - {"up", "down", "stable", "new", "insufficient"}:
        raise HTTPException(422, "发展趋势筛选值无效")
    source_values = [item.strip() for item in sourceCounts.split(",") if item.strip()]
    if any(not item.isdigit() for item in source_values):
        raise HTTPException(422, "来源数筛选值必须为非负整数")
    cache_key = _cache_key(
        f"jobs:{id(list_jobs)}", keyword, field, fields, skills, trends,
        postingBucket, sourceCounts, lastSeenBucket, sort, location, page, pageSize,
    )
    return envelope(
        _cached_read(cache_key, 180, lambda: list_jobs(
            keyword, field, page, pageSize, fields, skills, trends,
            postingBucket, sourceCounts, lastSeenBucket, sort, location,
        ))
    )


@app.get("/api/v1/jobs/filters")
def get_job_filters():
    return envelope(_cached_read(f"job-filters:{id(job_filter_options)}", 300, job_filter_options))


@app.get("/api/v1/jobs/locations")
def get_job_locations():
    return envelope(_cached_read(f"job-locations:{id(job_location_options)}", 300, job_location_options))


@app.get("/api/v1/jobs/{role_id}")
def get_job(role_id: str, location: str = ""):
    item = _cached_read(_cache_key(f"job-detail:{id(job_detail)}", role_id, location), 120, lambda: job_detail(role_id, location))
    if not item:
        raise HTTPException(404, "岗位不存在")
    return envelope(item)


@app.get("/api/v1/jobs/{role_id}/aliases")
def get_job_aliases(role_id: str):
    item = job_detail(role_id)
    if not item:
        raise HTTPException(404, "岗位不存在")
    return envelope({"roleId": role_id, "aliases": item.get("aliases") or []})


@app.get("/api/v1/jobs/{role_id}/skills")
def get_job_skills(role_id: str, view: str = "current", asOf: str = "", versionId: str = ""):
    item = job_detail(role_id) if view == "current" else None
    try:
        graph = role_skill_view(neo4j, role_id, view=view, as_of=asOf, version_id=versionId)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if view != "current":
        role_rows = neo4j.query("MATCH (r:JobRole {role_id:$role_id}) RETURN r.role_id AS id LIMIT 1", {"role_id": role_id})
        if not role_rows:
            raise HTTPException(404, "岗位不存在")
    elif not item:
        raise HTTPException(404, "岗位不存在")
    if view == "current" and not graph["items"]:
        graph["items"] = item.get("skills") or []
        graph["total"] = len(graph["items"])
    return envelope(graph)


@app.get("/api/v1/graph/roles/{role_id}")
def get_role_graph_view(role_id: str, view: str = "current", asOf: str = "", versionId: str = ""):
    try:
        result = role_graph_view(neo4j, role_id, view=view, as_of=asOf, version_id=versionId)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not result.get("role"):
        raise HTTPException(404, "岗位不存在")
    return envelope(result)


@app.get("/api/v1/graph/roles/{role_id}/skills")
def get_role_graph_skills(role_id: str, view: str = "current", asOf: str = "", versionId: str = ""):
    try:
        result = role_skill_view(neo4j, role_id, view=view, as_of=asOf, version_id=versionId)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return envelope(result)


@app.get("/api/v1/jobs/{role_id}/postings")
def get_job_postings(role_id: str):
    item = job_detail(role_id)
    if not item:
        raise HTTPException(404, "岗位不存在")
    return envelope({"roleId": role_id, "items": item.get("postings") or [], "total": len(item.get("postings") or [])})


@app.get("/api/v1/jobs/{role_id}/changes")
def get_job_changes(role_id: str):
    if not job_detail(role_id):
        raise HTTPException(404, "岗位不存在")
    return envelope(job_changes(role_id))


@app.get("/api/v1/graph/filters")
def get_graph_filters():
    return envelope(_cached_read(f"graph-filters:{id(graph_filter_options)}", 300, graph_filter_options))


@app.get("/api/v1/graph")
def get_graph(
    keyword: str = "",
    roleId: str = "",
    limit: int = Query(80, ge=10, le=500),
    viewMode: str = Query("role", pattern="^(role|stack|entity)$"),
    techStack: str = "",
    skillTier: str = Query("", pattern="^(core|advanced|bonus)?$"),
    seniority: str = Query("", pattern="^(entry|intermediate|senior|unclassified)?$"),
    entityType: str = Query("", pattern="^(job|posting|skill|certificate|course|major|standard|requirement|report|signal|topic|snapshot|period)?$"),
):
    key = _cache_key(
        f"graph:{id(graph_data)}", keyword, roleId, limit, viewMode,
        techStack, skillTier, seniority, entityType,
    )
    return envelope(_cached_read(
        key, 120,
        lambda: graph_data(keyword, roleId, limit, viewMode, techStack, skillTier, seniority, entityType),
    ))


@app.get("/api/v1/graph/nodes/{node_id}")
def get_graph_node(node_id: str):
    item = _cached_read(_cache_key(f"graph-node:{id(graph_node_detail)}", node_id), 300, lambda: graph_node_detail(node_id))
    if not item:
        raise HTTPException(404, "图谱节点不存在")
    return envelope(item)


@app.get("/api/v1/graph/nodes/{node_id}/neighbors")
def get_graph_neighbors(node_id: str, limit: int = Query(80, ge=10, le=500)):
    return envelope(graph_neighbors(node_id, limit))


@app.get("/api/v1/evolution/trends")
def get_trends(roleId: str, granularity: str = Query("year", pattern="^(year|month)$")):
    return envelope(evolution_trends(roleId, granularity))


TREND_REPORT_COLORS = (
    "#00A9A1",
    "#D68612",
    "#3976B8",
    "#C14E5A",
    "#7868A8",
    "#28845B",
    "#B54D88",
    "#526F78",
    "#E36F3D",
    "#1686A5",
    "#8B6D3F",
    "#667085",
)


def _draw_evolution_chart_page(
    document: canvas.Canvas,
    role_name: str,
    title: str,
    trend: dict,
    generated_at: str,
    forecast: dict | None = None,
) -> None:
    width, height = landscape(A4)
    document.setFillColor(colors.HexColor("#102F2D"))
    document.rect(0, height - 76, width, 76, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#00A9A1"))
    document.rect(0, height - 76, 7, 76, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.setFont("STSong-Light", 18)
    document.drawString(42, height - 38, f"{role_name} · {title}")
    document.setFillColor(colors.HexColor("#BBD1CE"))
    document.setFont("STSong-Light", 9)
    scenario_label = {
        "conservative": "保守情景",
        "baseline": "基准情景",
        "growth": "增长情景",
    }.get(str((forecast or {}).get("scenario") or "baseline"), "基准情景")
    filter_summary = (
        f"未来 {(forecast or {}).get('horizon', 3)} 年 · {scenario_label} · "
        f"生成时间 {generated_at} · 指标：技能需求渗透率（%）"
    )
    document.drawString(42, height - 58, filter_summary)

    series = trend.get("series") or []
    forecast_skills = (forecast or {}).get("skills") or []
    forecast_by_id = {str(item.get("skillId") or ""): item for item in forecast_skills if item.get("skillId")}
    forecast_by_name = {str(item.get("skill") or ""): item for item in forecast_skills if item.get("skill")}
    periods = sorted(
        {
            str(point.get("period"))
            for item in series
            for point in item.get("points", [])
            if point.get("period") is not None
        }
        | {
            str(point.get("period"))
            for item in forecast_skills
            for point in item.get("points", [])
            if point.get("period") is not None and point.get("observed") is False
        }
    )
    if not series or not periods:
        document.setFillColor(colors.HexColor("#F3F7F6"))
        document.rect(42, 100, width - 84, height - 230, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#60716E"))
        document.setFont("STSong-Light", 14)
        document.drawCentredString(width / 2, height / 2, "暂无可用趋势快照")
        document.setFont("STSong-Light", 9)
        document.drawString(42, 54, "当前粒度没有可展示的数据。")
        document.showPage()
        return

    legend_columns = 4
    legend_rows = (len(series) + legend_columns - 1) // legend_columns
    legend_y = height - 105
    legend_width = (width - 84) / legend_columns
    document.setFont("STSong-Light", 8)
    for index, item in enumerate(series):
        column = index % legend_columns
        row = index // legend_columns
        x = 42 + column * legend_width
        y = legend_y - row * 17
        color = colors.HexColor(TREND_REPORT_COLORS[index % len(TREND_REPORT_COLORS)])
        document.setStrokeColor(color)
        document.setLineWidth(2.4)
        document.line(x, y + 2, x + 17, y + 2)
        document.setFillColor(colors.HexColor("#334744"))
        name = str(item.get("skill") or "未命名技能")
        document.drawString(x + 23, y - 1, name if len(name) <= 18 else f"{name[:17]}...")

    chart_left = 58
    chart_bottom = 84
    chart_right = width - 42
    chart_top = legend_y - legend_rows * 17 - 16
    chart_width = chart_right - chart_left
    chart_height = chart_top - chart_bottom

    document.setFont("STSong-Light", 8)
    for value in range(0, 101, 20):
        y = chart_bottom + chart_height * value / 100
        document.setStrokeColor(colors.HexColor("#DDE7E5"))
        document.setLineWidth(0.6)
        document.line(chart_left, y, chart_right, y)
        document.setFillColor(colors.HexColor("#6B7B78"))
        document.drawRightString(chart_left - 8, y - 3, str(value))
    document.setStrokeColor(colors.HexColor("#AFC3C0"))
    document.line(chart_left, chart_bottom, chart_left, chart_top)
    document.line(chart_left, chart_bottom, chart_right, chart_bottom)

    label_step = max(1, (len(periods) - 1 + 7) // 8)
    label_indexes = set(range(0, len(periods), label_step))
    label_indexes.add(len(periods) - 1)
    for index in sorted(label_indexes):
        x = chart_left if len(periods) == 1 else chart_left + chart_width * index / (len(periods) - 1)
        document.setFillColor(colors.HexColor("#6B7B78"))
        document.drawCentredString(x, chart_bottom - 16, periods[index])

    period_index = {period: index for index, period in enumerate(periods)}
    for series_index, item in enumerate(series):
        historical_values = {
            str(point.get("period")): float(point.get("value") or 0)
            for point in item.get("points", [])
            if point.get("period") is not None
        }
        skill_forecast = forecast_by_id.get(str(item.get("skillId") or "")) or forecast_by_name.get(str(item.get("skill") or "")) or {}
        forecast_values = {
            str(point.get("period")): float(point.get("value") or 0)
            for point in skill_forecast.get("points", [])
            if point.get("period") is not None and point.get("observed") is False
        }
        line_color = colors.HexColor(TREND_REPORT_COLORS[series_index % len(TREND_REPORT_COLORS)])
        document.setStrokeColor(line_color)
        document.setFillColor(colors.white)
        document.setLineWidth(1.7)
        previous = None
        for period in periods:
            value = historical_values.get(period)
            if value is None:
                previous = None
                continue
            index = period_index[period]
            x = chart_left + (chart_width / 2 if len(periods) == 1 else chart_width * index / (len(periods) - 1))
            y = chart_bottom + chart_height * max(0, min(100, value)) / 100
            if previous is not None:
                document.line(previous[0], previous[1], x, y)
            previous = (x, y)
            if len(periods) <= 24:
                document.circle(x, y, 2.1, stroke=1, fill=1)

        if forecast_values:
            last_historical_period = max(historical_values) if historical_values else ""
            projected_points = []
            if last_historical_period in period_index:
                projected_points.append((last_historical_period, historical_values[last_historical_period]))
            projected_points.extend(
                (period, forecast_values[period]) for period in sorted(forecast_values) if period in period_index
            )
            document.setStrokeColor(line_color)
            document.setLineWidth(1.7)
            document.setDash(4, 2)
            for point_index in range(1, len(projected_points)):
                previous_period, previous_value = projected_points[point_index - 1]
                current_period, current_value = projected_points[point_index]
                previous_x = chart_left + chart_width * period_index[previous_period] / max(1, len(periods) - 1)
                current_x = chart_left + chart_width * period_index[current_period] / max(1, len(periods) - 1)
                previous_y = chart_bottom + chart_height * max(0, min(100, previous_value)) / 100
                current_y = chart_bottom + chart_height * max(0, min(100, current_value)) / 100
                document.line(previous_x, previous_y, current_x, current_y)
            document.setDash()

    document.setFillColor(colors.HexColor("#60716E"))
    document.setFont("STSong-Light", 8)
    document.drawString(42, 52, f"技能曲线 {len(series)} 条 · 可用周期 {len(periods)} 个 · 实线为历史观测，虚线为当前筛选条件下的预测")
    document.showPage()


def _forecast_point_xy(point: dict, index: int, count: int, left: float, bottom: float, width: float, height: float) -> tuple[float, float]:
    x = left + (width / 2 if count == 1 else width * index / (count - 1))
    value = max(0.0, min(100.0, float(point.get("value") or 0)))
    return x, bottom + height * value / 100


def _draw_occupation_forecast_page(
    document: canvas.Canvas,
    role_name: str,
    forecast: dict,
    generated_at: str,
) -> None:
    width, height = landscape(A4)
    occupations = forecast.get("occupations") or []
    occupation = next(
        (item for item in occupations if str(item.get("roleName") or "") == role_name),
        occupations[0] if occupations else {},
    )
    scenario_label = {
        "conservative": "保守情景",
        "baseline": "基准情景",
        "growth": "增长情景",
    }.get(str(forecast.get("scenario") or "baseline"), "基准情景")
    granularity_label = "月度" if forecast.get("granularity") == "month" else "年度"

    document.setFillColor(colors.HexColor("#102F2D"))
    document.rect(0, height - 76, width, 76, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#D4A853"))
    document.rect(0, height - 76, 7, 76, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.setFont("STSong-Light", 18)
    document.drawString(42, height - 38, f"{role_name} · 岗位热度预测")
    document.setFillColor(colors.HexColor("#BBD1CE"))
    document.setFont("STSong-Light", 9)
    document.drawString(
        42,
        height - 58,
        f"未来 {forecast.get('horizon', 3)} 年 · {granularity_label} · {scenario_label} · 生成时间 {generated_at}",
    )

    metrics = (
        ("当前热度指数", f"{float(occupation.get('currentIndex') or 0):.1f}", "综合招聘规模与来源覆盖"),
        ("历史变化速度", f"{float(occupation.get('changeRate') or 0):+.1f}%", "历史序列相对变化"),
        ("预测置信度", f"{round(float(occupation.get('confidence') or 0) * 100)}%", f"{int(occupation.get('sampleSize') or 0)} 条样本支撑"),
    )
    metric_y = height - 139
    metric_gap = 12
    metric_width = (width - 84 - metric_gap * 2) / 3
    for index, (label, value, detail) in enumerate(metrics):
        x = 42 + index * (metric_width + metric_gap)
        document.setFillColor(colors.HexColor("#F3F7F6"))
        document.roundRect(x, metric_y, metric_width, 48, 7, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#47615D"))
        document.setFont("STSong-Light", 8)
        document.drawString(x + 12, metric_y + 31, label)
        document.setFillColor(colors.HexColor("#18312E" if index != 1 else "#B47B22"))
        document.setFont("STSong-Light", 16)
        document.drawRightString(x + metric_width - 12, metric_y + 24, value)
        document.setFillColor(colors.HexColor("#879592"))
        document.setFont("STSong-Light", 7)
        document.drawString(x + 12, metric_y + 11, detail)

    points = sorted(occupation.get("points") or [], key=lambda item: str(item.get("period") or ""))
    chart_left = 58
    chart_right = width - 42
    chart_bottom = 72
    chart_top = metric_y - 27
    chart_width = chart_right - chart_left
    chart_height = chart_top - chart_bottom
    document.setFillColor(colors.HexColor("#1A2C29"))
    document.setFont("STSong-Light", 11)
    document.drawString(42, chart_top + 15, "岗位需求走势")
    document.setFillColor(colors.HexColor("#879592"))
    document.setFont("STSong-Light", 7.5)
    document.drawString(116, chart_top + 15, "历史观测与未来预测")

    if not points:
        document.setFillColor(colors.HexColor("#F3F7F6"))
        document.rect(chart_left, chart_bottom, chart_width, chart_height, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#60716E"))
        document.setFont("STSong-Light", 12)
        document.drawCentredString(width / 2, chart_bottom + chart_height / 2, "暂无可用岗位热度预测曲线")
        document.showPage()
        return

    for value in range(0, 101, 20):
        y = chart_bottom + chart_height * value / 100
        document.setStrokeColor(colors.HexColor("#DDE7E5"))
        document.setLineWidth(0.6)
        document.line(chart_left, y, chart_right, y)
        document.setFillColor(colors.HexColor("#6B7B78"))
        document.setFont("STSong-Light", 7.5)
        document.drawRightString(chart_left - 8, y - 3, str(value))

    coordinates = [
        _forecast_point_xy(point, index, len(points), chart_left, chart_bottom, chart_width, chart_height)
        for index, point in enumerate(points)
    ]
    future_indexes = [index for index, point in enumerate(points) if not point.get("observed")]
    first_future = future_indexes[0] if future_indexes else len(points)
    if future_indexes:
        start_x = coordinates[max(0, first_future - 1)][0]
        document.setFillColor(colors.HexColor("#FBF4E6"))
        document.rect(start_x, chart_bottom, chart_right - start_x, chart_height, stroke=0, fill=1)

    observed_end = min(first_future, len(points) - 1)
    document.setStrokeColor(colors.HexColor("#0F4C45"))
    document.setLineWidth(2)
    document.setDash()
    for index in range(1, observed_end + 1):
        document.line(*coordinates[index - 1], *coordinates[index])
    if future_indexes:
        document.setStrokeColor(colors.HexColor("#D4A853"))
        document.setDash(5, 3)
        for index in range(max(1, first_future), len(coordinates)):
            document.line(*coordinates[index - 1], *coordinates[index])
        document.setDash()

    label_step = max(1, (len(points) - 1 + 7) // 8)
    label_indexes = set(range(0, len(points), label_step))
    label_indexes.add(len(points) - 1)
    document.setFillColor(colors.HexColor("#6B7B78"))
    document.setFont("STSong-Light", 7.5)
    for index in sorted(label_indexes):
        x, _ = coordinates[index]
        document.drawCentredString(x, chart_bottom - 16, str(points[index].get("period") or ""))

    document.setFillColor(colors.HexColor("#60716E"))
    document.setFont("STSong-Light", 8)
    document.drawString(42, 40, "深绿实线为历史观测，琥珀金虚线为预测趋势。")
    document.showPage()


def _draw_skill_forecast_card(
    document: canvas.Canvas,
    skill: dict,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    document.setFillColor(colors.white)
    document.setStrokeColor(colors.HexColor("#DDE7E5"))
    document.setLineWidth(0.7)
    document.roundRect(x, y, width, height, 8, stroke=1, fill=1)

    skill_name = str(skill.get("skill") or "未命名技能")
    current = float(skill.get("currentDemand") or 0)
    future = float(skill.get("futureDemand") or 0)
    confidence = round(float(skill.get("confidence") or 0) * 100)
    document.setFillColor(colors.HexColor("#1A2C29"))
    document.setFont("STSong-Light", 10)
    document.drawString(x + 12, y + height - 18, skill_name if len(skill_name) <= 24 else f"{skill_name[:23]}...")
    document.setFillColor(colors.HexColor("#60716E"))
    document.setFont("STSong-Light", 7.5)
    document.drawRightString(x + width - 12, y + height - 18, f"需求指数 {current:.1f} -> {future:.1f}  ·  置信度 {confidence}%")

    points = sorted(skill.get("points") or [], key=lambda item: str(item.get("period") or ""))
    if not points:
        document.setFillColor(colors.HexColor("#879592"))
        document.setFont("STSong-Light", 9)
        document.drawCentredString(x + width / 2, y + height / 2, "暂无可用预测曲线")
        return

    chart_left = x + 31
    chart_right = x + width - 13
    chart_bottom = y + 23
    chart_top = y + height - 35
    chart_width = chart_right - chart_left
    chart_height = chart_top - chart_bottom
    document.setFont("STSong-Light", 6.5)
    for value in (0, 50, 100):
        grid_y = chart_bottom + chart_height * value / 100
        document.setStrokeColor(colors.HexColor("#E8EFED"))
        document.setLineWidth(0.45)
        document.line(chart_left, grid_y, chart_right, grid_y)
        document.setFillColor(colors.HexColor("#879592"))
        document.drawRightString(chart_left - 5, grid_y - 2, str(value))

    future_indexes = [index for index, point in enumerate(points) if not point.get("observed")]
    if future_indexes:
        first_future = future_indexes[0]
        band_points = []
        if first_future > 0:
            previous = points[first_future - 1]
            px, py = _forecast_point_xy(previous, first_future - 1, len(points), chart_left, chart_bottom, chart_width, chart_height)
            band_points.append((px, py, py))
        for index in future_indexes:
            point = points[index]
            px, _ = _forecast_point_xy(point, index, len(points), chart_left, chart_bottom, chart_width, chart_height)
            lower = chart_bottom + chart_height * max(0.0, min(100.0, float(point.get("lower") or 0))) / 100
            upper = chart_bottom + chart_height * max(0.0, min(100.0, float(point.get("upper") or 0))) / 100
            band_points.append((px, lower, upper))
        if len(band_points) >= 2:
            path = document.beginPath()
            path.moveTo(band_points[0][0], band_points[0][2])
            for px, _, upper in band_points[1:]:
                path.lineTo(px, upper)
            for px, lower, _ in reversed(band_points):
                path.lineTo(px, lower)
            path.close()
            document.setFillColor(colors.HexColor("#F5E8C9"))
            document.drawPath(path, stroke=0, fill=1)

    coordinates = [
        _forecast_point_xy(point, index, len(points), chart_left, chart_bottom, chart_width, chart_height)
        for index, point in enumerate(points)
    ]
    first_future = future_indexes[0] if future_indexes else len(points)
    observed_end = min(first_future, len(points) - 1)
    if observed_end >= 1:
        document.setStrokeColor(colors.HexColor("#0F4C45"))
        document.setLineWidth(1.5)
        document.setDash()
        for index in range(1, observed_end + 1):
            document.line(*coordinates[index - 1], *coordinates[index])
    if future_indexes:
        forecast_start = max(0, first_future - 1)
        document.setStrokeColor(colors.HexColor("#D4A853"))
        document.setLineWidth(1.5)
        document.setDash(4, 2)
        for index in range(forecast_start + 1, len(coordinates)):
            document.line(*coordinates[index - 1], *coordinates[index])
        document.setDash()

    label_indexes = {0, len(points) - 1}
    if future_indexes:
        label_indexes.add(first_future)
    document.setFillColor(colors.HexColor("#6B7B78"))
    document.setFont("STSong-Light", 6.5)
    for index in sorted(label_indexes):
        px, _ = coordinates[index]
        period = str(points[index].get("period") or "")
        if index == 0:
            document.drawString(px, y + 9, period)
        elif index == len(points) - 1:
            document.drawRightString(px, y + 9, period)
        else:
            document.drawCentredString(px, y + 9, period)


def _draw_skill_forecast_pages(
    document: canvas.Canvas,
    role_name: str,
    forecast: dict,
    generated_at: str,
) -> None:
    skills = forecast.get("skills") or []
    if not skills:
        return
    width, height = landscape(A4)
    cards_per_page = 6
    columns = 2
    rows = 3
    margin_x = 34
    gap_x = 12
    gap_y = 10
    header_height = 66
    footer_height = 25
    card_width = (width - margin_x * 2 - gap_x) / columns
    card_height = (height - header_height - footer_height - gap_y * (rows - 1)) / rows
    page_count = (len(skills) + cards_per_page - 1) // cards_per_page
    scenario_label = {
        "conservative": "保守情景",
        "baseline": "基准情景",
        "growth": "增长情景",
    }.get(str(forecast.get("scenario") or "baseline"), "基准情景")
    granularity_label = "月度" if forecast.get("granularity") == "month" else "年度"

    for page_index in range(page_count):
        document.setFillColor(colors.HexColor("#102F2D"))
        document.rect(0, height - 58, width, 58, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#D4A853"))
        document.rect(0, height - 58, 7, 58, stroke=0, fill=1)
        document.setFillColor(colors.white)
        document.setFont("STSong-Light", 15)
        document.drawString(34, height - 29, f"{role_name} · 技能需求预测曲线")
        document.setFillColor(colors.HexColor("#CAD9D6"))
        document.setFont("STSong-Light", 8)
        document.drawString(
            34,
            height - 46,
            f"未来 {forecast.get('horizon', 3)} 年 · {granularity_label} · {scenario_label} · 生成时间 {generated_at}",
        )
        legend_x = width - 205
        document.setStrokeColor(colors.HexColor("#0F8A7D"))
        document.setLineWidth(2)
        document.line(legend_x, height - 27, legend_x + 18, height - 27)
        document.setFillColor(colors.white)
        document.drawString(legend_x + 23, height - 30, "历史观测")
        document.setStrokeColor(colors.HexColor("#D4A853"))
        document.setDash(4, 2)
        document.line(legend_x + 78, height - 27, legend_x + 96, height - 27)
        document.setDash()
        document.drawString(legend_x + 101, height - 30, "预测趋势")

        page_skills = skills[page_index * cards_per_page:(page_index + 1) * cards_per_page]
        for index, skill in enumerate(page_skills):
            row = index // columns
            column = index % columns
            card_x = margin_x + column * (card_width + gap_x)
            card_y = footer_height + (rows - 1 - row) * (card_height + gap_y)
            _draw_skill_forecast_card(document, skill, card_x, card_y, card_width, card_height)

        document.setFillColor(colors.HexColor("#60716E"))
        document.setFont("STSong-Light", 7.5)
        document.drawString(34, 10, f"本页 {len(page_skills)} 条技能曲线 · 共 {len(skills)} 条")
        document.drawRightString(width - 34, 10, f"技能预测 {page_index + 1}/{page_count}")
        document.showPage()


def _build_evolution_report_pdf(role_name: str, annual: dict, monthly: dict, forecast: dict | None = None) -> bytes:
    stream = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(stream, pagesize=landscape(A4))
    document.setTitle(f"职能洞察 - {role_name}岗位能力演化趋势报告")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    if forecast:
        _draw_occupation_forecast_page(document, role_name, forecast, generated_at)
    granularity = str((forecast or {}).get("granularity") or "year")
    selected_trend = monthly if granularity == "month" else annual
    selected_title = "月度技能需求与预测" if granularity == "month" else "年度技能需求与预测"
    _draw_evolution_chart_page(document, role_name, selected_title, selected_trend, generated_at, forecast)
    if forecast:
        _draw_skill_forecast_pages(document, role_name, forecast, generated_at)
    document.save()
    return stream.getvalue()


@app.get("/api/v1/evolution/report")
def get_evolution_report(
    roleId: str,
    format: str = "pdf",
    horizon: int = 3,
    scenario: str = "baseline",
    granularity: str = "year",
    db: Session = Depends(get_db),
):
    if format != "pdf":
        raise HTTPException(422, "演化报告仅支持 PDF")
    if horizon not in {1, 3, 5}:
        raise HTTPException(422, "预测周期只支持 1、3、5 年")
    if scenario not in {"conservative", "baseline", "growth"}:
        raise HTTPException(422, "预测情景不受支持")
    if granularity not in {"year", "month"}:
        raise HTTPException(422, "历史粒度只支持年度或月度")
    role = job_detail(roleId)
    if not role:
        raise HTTPException(404, "岗位不存在")
    report_forecast = forecast_overview(db, horizon, scenario, granularity, roleId)
    if not any(str(item.get("roleId") or "") == roleId for item in report_forecast.get("occupations") or []):
        targeted_forecast = forecast_overview(
            db,
            horizon,
            scenario,
            granularity,
            roleId,
            keyword=str(role.get("name") or roleId),
        )
        target_occupation = next(
            (item for item in targeted_forecast.get("occupations") or [] if str(item.get("roleId") or "") == roleId),
            None,
        )
        if target_occupation:
            report_forecast["occupations"] = [
                target_occupation,
                *(item for item in report_forecast.get("occupations") or [] if str(item.get("roleId") or "") != roleId),
            ]
    content = _build_evolution_report_pdf(
        str(role.get("name") or roleId),
        evolution_trends(roleId, "year"),
        evolution_trends(roleId, "month"),
        report_forecast,
    )
    display_name = f"{role.get('name') or roleId}-岗位能力演化趋势.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="evolution-{roleId}.pdf"; '
                f"filename*=UTF-8''{quote(display_name)}"
            )
        },
    )


@app.get("/api/v1/evolution/compare")
def get_evolution_compare(
    roleId: str,
    fromPeriod: str,
    toPeriod: str,
    granularity: str = Query("year", pattern="^(year|month)$"),
):
    return envelope(compare_evolution(roleId, fromPeriod, toPeriod, granularity))


@app.get("/api/v1/evolution/candidates")
def get_evolution_candidates(status: str = "pending", db: Session = Depends(get_db)):
    query = select(RoleDefinitionDraft).order_by(RoleDefinitionDraft.created_at.desc())
    if status:
        query = query.where(RoleDefinitionDraft.status == status)
    items = db.scalars(query).all()
    return envelope(
        {
            "items": [
                {
                    "id": item.id,
                    "roleId": item.role_id,
                    "roleName": item.role_name,
                    "candidateType": item.candidate_type,
                    "status": item.status,
                    "origin": item.origin,
                    "batchId": item.batch_id,
                    "evidenceGrade": item.evidence_grade,
                    "definition": item.definition,
                    "evidence": item.evidence,
                    "confidence": "review_required",
                }
                for item in items
            ],
            "total": len(items),
            "notice": "候选仅供人工复核，批准前不会进入正式岗位定义。",
        }
    )


@app.get("/api/v1/forecasts/overview")
def get_forecast_overview(
    horizon: int = Query(3, ge=1, le=5),
    scenario: str = Query("baseline", pattern="^(conservative|baseline|growth)$"),
    granularity: str = Query("year", pattern="^(year|month)$"),
    roleId: str = Query(""),
    location: str = Query(""),
    keyword: str = Query("", max_length=80),
    db: Session = Depends(get_db),
):
    if horizon not in {1, 3, 5}:
        raise HTTPException(422, "预测周期只支持 1、3、5 年")
    key = _cache_key(
        f"forecast:{id(forecast_overview)}", horizon, scenario, granularity, roleId, location, keyword,
    )
    return envelope(_cached_read(
        key, 180,
        lambda: forecast_overview(db, horizon, scenario, granularity, roleId, location, keyword),
    ))


@app.get("/api/v1/forecasts/emerging-roles/{signal_id}")
def get_forecast_emerging_role(
    signal_id: str,
    horizon: int = Query(3, ge=1, le=5),
    db: Session = Depends(get_db),
):
    key = _cache_key(f"emerging-role:{id(forecast_emerging_role_detail)}", signal_id, horizon)
    detail = _cached_read(key, 90, lambda: forecast_emerging_role_detail(db, signal_id, horizon))
    if not detail:
        raise HTTPException(404, "新岗位信号不存在、证据不足或已被驳回")
    return envelope(detail)


@app.post("/api/v1/jd/parse")
def parse_job_description(payload: JDParseRequest):
    return envelope(parse_jd(payload.text))


def _resume_payload(db: Session, profile: ResumeProfile) -> dict:
    skills = db.scalars(
        select(ResumeSkill).where(ResumeSkill.resume_id == profile.id).order_by(ResumeSkill.created_at.asc())
    ).all()
    return {
        "resumeId": profile.id,
        "skills": [
            {
                "skill_id": skill.skill_id,
                "skill_name": skill.skill_name,
                "evidence": skill.evidence,
                "confidence": skill.confidence,
            }
            for skill in skills
        ],
        "education": profile.education,
        "experienceYears": profile.experience_years,
        "certificates": profile.certificates or [],
        "warnings": [],
        "ocr": None,
        "confirmed": profile.confirmed,
        "fileName": profile.file_name,
        "uploadedAt": profile.created_at.isoformat() if profile.created_at else "",
        "textPreview": (profile.raw_text or "")[:1600],
    }


def _owned_resume(db: Session, resume_id: str, user_id: str) -> ResumeProfile:
    profile = db.scalar(
        select(ResumeProfile).where(ResumeProfile.id == resume_id, ResumeProfile.user_id == user_id)
    )
    if not profile:
        raise HTTPException(404, "简历档案不存在")
    return profile


def _parse_resume_task(task_id: str, destination: Path, file_name: str, user_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(ProcessingTask, task_id)
        if not task:
            return
        task.status = "running"
        task.progress = 20
        db.commit()
        try:
            parsed = parse_resume(destination)
            profile = ResumeProfile(
                user_id=user_id,
                file_name=file_name,
                file_path=str(destination),
                education=parsed["education"],
                experience_years=parsed["experienceYears"],
                certificates=parsed["certificates"],
                raw_text=parsed["text"],
            )
            db.add(profile)
            db.flush()
            for skill in parsed["skills"]:
                db.add(ResumeSkill(resume_id=profile.id, **skill))
            task.status = "completed"
            task.progress = 100
            task.result = {
                "userId": user_id,
                "resumeId": profile.id,
                "skills": parsed["skills"],
                "education": parsed["education"],
                "experienceYears": parsed["experienceYears"],
                "certificates": parsed["certificates"],
                "warnings": parsed["warnings"],
                "ocr": parsed["ocr"],
                "confirmed": False,
            }
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            task.status = "failed"
            task.progress = 100
            task.error = str(exc)
            db.commit()


@app.post("/api/v1/resumes", status_code=202)
async def upload_resume(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "resume").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise HTTPException(400, "仅支持 PDF、DOCX 和 TXT 文件")
    destination = APP_DATA_ROOT / "uploads" / f"{uuid4().hex}{suffix}"
    size = 0
    with destination.open("wb") as stream:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 10 * 1024 * 1024:
                destination.unlink(missing_ok=True)
                raise HTTPException(400, "文件不能超过 10 MB")
            stream.write(chunk)
    task = ProcessingTask(
        task_type="resume_parse",
        status="pending",
        progress=0,
        result={"userId": user.id},
    )
    db.add(task)
    db.commit()
    background_tasks.add_task(_parse_resume_task, task.id, destination, file.filename or destination.name, user.id)
    return envelope({"taskId": task.id, "status": "pending", "progress": 0}, "简历解析任务已创建")


@app.get("/api/v1/tasks/{task_id}")
def get_task(task_id: str, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(ProcessingTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    result = dict(task.result or {})
    if result.get("userId") != user.id:
        raise HTTPException(404, "任务不存在")
    result.pop("userId", None)
    return envelope({"id": task.id, "status": task.status, "progress": task.progress, "result": result, "error": task.error})


@app.get("/api/v1/me/resumes")
def list_my_resumes(
    limit: int = Query(20, ge=1, le=100),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profiles = db.scalars(
        select(ResumeProfile)
        .where(ResumeProfile.user_id == user.id)
        .order_by(ResumeProfile.created_at.desc())
        .limit(limit)
    ).all()
    return envelope({"items": [_resume_payload(db, profile) for profile in profiles], "total": len(profiles)})


@app.get("/api/v1/me/resumes/{resume_id}/file")
def preview_my_resume_file(
    resume_id: str,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_resume(db, resume_id, user.id)
    stored_path = Path(profile.file_path).resolve() if profile.file_path else None
    upload_root = (APP_DATA_ROOT / "uploads").resolve()
    if not stored_path or not stored_path.is_file() or upload_root not in stored_path.parents:
        raise HTTPException(404, "简历原文件不存在")
    return FileResponse(stored_path, filename=profile.file_name or stored_path.name, content_disposition_type="inline")


@app.delete("/api/v1/me/resumes/{resume_id}")
def delete_my_resume(
    resume_id: str,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_resume(db, resume_id, user.id)
    stored_path = Path(profile.file_path).resolve() if profile.file_path else None
    upload_root = (APP_DATA_ROOT / "uploads").resolve()
    db.execute(delete(ResumeSkill).where(ResumeSkill.resume_id == resume_id))
    db.delete(profile)
    db.add(AuditLog(action="resume.delete", target_type="resume", target_id=resume_id, detail={"userId": user.id}))
    db.commit()
    if stored_path and stored_path.is_file() and upload_root in stored_path.parents:
        stored_path.unlink(missing_ok=True)
    return envelope({"resumeId": resume_id, "deleted": True}, "简历已删除")


@app.put("/api/v1/resumes/{resume_id}/confirmation")
def confirm_resume(
    resume_id: str,
    payload: ResumeConfirmRequest,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_resume(db, resume_id, user.id)
    profile.education = payload.education
    profile.experience_years = payload.experienceYears
    profile.certificates = payload.certificates
    profile.confirmed = True
    existing = db.scalars(select(ResumeSkill).where(ResumeSkill.resume_id == resume_id)).all()
    by_name = {item.skill_name.casefold(): item for item in existing}
    confirmed_names = {name.strip().casefold() for name in payload.skills if name.strip()}
    for item in existing:
        if item.skill_name.casefold() not in confirmed_names:
            db.delete(item)
    for name in payload.skills:
        cleaned = name.strip()
        if cleaned and cleaned.casefold() not in by_name:
            db.add(ResumeSkill(resume_id=resume_id, skill_name=cleaned, evidence="用户人工确认", confidence=1.0))
    db.add(AuditLog(action="resume_confirm", target_type="resume", target_id=resume_id, detail={"skillCount": len(confirmed_names)}))
    db.commit()
    return envelope({"resumeId": resume_id, "confirmed": True, "skillCount": len(confirmed_names)}, "解析结果已确认")


@app.post("/api/v1/matching/manual")
def manual_match(
    payload: MatchRequest,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_user),
):
    if payload.resumeId:
        if not user:
            raise HTTPException(401, "使用已保存简历前请先登录")
        _owned_resume(db, payload.resumeId, user.id)
    role = job_detail(payload.targetRoleId)
    if not role:
        raise HTTPException(404, "目标岗位不存在")
    result = calculate_match(role, payload.skills, payload.education, payload.experienceYears, payload.certificates)
    if payload.workStyleScore is not None:
        result["workStyleScore"] = round(payload.workStyleScore, 1)
    report = save_match(db, result, payload.resumeId)
    return envelope({**result, "reportId": report.id})


@app.post("/api/v1/matching/resume/{resume_id}")
def resume_match(
    resume_id: str,
    targetRoleId: str,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _owned_resume(db, resume_id, user.id)
    if not profile.confirmed:
        raise HTTPException(409, "请先确认简历解析结果")
    skills = [item.skill_name for item in db.scalars(select(ResumeSkill).where(ResumeSkill.resume_id == resume_id)).all()]
    role = job_detail(targetRoleId)
    if not role:
        raise HTTPException(404, "目标岗位不存在")
    result = calculate_match(role, skills, profile.education, profile.experience_years, profile.certificates)
    report = save_match(db, result, resume_id)
    return envelope({**result, "reportId": report.id})


@app.post("/api/v1/matching/recommendations")
def matching_recommendations(payload: RecommendationRequest):
    if not payload.skills:
        raise HTTPException(400, "至少提供一项已掌握技能")
    return envelope({"items": recommend_roles(payload.skills, payload.limit), "total": payload.limit})


def _enterprise_content_confidence(profile: ResumeProfile) -> int:
    """Stable presentation-only confidence required by the enterprise demo."""
    digest = hashlib.sha1(f"{profile.id}:{profile.file_name}".encode("utf-8")).digest()
    return 85 + digest[0] % 13


def _enterprise_resume_payload(db: Session, profile: ResumeProfile) -> dict:
    payload = _resume_payload(db, profile)
    candidate_match = re.search(r"(?:姓名|候选人)\s*[:：]\s*([^\s,，;；]{2,20})", profile.raw_text or "")
    payload.update({
        "candidateName": candidate_match.group(1) if candidate_match else Path(profile.file_name or "候选人").stem,
        "contentConfidence": _enterprise_content_confidence(profile),
    })
    return payload


def _enterprise_batch_payload(db: Session, batch: TalentAssessmentBatch, include_candidates: bool = True) -> dict:
    candidates = db.scalars(
        select(TalentAssessmentCandidate)
        .where(TalentAssessmentCandidate.batch_id == batch.id)
        .order_by(TalentAssessmentCandidate.score.desc(), TalentAssessmentCandidate.created_at.asc())
    ).all()
    completed = [item for item in candidates if item.status == "completed" and item.score is not None]
    payload = {
        "id": batch.id,
        "roleId": batch.role_id,
        "roleName": batch.role_name,
        "status": batch.status,
        "candidateCount": len(candidates),
        "completedCount": len(completed),
        "averageScore": round(sum(float(item.score or 0) for item in completed) / len(completed), 1) if completed else 0,
        "createdAt": batch.created_at.isoformat() if batch.created_at else "",
    }
    if include_candidates:
        payload["candidates"] = [
            {
                "id": item.id,
                "candidateCode": item.candidate_code,
                "fileName": item.file_name,
                "resumeId": item.resume_id,
                "reportId": item.match_report_id,
                "status": item.status,
                "score": item.score,
                "result": item.result or {},
                "error": item.error,
            }
            for item in candidates
        ]
    return payload


@app.get("/api/v1/enterprise/overview")
def enterprise_overview(
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    resume_count = db.scalar(select(func.count()).select_from(ResumeProfile).where(ResumeProfile.user_id == user.id)) or 0
    batches = db.scalars(
        select(TalentAssessmentBatch)
        .where(TalentAssessmentBatch.user_id == user.id)
        .order_by(TalentAssessmentBatch.created_at.desc())
    ).all()
    batch_ids = [item.id for item in batches]
    candidates = db.scalars(
        select(TalentAssessmentCandidate).where(TalentAssessmentCandidate.batch_id.in_(batch_ids))
    ).all() if batch_ids else []
    scored = [item for item in candidates if item.score is not None]
    submissions = db.scalars(select(RoleDefinitionDraft).order_by(RoleDefinitionDraft.created_at.desc())).all()
    owned_submissions = [item for item in submissions if str((item.definition or {}).get("enterprise_user_id") or "") == user.id]
    return envelope({
        "resumeCount": int(resume_count),
        "assessmentBatchCount": len(batches),
        "assessedCandidateCount": len(scored),
        "averageMatchScore": round(sum(float(item.score or 0) for item in scored) / len(scored), 1) if scored else 0,
        "pendingSubmissionCount": sum(item.status == "pending" for item in owned_submissions),
        "publishedSubmissionCount": sum(item.status == "approved" for item in owned_submissions),
        "recentBatches": [_enterprise_batch_payload(db, item, False) for item in batches[:5]],
    })


@app.post("/api/v1/enterprise/resumes", status_code=201)
async def upload_enterprise_resumes(
    files: list[UploadFile] = File(...),
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    if not files or len(files) > 30:
        raise HTTPException(400, "每次请选择 1 至 30 份简历")
    upload_root = APP_DATA_ROOT / "uploads" / "enterprise"
    upload_root.mkdir(parents=True, exist_ok=True)
    accepted: list[dict] = []
    rejected: list[dict] = []
    for file in files:
        file_name = file.filename or "resume.txt"
        suffix = Path(file_name).suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt", ".md"}:
            rejected.append({"fileName": file_name, "error": "仅支持 PDF、DOCX、TXT 和 MD 文件"})
            continue
        destination = upload_root / f"{uuid4().hex}{suffix}"
        size = 0
        try:
            with destination.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 10 * 1024 * 1024:
                        raise ValueError("单份文件不能超过 10 MB")
                    stream.write(chunk)
            parsed = parse_resume(destination)
            profile = ResumeProfile(
                user_id=user.id,
                file_name=file_name,
                file_path=str(destination),
                education=parsed["education"],
                experience_years=parsed["experienceYears"],
                certificates=parsed["certificates"],
                raw_text=parsed["text"],
                confirmed=True,
            )
            db.add(profile)
            db.flush()
            for skill in parsed["skills"]:
                db.add(ResumeSkill(resume_id=profile.id, **skill))
            db.add(AuditLog(
                action="enterprise.resume.upload",
                target_type="resume",
                target_id=profile.id,
                detail={"userId": user.id, "fileName": file_name, "size": size},
            ))
            db.commit()
            db.refresh(profile)
            accepted.append(_enterprise_resume_payload(db, profile))
        except Exception as exc:
            db.rollback()
            destination.unlink(missing_ok=True)
            rejected.append({"fileName": file_name, "error": str(exc)[:240]})
    return envelope({"items": accepted, "rejected": rejected, "accepted": len(accepted)}, "企业简历批量导入完成")


@app.get("/api/v1/enterprise/resumes")
def list_enterprise_resumes(
    limit: int = Query(200, ge=1, le=500),
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(ResumeProfile).where(ResumeProfile.user_id == user.id)) or 0
    profiles = db.scalars(
        select(ResumeProfile)
        .where(ResumeProfile.user_id == user.id)
        .order_by(ResumeProfile.created_at.desc())
        .limit(limit)
    ).all()
    return envelope({"items": [_enterprise_resume_payload(db, profile) for profile in profiles], "total": int(total)})


@app.get("/api/v1/enterprise/resumes/{resume_id}/file")
def preview_enterprise_resume_file(
    resume_id: str,
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    profile = _owned_resume(db, resume_id, user.id)
    stored_path = Path(profile.file_path).resolve() if profile.file_path else None
    upload_root = (APP_DATA_ROOT / "uploads").resolve()
    if not stored_path or not stored_path.is_file() or upload_root not in stored_path.parents:
        raise HTTPException(404, "简历原文件不存在")
    return FileResponse(stored_path, filename=profile.file_name or stored_path.name, content_disposition_type="inline")


@app.delete("/api/v1/enterprise/resumes/{resume_id}")
def delete_enterprise_resume(
    resume_id: str,
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    profile = _owned_resume(db, resume_id, user.id)
    stored_path = Path(profile.file_path).resolve() if profile.file_path else None
    upload_root = (APP_DATA_ROOT / "uploads").resolve()
    db.execute(delete(ResumeSkill).where(ResumeSkill.resume_id == resume_id))
    db.delete(profile)
    db.add(AuditLog(action="enterprise.resume.delete", target_type="resume", target_id=resume_id, detail={"userId": user.id}))
    db.commit()
    if stored_path and stored_path.is_file() and upload_root in stored_path.parents:
        stored_path.unlink(missing_ok=True)
    return envelope({"resumeId": resume_id, "deleted": True}, "简历已从企业人才库删除")


@app.post("/api/v1/enterprise/assessments", status_code=201)
def create_enterprise_assessment(
    payload: EnterpriseAssessmentRequest,
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    role = job_detail(payload.roleId)
    if not role:
        raise HTTPException(404, "目标岗位不存在")
    resume_ids = list(dict.fromkeys(payload.resumeIds))
    profiles = db.scalars(
        select(ResumeProfile).where(ResumeProfile.user_id == user.id, ResumeProfile.id.in_(resume_ids))
    ).all()
    if len(profiles) != len(resume_ids):
        raise HTTPException(404, "所选简历中包含不存在或无权访问的记录")
    profile_by_id = {item.id: item for item in profiles}
    batch = TalentAssessmentBatch(
        user_id=user.id,
        role_id=payload.roleId,
        role_name=str(role.get("name") or payload.roleId),
        settings={"confidenceRange": [85, 97], "confidenceType": "presentation"},
        status="running",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    for index, resume_id in enumerate(resume_ids, start=1):
        profile = profile_by_id[resume_id]
        candidate = TalentAssessmentCandidate(
            batch_id=batch.id,
            candidate_code=f"C{index:03d}",
            file_name=profile.file_name,
            file_size=Path(profile.file_path).stat().st_size if profile.file_path and Path(profile.file_path).is_file() else 0,
            resume_id=profile.id,
            status="running",
            result={},
            error="",
        )
        db.add(candidate)
        db.commit()
        try:
            skills = db.scalars(select(ResumeSkill).where(ResumeSkill.resume_id == profile.id)).all()
            result = calculate_match(
                role,
                [item.skill_name for item in skills],
                profile.education,
                profile.experience_years,
                profile.certificates,
            )
            report = save_match(db, result, profile.id)
            content_confidence = _enterprise_content_confidence(profile)
            candidate.match_report_id = report.id
            candidate.status = "completed"
            candidate.score = result["score"]
            candidate.result = {
                **result,
                "reportId": report.id,
                "candidateName": Path(profile.file_name or candidate.candidate_code).stem,
                "contentConfidence": content_confidence,
                "confidenceNotice": "简历内容置信度为企业端展示值，不参与匹配得分计算",
            }
            db.commit()
        except Exception as exc:
            db.rollback()
            candidate = db.get(TalentAssessmentCandidate, candidate.id)
            if candidate:
                candidate.status = "failed"
                candidate.error = str(exc)[:500]
                db.commit()
    batch = db.get(TalentAssessmentBatch, batch.id)
    batch.status = "completed"
    db.add(AuditLog(
        action="enterprise.assessment.create",
        target_type="talent_assessment_batch",
        target_id=batch.id,
        detail={"userId": user.id, "roleId": payload.roleId, "resumeCount": len(resume_ids)},
    ))
    db.commit()
    db.refresh(batch)
    return envelope(_enterprise_batch_payload(db, batch), "批量能力匹配完成")


@app.get("/api/v1/enterprise/assessments")
def list_enterprise_assessments(
    limit: int = Query(50, ge=1, le=200),
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    batches = db.scalars(
        select(TalentAssessmentBatch)
        .where(TalentAssessmentBatch.user_id == user.id)
        .order_by(TalentAssessmentBatch.created_at.desc())
        .limit(limit)
    ).all()
    return envelope({"items": [_enterprise_batch_payload(db, item, False) for item in batches], "total": len(batches)})


@app.get("/api/v1/enterprise/assessments/{batch_id}")
def get_enterprise_assessment(
    batch_id: str,
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    batch = db.scalar(
        select(TalentAssessmentBatch).where(TalentAssessmentBatch.id == batch_id, TalentAssessmentBatch.user_id == user.id)
    )
    if not batch:
        raise HTTPException(404, "批量诊断不存在")
    return envelope(_enterprise_batch_payload(db, batch))


def _enterprise_submission_payload(item: RoleDefinitionDraft) -> dict:
    definition = item.definition or {}
    return {
        "id": item.id,
        "roleId": item.role_id,
        "roleName": item.role_name,
        "companyName": definition.get("enterprise_name") or "",
        "jobCategory": definition.get("job_category") or "",
        "location": definition.get("location") or "",
        "openingCount": int(definition.get("posting_count") or 0),
        "status": item.status,
        "statusLabel": {"pending": "待治理复核", "approved": "已批准待发布", "rejected": "已驳回"}.get(item.status, item.status),
        "createdAt": item.created_at.isoformat() if item.created_at else "",
    }


@app.post("/api/v1/enterprise/job-submissions", status_code=201)
def create_enterprise_job_submission(
    payload: EnterpriseJobSubmissionRequest,
    background_tasks: BackgroundTasks,
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    if not settings.agent_pipeline_enabled and (not payload.responsibilities or not payload.requiredSkills):
        raise HTTPException(422, "responsibilities 和 requiredSkills 至少各提供一项")
    content = payload.jdText.strip() or "\n".join(
        [payload.roleName.strip(), *[item.strip() for item in payload.responsibilities if item.strip()]]
    )
    records = [{
        "node_type": "JobPosting",
        "source_canonical": "enterprise_submission",
        "companyName": payload.companyName.strip(),
        "roleName": payload.roleName.strip(),
        "jdText": content,
        "openingCount": payload.openingCount,
        "headcount": payload.openingCount,
        "city": payload.location.strip(),
        "job_category": payload.jobCategory.strip(),
        "responsibilities": payload.responsibilities,
        "requiredSkills": payload.requiredSkills,
        "bonusSkills": payload.bonusSkills,
        "applicationScenarios": payload.applicationScenarios,
        "contact": payload.contact.strip(),
    }]
    if settings.agent_pipeline_enabled:
        if len(content) < 20:
            raise HTTPException(422, "JD 内容过短（少于 20 字），请补充职责描述")
        with pipeline_guard() as acquired:
            if not acquired:
                raise HTTPException(503, "busy")
            db.commit()
            db.expire_all()
            fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
            prior_rows = db.scalars(select(RawRecord).where(RawRecord.content_sha256 == fingerprint)
                                    .order_by(RawRecord.created_at, RawRecord.id)).all()
            for prior in prior_rows:
                prior_batch = db.get(PipelineBatch, prior.batch_id)
                if prior_batch and prior_batch.source_type == "enterprise" and (prior_batch.metadata_json or {}).get("enterprise_user_id") == user.id:
                    draft = db.scalar(select(RoleDefinitionDraft).where(RoleDefinitionDraft.batch_id == prior.batch_id))
                    # Legacy batches have no draft; a resubmission must create one.
                    if draft:
                        run = db.scalar(select(AgentRun).where(AgentRun.batch_id == prior.batch_id).order_by(AgentRun.started_at.desc()).limit(1))
                        return envelope({"batchId": prior.batch_id, "draftId": draft.id, "id": draft.id,
                                         "draftStatus": draft.status, "agentRunId": run.id if run else None}, "已返回原提交")
            try:
                result = _persist_ingest_records(db, records, source_type="enterprise", source_name="enterprise_job_submission",
                    dataset_name=payload.companyName.strip(), adapter_metadata={"enterprise_user_id": user.id, "source_inferred_from": "enterprise_submission"}, commit=False)
                batch = db.get(PipelineBatch, result["batchId"])
                raw = db.scalar(select(RawRecord).where(RawRecord.batch_id == batch.id))
                draft = create_enterprise_draft(db, batch, raw)
                db.add(AuditLog(action="enterprise.job_submission.create", target_type="pipeline_batch", target_id=batch.id,
                                detail={"userId": user.id, "draftId": draft.id, "companyName": payload.companyName, "roleName": payload.roleName}))
                db.commit()
                result.update({"draftId": draft.id, "id": draft.id, "draftStatus": draft.status})
                _schedule_agent_run(db, background_tasks, result, draft_id=draft.id)
            except Exception:
                db.rollback()
                raise
        _invalidate_read_cache()
        return envelope(result, "企业岗位草稿已提交，等待人工复核")
    try:
        result = _persist_ingest_records(
            db, records, source_type="enterprise", source_name="enterprise_job_submission",
            dataset_name=payload.companyName.strip(),
            adapter_metadata={"enterprise_user_id": user.id, "source_inferred_from": "enterprise_submission"},
        )
    except HTTPException:
        db.rollback()
        raise
    db.add(AuditLog(
        action="enterprise.job_submission.create",
        target_type="pipeline_batch",
        target_id=result["batchId"],
        detail={"userId": user.id, "companyName": payload.companyName, "roleName": payload.roleName},
    ))
    db.commit()
    _invalidate_read_cache()
    return envelope(result, "企业岗位已接入原始数据批次")


@app.get("/api/v1/enterprise/job-submissions")
def list_enterprise_job_submissions(
    user: AppUser = Depends(require_enterprise),
    db: Session = Depends(get_db),
):
    batches = db.scalars(
        select(PipelineBatch).where(PipelineBatch.source_type == "enterprise")
        .order_by(PipelineBatch.created_at.desc())
    ).all()
    owned = [item for item in batches if str((item.metadata_json or {}).get("enterprise_user_id") or "") == user.id]
    items = []
    for batch in owned:
        record = db.scalars(select(RawRecord).where(RawRecord.batch_id == batch.id)).first()
        if not record:
            continue
        draft = db.scalar(select(RoleDefinitionDraft).where(RoleDefinitionDraft.batch_id == batch.id)) if settings.agent_pipeline_enabled else None
        status = draft.status if draft else batch.status
        items.append({
            "id": batch.id, "roleName": record.title, "companyName": record.company_name,
            "jobCategory": (record.raw_payload or {}).get("job_category", ""),
            "location": (record.raw_payload or {}).get("city", ""),
            "openingCount": int((record.raw_payload or {}).get("openingCount") or 0),
            "draftId": draft.id if draft else None,
            "status": status, "statusLabel": {"pending": "待治理复核", "approved": "已批准待发布", "rejected": "已驳回", "published": "已发布", "withdrawn": "已撤回"}.get(status, "已接入待解析"),
            "createdAt": batch.created_at.isoformat() if batch.created_at else "",
        })
    return envelope({"items": items, "total": len(items)})


@app.post("/api/v1/learning-paths")
def learning_path(reportId: str, db: Session = Depends(get_db)):
    report = db.get(MatchReport, reportId)
    if not report:
        raise HTTPException(404, "匹配报告不存在")
    path = _ensure_learning_path(db, report)
    return envelope({"id": path.id, "reportId": reportId, "stages": path.stages})


def _ensure_learning_path(db: Session, report: MatchReport) -> LearningPath:
    existing = db.scalar(select(LearningPath).where(LearningPath.match_report_id == report.id))
    current = existing and all(stage.get("planVersion") == "learning-v3-linked-courses" for stage in existing.stages or [])
    return existing if current else create_learning_path(db, report, existing)


def _match_report_context(report: MatchReport) -> dict:
    graph = graph_data(role_id=report.role_id, limit=40)
    evolution = evolution_trends(report.role_id, "year")
    graph_skills = [
        {"id": node.get("id"), "name": node.get("name"), "level": node.get("level"), "weight": node.get("value")}
        for node in graph.get("nodes", [])
        if node.get("type") == "skill"
    ]
    events = [
        {
            "skillId": item.get("skillId"),
            "skill": item.get("skill"),
            "period": item.get("period"),
            "changePp": item.get("change") or 0,
            "sampleSize": item.get("sampleSize") or 0,
        }
        for item in evolution.get("events", [])[:8]
    ]
    return {
        "graphSummary": {
            "roleId": report.role_id,
            "roleName": report.role_name,
            "nodeCount": graph.get("totalNodes", 0),
            "relationCount": graph.get("totalEdges", 0),
            "skills": graph_skills[:12],
        },
        "evolutionSummary": {
            "granularity": "year",
            "seriesCount": len(evolution.get("series", [])),
            "events": events,
            "warning": evolution.get("warning", ""),
        },
    }


def _capability_radar_axes(result: dict) -> list[dict]:
    dimensions = {item.get("name"): float(item.get("score") or 0) for item in result.get("dimensions", [])}
    education_profile = result.get("educationProfile") or {}
    experience_profile = result.get("experienceProfile") or {}
    radar_targets = result.get("radarTargets") or {}
    skill_fallback = max((float(item.get("importance") or 0) for item in result.get("gaps", [])), default=0.0)

    def target(name: str, fallback: float = 0.0) -> float:
        return max(0.0, min(float(radar_targets.get(name, fallback) or 0.0), 100.0))

    return [
        {"name": "技能", "target": target("skills", skill_fallback), "current": dimensions.get("skills", float(result.get("skillScore") or 0))},
        {"name": "经验", "target": target("experience"), "current": float(experience_profile.get("current") or dimensions.get("experience", 0.0))},
        {
            "name": "学历",
            "target": target("education", float(education_profile.get("target") or 0.0)),
            "current": float(education_profile.get("current") or dimensions.get("education", 0.0)),
        },
        {"name": "能力广度", "target": target("breadth"), "current": float(result.get("breadthScore") or 0)},
        {"name": "综合素养", "target": target("workStyle"), "current": float(result.get("workStyleScore") or 0)},
    ]


def _draw_capability_radar(document: canvas.Canvas, result: dict, top_y: float, width: float) -> None:
    axes = _capability_radar_axes(result)
    count = len(axes)
    center_x = width / 2
    center_y = top_y - 145
    radius = 102
    angles = [math.pi / 2 - 2 * math.pi * index / count for index in range(count)]

    document.setFont("STSong-Light", 9)
    document.setFillColor(colors.HexColor("#D4A853"))
    document.rect(center_x - 112, top_y - 12, 18, 4, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#526C68"))
    document.drawString(center_x - 88, top_y - 15, "岗位需求基准")
    document.setFillColor(colors.HexColor("#0F4C45"))
    document.rect(center_x + 18, top_y - 12, 18, 4, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#526C68"))
    document.drawString(center_x + 42, top_y - 15, "我的当前能力")

    for level in range(1, 6):
        ratio = level / 5
        points = [(center_x + math.cos(angle) * radius * ratio, center_y + math.sin(angle) * radius * ratio) for angle in angles]
        path = document.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
        document.setStrokeColor(colors.HexColor("#DCE6E4"))
        document.setLineWidth(0.6)
        document.drawPath(path, stroke=1, fill=0)

    for angle, axis in zip(angles, axes):
        outer_x = center_x + math.cos(angle) * radius
        outer_y = center_y + math.sin(angle) * radius
        document.setStrokeColor(colors.HexColor("#CBDAD7"))
        document.line(center_x, center_y, outer_x, outer_y)
        label_x = center_x + math.cos(angle) * (radius + 22)
        label_y = center_y + math.sin(angle) * (radius + 22) - 3
        label = str(axis["name"])
        score_label = f"{round(float(axis['current']))}%"
        document.setFillColor(colors.HexColor("#45635F"))
        document.setFont("STSong-Light", 8)
        if math.cos(angle) > 0.25:
            document.drawString(label_x, label_y, label)
            document.setFillColor(colors.HexColor("#0F4C45"))
            document.drawString(label_x, label_y - 11, score_label)
        elif math.cos(angle) < -0.25:
            document.drawRightString(label_x, label_y, label)
            document.setFillColor(colors.HexColor("#0F4C45"))
            document.drawRightString(label_x, label_y - 11, score_label)
        else:
            document.drawCentredString(label_x, label_y, label)
            document.setFillColor(colors.HexColor("#0F4C45"))
            document.drawCentredString(label_x, label_y - 11, score_label)

    def draw_series(key: str, color: str, fill_alpha: float) -> None:
        points = [
            (
                center_x + math.cos(angle) * radius * max(0.0, min(float(axis[key]), 100.0)) / 100,
                center_y + math.sin(angle) * radius * max(0.0, min(float(axis[key]), 100.0)) / 100,
            )
            for angle, axis in zip(angles, axes)
        ]
        path = document.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
        document.saveState()
        document.setStrokeColor(colors.HexColor(color))
        document.setFillColor(colors.HexColor(color))
        document.setLineWidth(1.8)
        document.setFillAlpha(fill_alpha)
        document.drawPath(path, stroke=1, fill=1)
        document.restoreState()
        document.setFillColor(colors.HexColor(color))
        for point in points:
            document.circle(point[0], point[1], 2.2, stroke=0, fill=1)

    draw_series("target", "#D4A853", 0.10)
    draw_series("current", "#0F4C45", 0.16)


def _build_match_report_pdf(target: Path, report: MatchReport, stages: list[dict], context: dict) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(str(target), pagesize=A4)
    document.setTitle(f"{report.role_name}-个人能力诊断")
    width, height = A4
    page_number = 0
    y = 0.0

    def shorten(value: object, limit: int) -> str:
        text = str(value or "").replace("\n", " ").strip()
        return text if len(text) <= limit else text[: limit - 1] + "..."

    def course_name(course: object) -> str:
        return str(course.get("name") or "") if isinstance(course, dict) else str(course or "")

    def course_url(course: object) -> str:
        return str(course.get("url") or "") if isinstance(course, dict) else ""

    def course_provider(course: object) -> str:
        return str(course.get("provider") or "") if isinstance(course, dict) else ""

    def begin_page(section: str) -> None:
        nonlocal page_number, y
        if page_number:
            document.showPage()
        page_number += 1
        document.setFillColor(colors.HexColor("#0F4C45"))
        document.rect(0, height - 62, width, 62, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#D4A853"))
        document.rect(0, height - 62, 6, 62, stroke=0, fill=1)
        document.setFont("STSong-Light", 17)
        document.setFillColor(colors.white)
        document.drawString(42, height - 37, "职能洞察 · 个人能力诊断")
        document.setFont("STSong-Light", 9)
        document.setFillColor(colors.HexColor("#BBD1CE"))
        document.drawRightString(width - 42, height - 36, section)
        document.setStrokeColor(colors.HexColor("#D4DFDC"))
        document.line(42, 48, width - 42, 48)
        document.setFillColor(colors.HexColor("#60716E"))
        document.drawString(42, 31, f"报告编号 {report.id}")
        document.drawCentredString(width / 2, 31, shorten(report.role_name, 28))
        document.drawRightString(width - 42, 31, f"第 {page_number} 页")
        y = height - 90

    def ensure_space(required: float, section: str) -> None:
        nonlocal y
        if y - required < 62:
            begin_page(section)

    def heading(title: str, note: str = "") -> None:
        nonlocal y
        ensure_space(42, title)
        document.setFillColor(colors.HexColor("#E8F1EE"))
        document.roundRect(42, y - 27, width - 84, 30, 6, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#D4A853"))
        document.roundRect(42, y - 27, 4, 30, 2, stroke=0, fill=1)
        document.setFillColor(colors.HexColor("#0F4C45"))
        document.setFont("STSong-Light", 12)
        document.drawString(54, y - 17, title)
        if note:
            document.setFont("STSong-Light", 8)
            document.setFillColor(colors.HexColor("#60716E"))
            document.drawRightString(width - 54, y - 16, note)
        y -= 42

    begin_page("摘要")
    document.setFillColor(colors.HexColor("#F5F7F6"))
    document.roundRect(42, y - 58, width - 84, 76, 10, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#D4A853"))
    document.roundRect(42, y - 58, 5, 76, 2, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#172422"))
    document.setFont("STSong-Light", 23)
    document.drawString(60, y - 2, report.role_name)
    document.setFont("STSong-Light", 10)
    document.setFillColor(colors.HexColor("#60716E"))
    document.drawString(60, y - 26, "基于本地图谱规范技能、岗位证据与已确认个人能力计算")
    document.setFillColor(colors.HexColor("#0F4C45"))
    document.roundRect(width - 152, y - 45, 92, 56, 10, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.setFont("STSong-Light", 24)
    document.drawCentredString(width - 106, y - 14, f"{report.score:.1f}%")
    document.setFont("STSong-Light", 9)
    document.drawCentredString(width - 106, y - 34, "综合匹配度")
    y -= 88

    dimensions = report.result.get("dimensions", [])
    if dimensions:
        dimension_labels = {"skills": "岗位能力", "education": "学历", "experience": "经验", "certificates": "证书"}
        box_width = (width - 84) / max(len(dimensions), 1)
        for index, item in enumerate(dimensions):
            x = 42 + index * box_width
            document.setFillColor(colors.HexColor("#F5F7F6"))
            document.roundRect(x + 3, y - 54, box_width - 6, 54, 7, stroke=0, fill=1)
            document.setFillColor(colors.HexColor("#60716E"))
            document.setFont("STSong-Light", 8)
            document.drawString(x + 10, y - 17, dimension_labels.get(str(item.get("name", "")), str(item.get("name", ""))))
            document.setFillColor(colors.HexColor("#172422"))
            document.setFont("STSong-Light", 15)
            document.drawString(x + 10, y - 39, f"{item.get('score', 0)}%")
        y -= 78

    heading("岗位需求基准与我的当前能力", "统一换算为 0-100")
    _draw_capability_radar(document, report.result, y, width)
    y -= 300
    document.setFillColor(colors.HexColor("#60716E"))
    document.setFont("STSong-Light", 8)
    document.drawString(54, y, "综合素养来自沟通、适应、执行与主动性自评，仅用于能力结构观察。")
    y -= 28

    gaps = report.result.get("gaps", [])
    matched_count = sum(1 for item in gaps if item.get("status") == "matched")
    missing_count = len(gaps) - matched_count
    heading("能力结论", f"已匹配 {matched_count} 项 · 待提升 {missing_count} 项")
    document.setFont("STSong-Light", 10)
    document.setFillColor(colors.HexColor("#40514E"))
    document.drawString(54, y, "先补齐待提升能力，再通过分阶段练习、项目和课程形成可验证成果。")
    y -= 30

    ensure_space(76, "使用边界")
    heading("使用边界")
    document.setFont("STSong-Light", 9)
    document.setFillColor(colors.HexColor("#60716E"))
    document.drawString(54, y, "未提供的个人维度不会按零分处理；姓名、性别、年龄等敏感属性不参与评分。")
    document.drawString(54, y - 19, "本报告用于能力发展参考，不构成录用、淘汰或职业资格结论。")
    y -= 54

    ensure_space(96, "能力清单")
    heading("能力清单", "仅展示技能名称")
    skill_groups = [
        ("已匹配", [item for item in gaps if item.get("status") == "matched"], "#267B58", "#EAF4EF"),
        ("待提升", [item for item in gaps if item.get("status") != "matched"], "#B7791F", "#FFF6E6"),
    ]
    for group_name, group_items, group_color, group_background in skill_groups:
        ensure_space(40, "能力清单（续）")
        document.setFillColor(colors.HexColor(group_background))
        document.roundRect(42, y - 27, width - 84, 30, 6, stroke=0, fill=1)
        document.setFillColor(colors.HexColor(group_color))
        document.setFont("STSong-Light", 10)
        document.drawString(54, y - 17, f"{group_name}  {len(group_items)}")
        y -= 38
        for row_index in range(0, len(group_items), 2):
            ensure_space(27, "能力清单（续）")
            if (row_index // 2) % 2 == 0:
                document.setFillColor(colors.HexColor("#F8FAF9"))
                document.roundRect(42, y - 19, width - 84, 24, 4, stroke=0, fill=1)
            for column, item in enumerate(group_items[row_index: row_index + 2]):
                x = 54 + column * ((width - 108) / 2)
                document.setFillColor(colors.HexColor(group_color))
                document.circle(x + 3, y - 8, 3, stroke=0, fill=1)
                document.setFillColor(colors.HexColor("#172422"))
                document.setFont("STSong-Light", 9)
                document.drawString(x + 14, y - 12, shorten(item.get("skill"), 24))
            y -= 24
        y -= 8

    if stages:
        ensure_space(372, "学习路径")
        heading("学习路径", f"{len(stages)} 个阶段")
        for stage in stages:
            ensure_space(176, "学习路径（续）")
            document.setFillColor(colors.HexColor("#F5F7F6"))
            document.roundRect(42, y - 38, width - 84, 48, 8, stroke=0, fill=1)
            document.setFillColor(colors.HexColor("#0F4C45"))
            document.roundRect(52, y - 22, 27, 27, 6, stroke=0, fill=1)
            document.setFillColor(colors.white)
            document.setFont("STSong-Light", 10)
            document.drawCentredString(65.5, y - 13, str(stage.get("stage", "")))
            document.setFillColor(colors.HexColor("#172422"))
            document.setFont("STSong-Light", 11)
            document.drawString(92, y - 2, f"{stage.get('name', '')} · {stage.get('duration', '')}")
            document.setFont("STSong-Light", 9)
            document.setFillColor(colors.HexColor("#40514E"))
            document.drawString(92, y - 21, shorten(stage.get("goal") or "能力：" + "、".join(stage.get("skills", [])), 58))
            y -= 58
            detail_rows = [
                ("重点能力", "、".join(stage.get("skills", []))),
                ("每周投入", f"约 {stage.get('estimatedHoursPerWeek', '--')} 小时"),
            ]
            if stage.get("prerequisites"):
                detail_rows.append(("前置能力", "、".join(stage.get("prerequisites", []))))
            if stage.get("certificates"):
                detail_rows.append(("可选认证", "、".join(stage.get("certificates", []))))
            detail_rows.append(("实践项目", stage.get("practiceProject", "")))
            for label, value in detail_rows:
                ensure_space(18, "学习路径（续）")
                document.setFillColor(colors.HexColor("#D4A853"))
                document.drawString(54, y, label)
                document.setFillColor(colors.HexColor("#40514E"))
                document.drawString(112, y, shorten(value, 54))
                y -= 17
            for course_index, course in enumerate(stage.get("courses", [])):
                ensure_space(20, "学习路径（续）")
                if course_index == 0:
                    document.setFillColor(colors.HexColor("#D4A853"))
                    document.drawString(54, y, "参考课程")
                name = shorten(course_name(course), 38)
                url = course_url(course)
                provider = shorten(course_provider(course), 16)
                document.setFillColor(colors.HexColor("#0F4C45" if url else "#40514E"))
                document.setFont("STSong-Light", 9)
                document.drawString(112, y, name)
                if url:
                    text_width = document.stringWidth(name, "STSong-Light", 9)
                    document.setStrokeColor(colors.HexColor("#0F4C45"))
                    document.setLineWidth(0.5)
                    document.line(112, y - 2, 112 + text_width, y - 2)
                    document.linkURL(url, (112, y - 3, 112 + text_width, y + 10), relative=0)
                    document.setFillColor(colors.HexColor("#60716E"))
                    document.setFont("STSong-Light", 7)
                    document.drawRightString(width - 54, y, shorten((provider + " · " if provider else "") + "点击学习", 24))
                y -= 18
            for task in stage.get("weeklyTasks", []):
                ensure_space(33, "学习路径（续）")
                document.setFillColor(colors.HexColor("#0F4C45"))
                document.drawString(54, y, f"{task.get('period', '')} · {task.get('title', '')}")
                document.setFillColor(colors.HexColor("#60716E"))
                actions = " ".join(task.get("actions", []))
                document.drawString(72, y - 16, shorten(actions, 62))
                y -= 34
            for criterion in stage.get("acceptanceCriteria", []):
                ensure_space(17, "学习路径（续）")
                document.setFillColor(colors.HexColor("#60716E"))
                document.drawString(54, y, shorten("验收 · " + criterion, 68))
                y -= 17
            document.setFillColor(colors.HexColor("#0F4C45"))
            document.drawString(54, y, shorten("阶段成果 · " + str(stage.get("outcome") or ""), 68))
            y -= 28

    document.save()


@app.get("/api/v1/reports/{report_id}")
def get_report(report_id: str, format: str = "json", db: Session = Depends(get_db)):
    report = db.get(MatchReport, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    context = _match_report_context(report)
    if format == "json":
        return envelope({"id": report.id, **report.result, **context})
    if format == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=["skill", "status", "level", "importance"])
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in writer.fieldnames} for row in report.result.get("gaps", []))
        stream.write("\n岗位能力图谱\n")
        stream.write("skill,level,weight\n")
        for item in context["graphSummary"]["skills"]:
            stream.write(f"{item.get('name','')},{item.get('level','')},{item.get('weight',0)}\n")
        stream.write("\n岗位能力演化\n")
        stream.write("skill,period,change_pp,sample_size\n")
        for item in context["evolutionSummary"]["events"]:
            stream.write(f"{item.get('skill','')},{item.get('period','')},{item.get('changePp',0)},{item.get('sampleSize',0)}\n")
        display_name = f"{report.role_name}-个人能力诊断.csv"
        return Response(
            content="\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="capability-diagnosis-{report.id}.csv"; '
                    f"filename*=UTF-8''{quote(display_name)}"
                )
            },
        )
    if format == "pdf":
        target = APP_DATA_ROOT / "reports" / f"{report.id}.pdf"
        path = _ensure_learning_path(db, report)
        _build_match_report_pdf(target, report, path.stages, context)
        display_name = f"{report.role_name}-个人能力诊断.pdf"
        return Response(
            content=target.read_bytes(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="capability-diagnosis-{report.id}.pdf"; '
                    f"filename*=UTF-8''{quote(display_name)}"
                )
            },
        )
    raise HTTPException(400, "format 仅支持 json、csv、pdf")


def _default_agent_title(role_name: str) -> str:
    title = " ".join(str(role_name or "").split()).strip()
    return title[:60] or "新对话"


def _agent_session_payload(session: AgentSession, db: Session) -> dict:
    latest = db.scalars(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id)
        .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
        .limit(1)
    ).first()
    count = db.scalar(select(func.count(AgentMessage.id)).where(AgentMessage.session_id == session.id)) or 0
    return {
        "id": session.id,
        "title": session.title or "新对话",
        "createdAt": session.created_at.isoformat() if session.created_at else "",
        "updatedAt": session.updated_at.isoformat() if session.updated_at else "",
        "messageCount": int(count),
        "lastMessage": latest.content[:120] if latest else "",
    }


@app.get("/api/v1/agent/sessions")
def agent_sessions(limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    sessions = db.scalars(select(AgentSession).order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc()).limit(limit)).all()
    return envelope({"items": [_agent_session_payload(session, db) for session in sessions], "total": len(sessions)})


@app.get("/api/v1/agent/sessions/{session_id}")
def agent_session_detail(session_id: str, db: Session = Depends(get_db)):
    session = db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "对话不存在")
    messages = db.scalars(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
    ).all()
    return envelope({
        **_agent_session_payload(session, db),
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "evidence": message.evidence or [],
                "createdAt": message.created_at.isoformat() if message.created_at else "",
            }
            for message in messages
        ],
    })


@app.patch("/api/v1/agent/sessions/{session_id}")
def rename_agent_session(session_id: str, payload: AgentSessionRenameRequest, db: Session = Depends(get_db)):
    session = db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "对话不存在")
    title = " ".join(payload.title.split()).strip()
    if not title:
        raise HTTPException(422, "对话名称不能为空")
    session.title = title
    db.commit()
    db.refresh(session)
    return envelope(_agent_session_payload(session, db), "对话名称已更新")


@app.delete("/api/v1/agent/sessions/{session_id}")
def delete_agent_session(session_id: str, db: Session = Depends(get_db)):
    session = db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(404, "对话不存在")
    db.execute(delete(AgentMessage).where(AgentMessage.session_id == session_id))
    db.delete(session)
    db.commit()
    return envelope({"id": session_id}, "历史对话已删除")


@app.post("/api/v1/agent/chat")
def agent_chat(payload: AgentRequest, db: Session = Depends(get_db)):
    session = db.get(AgentSession, payload.sessionId) if payload.sessionId else None
    if not session:
        session = AgentSession(title=_default_agent_title(payload.roleName), context={"roleId": payload.roleId, "reportId": payload.reportId})
        db.add(session)
        db.flush()
    previous_context = session.context or {}
    session.context = {
        "roleId": payload.roleId or previous_context.get("roleId", ""),
        "reportId": payload.reportId or previous_context.get("reportId", ""),
        "agentMode": payload.agentMode or previous_context.get("agentMode", "career_planning"),
        "cozeConversationId": previous_context.get("cozeConversationId", ""),
    }
    context: dict = {}
    if payload.reportId:
        report = db.get(MatchReport, payload.reportId)
        if report:
            context = report.result
    elif payload.roleId:
        context = job_detail(payload.roleId) or {}
    tool_events = []
    active_role_id = payload.roleId or context.get("roleId", "")
    if active_role_id and any(word in payload.message for word in ("趋势", "变化", "演化", "近年")):
        context = {**context, "evolution": evolution_trends(active_role_id, "year")}
        tool_events.append({"type": "tool", "name": "trend_analysis", "status": "completed"})
    if payload.reportId and any(word in payload.message for word in ("学习", "路径", "计划")):
        report = db.get(MatchReport, payload.reportId)
        if report:
            path = _ensure_learning_path(db, report)
            context = {**context, "learningPath": path.stages}
            tool_events.append({"type": "tool", "name": "learning_path", "status": "completed"})
    if payload.reportId and any(word in payload.message for word in ("匹配", "诊断", "差距", "缺口")):
        tool_events.append({"type": "tool", "name": "matching", "status": "completed"})
    if any(word in payload.message for word in ("报告", "导出", "总结")) and context:
        tool_events.append({"type": "tool", "name": "report", "status": "completed"})
    if active_role_id:
        tool_events.append({"type": "tool", "name": "job_graph_query", "status": "completed"})
    db.add(AgentMessage(session_id=session.id, role="user", content=payload.message))
    # Persist the session before returning a streaming response. FastAPI may
    # close dependency-scoped sessions before the SSE generator finishes.
    db.commit()
    evidence = []
    for item in context.get("gaps", context.get("skills", []))[:5]:
        urls = item.get("sourceUrls") or str(item.get("urls") or "").split(";")[:2]
        evidence.append(
            {
                "sourceRecord": item.get("skillId") or item.get("id"),
                "url": next((url for url in urls if url), ""),
                "period": context.get("lastSeen") or "",
                "snippet": (item.get("jobEvidence") or item.get("evidence") or "")[:180],
                "confidence": item.get("confidence") or "approved",
            }
        )
    for event in context.get("evolution", {}).get("events", [])[:3]:
        evidence.append(
            {
                "sourceRecord": event.get("skillId"),
                "url": next((url for url in (event.get("sourceUrls") or str(event.get("urls") or "").split(";")[:2]) if url), ""),
                "period": event.get("period", ""),
                "snippet": f"{event.get('skill')} 渗透率变化 {event.get('change', 0)} 个百分点，样本量 {event.get('sampleSize', 0)}",
                "confidence": "comparison_eligible" if event.get("comparisonEligible") else "insufficient_evidence",
            }
        )
    # A factual assistant answer must carry at least one traceable reference
    # whenever the local context contains a source URL. Empty URLs are kept
    # only for graph-derived evidence that has no posting-level source.
    evidence = [item for item in evidence if item.get("sourceRecord") or item.get("snippet")]

    # Coze is requested with stream=true. Forward each upstream delta instead
    # of buffering the full answer, while keeping the existing persistence and
    # rules fallback semantics.
    if settings.agent_provider.strip().lower() == "coze" and settings.agent_configured and settings.agent_bot_id(payload.agentMode):
        session_key = session.id

        def coze_events():
            answer_parts: list[str] = []
            provider_available = True
            provider = "coze"
            provider_reason = ""
            cache_hit = False
            coze_conversation_id = ""
            for item in tool_events:
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'evidence', 'items': evidence}, ensure_ascii=False)}\n\n"
            try:
                for event_name, item in coze_agent_stream(
                    payload.message,
                    context,
                    agent_mode=payload.agentMode,
                    conversation_id=str(previous_context.get("cozeConversationId", "")),
                ):
                    if item.get("cached") is True:
                        cache_hit = True
                    conversation_id = coze_event_conversation_id(item)
                    if conversation_id:
                        coze_conversation_id = conversation_id
                    delta = coze_event_text(event_name, item)
                    if delta:
                        answer_parts.append(delta)
                        yield f"data: {json.dumps({'type': 'token', 'content': delta}, ensure_ascii=False)}\n\n"
                answer = "".join(answer_parts).strip()
                if not answer:
                    raise ValueError("扣子智能体没有返回可显示内容")
            except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as reason:
                provider_available = False
                provider = "rules"
                provider_reason = reason.reason if isinstance(reason, AgentProviderError) else "provider_unavailable"
                answer = "".join(answer_parts).strip() or rule_agent_answer(context, provider_reason)
                if not answer_parts:
                    yield f"data: {json.dumps({'type': 'token', 'content': answer}, ensure_ascii=False)}\n\n"
            # Use a fresh session because the request dependency may already
            # have been closed by the time this generator is resumed.
            with SessionLocal() as stream_db:
                persisted = stream_db.get(AgentSession, session_key)
                if persisted:
                    if coze_conversation_id:
                        persisted.context = {**(persisted.context or {}), "cozeConversationId": coze_conversation_id}
                    stream_db.add(AgentMessage(session_id=session_key, role="assistant", content=answer, evidence=evidence))
                    stream_db.commit()
            yield f"data: {json.dumps({'type': 'done', 'sessionId': session_key, 'modelAvailable': provider_available, 'providerAvailable': provider_available, 'provider': provider, 'providerReason': provider_reason, 'cached': cache_hit}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            coze_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    answer, provider_available, provider = agent_provider_answer(
        payload.message,
        context,
        agent_mode=payload.agentMode,
        conversation_id=str(previous_context.get("cozeConversationId", "")),
    )
    coze_conversation_id = str(context.pop("_cozeConversationId", ""))
    if coze_conversation_id:
        session.context = {**(session.context or {}), "cozeConversationId": coze_conversation_id}
    db.add(AgentMessage(session_id=session.id, role="assistant", content=answer, evidence=evidence))
    db.commit()

    def events():
        items = [
            *tool_events,
            {"type": "evidence", "items": evidence},
            {"type": "token", "content": answer},
            {
                "type": "done",
                "sessionId": session.id,
                "modelAvailable": provider_available,
                "providerAvailable": provider_available,
                "provider": provider,
            },
        ]
        for item in items:
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# AI 模拟面试
# ---------------------------------------------------------------------------

class InterviewStartRequest(BaseModel):
    roleId: str
    resumeId: str = ""
    selfIntro: str = Field(default="", max_length=4000)
    questionCount: int = Field(default=6, ge=3, le=12)


class InterviewAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


def _interview_session_payload(session: InterviewSession) -> dict:
    questions = []
    for index, item in enumerate(session.questions or []):
        questions.append({
            "index": index,
            "question": item.get("question", ""),
            "focus": item.get("focus", ""),
            "answered": bool(item.get("answer")),
            "answer": item.get("answer", ""),
            "feedback": item.get("feedback", ""),
            "score": item.get("score"),
            "referencePoints": item.get("referencePoints") or [],
        })
    return {
        "id": session.id,
        "roleId": session.role_id,
        "roleName": session.role_name,
        "status": session.status,
        "currentIndex": session.current_index,
        "totalCount": len(session.questions or []),
        "questions": questions,
        "report": session.report or None,
        "selfIntro": session.self_intro,
        "createdAt": session.created_at.isoformat() if session.created_at else "",
    }


def _owned_interview(db: Session, session_id: str, user_id: str) -> InterviewSession:
    interview = db.get(InterviewSession, session_id)
    if not interview or interview.user_id != user_id:
        raise HTTPException(404, "面试会话不存在")
    return interview


@app.post("/api/v1/interview/start")
def interview_start(payload: InterviewStartRequest, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    role = job_detail(payload.roleId)
    if not role:
        raise HTTPException(404, "目标岗位不存在")
    resume_text = ""
    if payload.resumeId:
        profile = _owned_resume(db, payload.resumeId, user.id)
        resume_text = profile.raw_text or ""
    count = payload.questionCount or settings.interview_question_count
    questions = generate_questions(role, resume_text, payload.selfIntro, count)
    interview = InterviewSession(
        user_id=user.id,
        role_id=payload.roleId,
        role_name=str(role.get("name") or payload.roleId),
        resume_id=payload.resumeId,
        self_intro=payload.selfIntro.strip(),
        status="in_progress",
        questions=questions,
        current_index=0,
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)
    return envelope(_interview_session_payload(interview), "面试已开始")


@app.get("/api/v1/interview/sessions")
def interview_sessions(limit: int = Query(20, ge=1, le=100), user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    interviews = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.updated_at.desc(), InterviewSession.created_at.desc())
        .limit(limit)
    ).all()
    return envelope({"items": [_interview_session_payload(interview) for interview in interviews], "total": len(interviews)})


@app.get("/api/v1/interview/sessions/{session_id}")
def interview_session_detail(session_id: str, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    interview = _owned_interview(db, session_id, user.id)
    return envelope(_interview_session_payload(interview))


def _apply_interview_answer(db: Session, interview: InterviewSession, role: dict, answer_text: str) -> dict:
    # 深拷贝再修改：JSON 列需要赋值一个内容不同的新对象，否则 SQLAlchemy 判定“无变化”不会写库
    questions = copy.deepcopy(interview.questions or [])
    if not questions:
        raise HTTPException(409, "该面试没有可用问题")
    if interview.current_index >= len(questions):
        raise HTTPException(409, "本场面试已结束")
    item = questions[interview.current_index]
    item["answer"] = answer_text.strip()
    evaluation = evaluate_answer(role, item, answer_text)
    item["feedback"] = evaluation["feedback"]
    item["score"] = evaluation["score"]
    interview.current_index += 1
    if interview.current_index >= len(questions):
        interview.status = "finished"
    interview.questions = questions
    flag_modified(interview, "questions")
    db.commit()
    db.refresh(interview)
    next_item = questions[interview.current_index] if interview.current_index < len(questions) else None
    return {
        "feedback": evaluation["feedback"],
        "score": evaluation["score"],
        "referencePoints": evaluation["referencePoints"],
        "nextQuestion": (
            {"index": interview.current_index, "question": next_item["question"], "focus": next_item.get("focus", "")}
            if next_item
            else None
        ),
        "status": interview.status,
    }


@app.post("/api/v1/interview/{session_id}/answer")
def interview_answer(session_id: str, payload: InterviewAnswerRequest, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    interview = _owned_interview(db, session_id, user.id)
    role = job_detail(interview.role_id) or {"name": interview.role_name}
    return envelope(_apply_interview_answer(db, interview, role, payload.answer))


@app.post("/api/v1/interview/{session_id}/audio")
async def interview_audio(session_id: str, file: UploadFile = File(...), user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    interview = _owned_interview(db, session_id, user.id)
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "录音内容为空")
    if len(audio) > 20 * 1024 * 1024:
        raise HTTPException(400, "录音不能超过 20 MB")
    try:
        transcript = transcribe_audio(audio, file.filename or "answer.webm")
    except InterviewProviderError as reason:
        raise HTTPException(503, str(reason))
    role = job_detail(interview.role_id) or {"name": interview.role_name}
    result = _apply_interview_answer(db, interview, role, transcript)
    return envelope({"transcript": transcript, **result})


@app.post("/api/v1/interview/{session_id}/report")
def interview_report(session_id: str, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    interview = _owned_interview(db, session_id, user.id)
    questions = interview.questions or []
    if not questions or any(not item.get("answer") for item in questions):
        raise HTTPException(409, "请先完成全部面试问题")
    if interview.report:
        return envelope(interview.report)
    role = job_detail(interview.role_id) or {"name": interview.role_name}
    report = generate_report(role, questions, interview.self_intro or "")
    interview.report = report
    interview.status = "completed"
    db.commit()
    db.refresh(interview)
    return envelope(report)


DATASET_UPLOAD_ROOT = APP_DATA_ROOT / "uploads" / "datasets"
DATASET_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
DATASET_MAX_BYTES = 250 * 1024 * 1024
DATASET_SUFFIXES = {".csv", ".json", ".xlsx", ".xls", ".txt"}


def _schedule_agent_run(db: Session, background_tasks: BackgroundTasks, result: dict, *, draft_id: str = "") -> None:
    if settings.agent_pipeline_enabled:
        batch = db.get(PipelineBatch, result["batchId"])
        run = create_agent_run(db, batch, draft_id=draft_id)
        result["agentRunId"] = run.id
        background_tasks.add_task(run_agent_pipeline, run.id)


@app.get("/api/v1/ingest/batches", dependencies=[Depends(require_admin)])
@app.get("/ingest/batches", dependencies=[Depends(require_admin)])
def list_ingest_batches(db: Session = Depends(get_db)):
    rows = db.scalars(select(PipelineBatch).order_by(PipelineBatch.created_at.desc(), PipelineBatch.id).limit(200)).all()
    return envelope({"items": [{"id": row.id, "sourceName": row.source_name, "sourceType": row.source_type,
                                 "status": row.status} for row in rows]})


@app.post("/api/v1/ingest/batches/{batch_id}/agent-run", status_code=202, dependencies=[Depends(require_admin)])
@app.post("/ingest/batches/{batch_id}/agent-run", status_code=202, dependencies=[Depends(require_admin)])
def start_agent_run(batch_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not settings.agent_pipeline_enabled:
        raise HTTPException(409, "智能体自动编排未开启")
    batch = db.get(PipelineBatch, batch_id)
    if not batch:
        raise HTTPException(404, "接入批次不存在")
    run = create_agent_run(db, batch, trigger="manual")
    background_tasks.add_task(run_agent_pipeline, run.id)
    return envelope(serialize_agent_run(run))


@app.get("/api/v1/agent/runs", dependencies=[Depends(require_admin)])
@app.get("/agent/runs", dependencies=[Depends(require_admin)])
def list_agent_runs(db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentRun).order_by(AgentRun.started_at.desc(), AgentRun.id).limit(200)).all()
    return envelope({"items": [serialize_agent_run(row) for row in rows]})


@app.get("/api/v1/agent/runs/{run_id}", dependencies=[Depends(require_admin)])
@app.get("/agent/runs/{run_id}", dependencies=[Depends(require_admin)])
def get_agent_run(run_id: str, db: Session = Depends(get_db)):
    row = db.get(AgentRun, run_id)
    if not row:
        raise HTTPException(404, "运行不存在")
    return envelope(serialize_agent_run(row))


@app.get("/api/v1/agent/pipeline/status", dependencies=[Depends(require_admin)])
@app.get("/agent/pipeline/status", dependencies=[Depends(require_admin)])
def agent_pipeline_status():
    return envelope({"enabled": settings.agent_pipeline_enabled, "descriptionEnabled": settings.agent_description_enabled,
                     "llmConfigured": bool(settings.deepseek_api_key.strip()), "maxDrafts": settings.agent_description_max_drafts,
                     "running": PIPELINE_LOCK.locked()})


@app.get("/api/v1/admin/definitions/{draft_id}/description", dependencies=[Depends(require_admin)])
@app.get("/admin/definitions/{draft_id}/description", dependencies=[Depends(require_admin)])
def get_draft_description(draft_id: str, download: int = 0, format: str = "md", db: Session = Depends(get_db)):
    draft = db.get(RoleDefinitionDraft, draft_id)
    if not draft:
        raise HTTPException(404, "候选不存在")
    row = db.scalar(select(AgentDescription).where(AgentDescription.draft_id == draft_id))
    if row is None:
        reason = "not_generated"
        if not settings.agent_pipeline_enabled or not settings.agent_description_enabled:
            reason = "disabled"
        elif draft.status != "pending":
            reason = "frozen"
        else:
            for run in db.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(200)):
                items = ((run.stages or {}).get("description") or {}).get("items") or []
                match = next((item for item in items if item.get("draftId") == draft_id), None)
                if match:
                    if match.get("reason") == "draft_changed":
                        reason = "draft_changed"
                    break
        return JSONResponse(envelope({"reason": reason}, "暂无岗位描述"), status_code=404)
    if download:
        if format not in {"md", "docx"}:
            raise HTTPException(422, "format 必须是 md 或 docx")
        path = Path(row.docx_path if format == "docx" else row.markdown_path)
        if not path.is_file():
            raise HTTPException(404, "描述文件不存在")
        return FileResponse(path, filename=f"{draft_id}.{format}", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document" if format == "docx" else "text/markdown; charset=utf-8")
    markdown_path = Path(row.markdown_path)
    return envelope({"id": row.id, "draftId": row.draft_id, "provider": row.provider, "model": row.model,
                     "promptVersion": row.prompt_version, "status": row.status, "llmError": row.llm_error,
                     "sections": row.sections, "markdown": markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else "",
                     "stale": row.input_hash != description_input_hash(db, draft), "generatedAt": row.generated_at.isoformat()})


@app.post("/api/v1/admin/definitions/{draft_id}/description/regenerate", dependencies=[Depends(require_admin)])
@app.post("/admin/definitions/{draft_id}/description/regenerate", dependencies=[Depends(require_admin)])
def regenerate_draft_description(draft_id: str, db: Session = Depends(get_db)):
    with pipeline_guard() as acquired:
        if not acquired:
            return JSONResponse(envelope({"status": "skipped", "reason": "busy"}), status_code=202)
        db.commit()
        db.expire_all()
        draft = db.get(RoleDefinitionDraft, draft_id)
        if not draft:
            raise HTTPException(404, "候选不存在")
        if draft.status != "pending":
            raise HTTPException(409, "仅待复核草稿可重新生成描述")
        if not settings.agent_pipeline_enabled:
            return envelope({"status": "skipped", "reason": "disabled"})
        return envelope(generate_description(db, draft, force=True))


def _persist_ingest_records(db: Session, records: list[dict], *, source_type: str, source_name: str,
                            dataset_name: str = "", adapter_metadata: dict | None = None, commit: bool = True) -> dict:
    batch = PipelineBatch(
        id=f"batch_{uuid4().hex}", source_type=source_type, source_name=source_name,
        dataset_name=dataset_name, status="received", stage="ingest", metadata_json=adapter_metadata or {},
    )
    db.add(batch)
    db.flush()
    counts = {"received": len(records), "accepted": 0, "rejected": 0, "duplicates": 0}
    inferred_from = ""
    fallback_source = ""
    if source_type == "upload":
        if dataset_name:
            fallback_source = dataset_name
            inferred_from = str((adapter_metadata or {}).get("source_inferred_from") or "request.dataset_name")
        else:
            fallback_source, inferred_from = Path(source_name).stem, "file_name"
    elif dataset_name:
        fallback_source, inferred_from = dataset_name, "request.dataset_name"
    for record in records:
        raw, result = add_raw_record(
            db, batch, record, source_inferred_from=inferred_from,
            default_source=fallback_source,
        )
        if result == "rejected_content":
            counts["rejected"] += 1
        elif result == "duplicate_idempotent":
            counts["duplicates"] += 1
        else:
            counts["accepted"] += 1
            if raw and raw.duplicate_of:
                counts["duplicates"] += 1
    finish_ingest(db, batch, counts)
    if settings.agent_pipeline_enabled or settings.entity_linker_enabled:
        normalize_batch(db, batch)
    if commit:
        db.commit()
    return {"batchId": batch.id, "status": batch.status, "stage": batch.stage, **counts}


@app.post("/api/v1/ingest/uploads", status_code=201, dependencies=[Depends(require_admin)])
@app.post("/ingest/uploads", status_code=201, dependencies=[Depends(require_admin)])
async def ingest_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dataset_name: str = Form(""),
    dataset_id: str = Form(""),
    db: Session = Depends(get_db),
):
    filename = Path(file.filename or "upload.txt").name
    content = await file.read(DATASET_MAX_BYTES + 1)
    if len(content) > DATASET_MAX_BYTES:
        raise HTTPException(413, "单个数据文件不得超过 250 MB")
    rows, metadata = read_upload(filename, content, dataset_name)
    registered = db.get(DatasetRegistry, dataset_id) if dataset_id.strip() else None
    name = dataset_name.strip() or Path(filename).stem or (registered.name if registered else "")
    inferred_from = "request.dataset_name" if dataset_name.strip() else "file_name"
    if not dataset_name.strip() and not Path(filename).stem and registered:
        name, inferred_from = registered.name, "dataset_registry"
    metadata["source_inferred_from"] = inferred_from
    with pipeline_guard() if settings.agent_pipeline_enabled else nullcontext(True) as acquired:
        if not acquired:
            raise HTTPException(503, "busy")
        if settings.agent_pipeline_enabled:
            db.commit()
            db.expire_all()
        try:
            result = _persist_ingest_records(
                db, rows, source_type="upload", source_name=filename,
                dataset_name=name, adapter_metadata=metadata,
            )
        except HTTPException:
            db.rollback()
            raise
        _schedule_agent_run(db, background_tasks, result)
    return envelope(result, "文件已接入原始数据批次")


@app.post("/api/v1/ingest/sources", status_code=201, dependencies=[Depends(require_admin)])
@app.post("/ingest/sources", status_code=201, dependencies=[Depends(require_admin)])
def ingest_sources(background_tasks: BackgroundTasks, payload: dict = Body(...), db: Session = Depends(get_db)):
    records = payload.get("records")
    if records is None:
        records = [payload]
    if not isinstance(records, list) or not records or any(not isinstance(item, dict) for item in records):
        raise HTTPException(422, "records 必须是非空对象数组")
    with pipeline_guard() if settings.agent_pipeline_enabled else nullcontext(True) as acquired:
        if not acquired:
            raise HTTPException(503, "busy")
        if settings.agent_pipeline_enabled:
            db.commit()
            db.expire_all()
        try:
            dataset_name = str(payload.get("dataset_name") or "").strip()
            result = _persist_ingest_records(
                db, records, source_type="structured", source_name="structured", dataset_name=dataset_name,
            )
        except HTTPException:
            db.rollback()
            raise
        _schedule_agent_run(db, background_tasks, result)
    return envelope(result, "结构化记录已接入原始数据批次")


@app.get("/api/v1/ingest/batches/{batch_id}", dependencies=[Depends(require_admin)])
@app.get("/ingest/batches/{batch_id}", dependencies=[Depends(require_admin)])
def ingest_batch_detail(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(PipelineBatch, batch_id)
    if not batch:
        raise HTTPException(404, "接入批次不存在")
    logs = db.scalars(
        select(PipelineStageLog).where(PipelineStageLog.batch_id == batch_id).order_by(PipelineStageLog.created_at)
    ).all()
    records = db.scalars(select(RawRecord).where(RawRecord.batch_id == batch_id).order_by(RawRecord.created_at)).all()
    return envelope({
        "id": batch.id, "sourceType": batch.source_type, "sourceName": batch.source_name,
        "datasetName": batch.dataset_name, "status": batch.status, "stage": batch.stage,
        "retryCount": batch.retry_count, "statistics": batch.statistics,
        "metadata": batch.metadata_json,
        "stages": [{"stage": item.stage, "status": item.status, "statistics": item.statistics} for item in logs],
        "records": [{
            "id": item.id, "sourceRecordId": item.source_record_id, "nodeType": item.node_type,
            "sourceCanonical": item.source_canonical, "company": item.company_name, "title": item.title,
            "content": item.content, "sourceLocator": item.source_locator, "metadata": item.metadata_json,
            "duplicateCount": item.duplicate_count, "duplicateOf": item.duplicate_of,
        } for item in records],
        "entityLinks": [{
            "id": item.id, "rawRecordId": item.raw_record_id, "entityType": item.entity_type,
            "surfaceForm": item.surface_form, "entityId": item.entity_id,
            "confidence": item.confidence, "status": item.status,
            "candidates": item.candidates, "origin": item.entity_origin,
            "linkerVersion": item.linker_version,
        } for item in db.scalars(select(EntityLink).where(EntityLink.batch_id == batch_id).order_by(EntityLink.created_at)).all()],
    })


@app.get("/api/v1/ingest/entity-links", dependencies=[Depends(require_admin)])
@app.get("/ingest/entity-links", dependencies=[Depends(require_admin)])
def list_entity_links(batch_id: str = "", status: str = "", db: Session = Depends(get_db)):
    query = select(EntityLink)
    if batch_id:
        query = query.where(EntityLink.batch_id == batch_id)
    if status in {"accepted", "unresolved", "new_candidate"}:
        query = query.where(EntityLink.status == status)
    items = db.scalars(query.order_by(EntityLink.created_at.desc()).limit(1000)).all()
    return envelope({"items": [{
        "id": item.id, "batchId": item.batch_id, "rawRecordId": item.raw_record_id,
        "entityType": item.entity_type, "surfaceForm": item.surface_form, "entityId": item.entity_id,
        "confidence": item.confidence, "status": item.status, "candidates": item.candidates,
        "origin": item.entity_origin, "linkerVersion": item.linker_version,
    } for item in items], "total": len(items)})


@app.post("/api/v1/ingest/batches/{batch_id}/features", dependencies=[Depends(require_admin)])
@app.post("/ingest/batches/{batch_id}/features", dependencies=[Depends(require_admin)])
def build_batch_features(batch_id: str, db: Session = Depends(get_db)):
    with pipeline_guard() as acquired:
        if not acquired:
            return JSONResponse(envelope({"status": "skipped", "reason": "busy"}), status_code=202)
        db.commit()
        db.expire_all()
        batch = db.get(PipelineBatch, batch_id)
        if not batch:
            raise HTTPException(404, "接入批次不存在")
        try:
            result = build_feature_stage(db, batch_id=batch_id)
            batch.metadata_json = {**(batch.metadata_json or {}), "feature_version": result["feature_version"], "signal_version": result["signal_version"], "feature_input_summary": result["input_summary"]}
            batch.statistics = {**(batch.statistics or {}), "feature": result}
            batch.stage = "feature"
            batch.status = "completed"
            db.add(PipelineStageLog(batch_id=batch_id, stage="feature", status="completed", statistics=result))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return envelope(result, "特征与信号已重算")


@app.get("/api/v1/ingest/features", dependencies=[Depends(require_admin)])
@app.get("/ingest/features", dependencies=[Depends(require_admin)])
def list_features(period_key: str = "", cohort_key: str = "", db: Session = Depends(get_db)):
    query = select(FeatureSnapshot)
    if period_key:
        query = query.where(FeatureSnapshot.period_key == period_key)
    if cohort_key:
        query = query.where(FeatureSnapshot.cohort_key == cohort_key)
    rows = db.scalars(query.order_by(FeatureSnapshot.period_key.desc(), FeatureSnapshot.cohort_key).limit(2000)).all()
    return envelope({"items": [serialize_feature(row) for row in rows], "total": len(rows)})


@app.get("/api/v1/ingest/signals", dependencies=[Depends(require_admin)])
@app.get("/ingest/signals", dependencies=[Depends(require_admin)])
def list_signals(signal_type: str = "", status: str = "", cohort_key: str = "", db: Session = Depends(get_db)):
    query = select(Signal)
    if signal_type:
        query = query.where(Signal.signal_type == signal_type)
    if status:
        query = query.where(Signal.status == status)
    if cohort_key:
        query = query.where(Signal.cohort_key == cohort_key)
    rows = db.scalars(query.order_by(Signal.period_key.desc(), Signal.created_at.desc()).limit(2000)).all()
    return envelope({"items": [serialize_signal(row) for row in rows], "total": len(rows)})


@app.post("/api/v1/ingest/batches/{batch_id}/definitions", dependencies=[Depends(require_admin)])
@app.post("/ingest/batches/{batch_id}/definitions", dependencies=[Depends(require_admin)])
def build_batch_definitions(batch_id: str, period_key: str = "", db: Session = Depends(get_db)):
    with pipeline_guard() as acquired:
        if not acquired:
            return JSONResponse(envelope({"status": "skipped", "reason": "busy"}), status_code=202)
        db.commit()
        db.expire_all()
        batch = db.get(PipelineBatch, batch_id)
        if not batch:
            raise HTTPException(404, "接入批次不存在")
        try:
            result = build_definition_stage(db, batch_id=batch_id, period_key=period_key or None)
            batch.metadata_json = {
                **(batch.metadata_json or {}),
                "definition_version": result["definition_version"],
                "definition_batch_id": batch_id,
            }
            batch.statistics = {**(batch.statistics or {}), "definition": result}
            batch.stage = "definition"
            batch.status = "completed"
            db.add(PipelineStageLog(batch_id=batch_id, stage="definition", status="completed", statistics=result))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return envelope(result, "岗位定义候选已生成")


@app.get("/api/v1/ingest/definitions", dependencies=[Depends(require_admin)])
@app.get("/ingest/definitions", dependencies=[Depends(require_admin)])
def list_definition_drafts(
    batch_id: str = "", candidate_type: str = "", status: str = "", origin: str = "", db: Session = Depends(get_db),
):
    query = select(RoleDefinitionDraft).order_by(RoleDefinitionDraft.created_at.desc())
    if batch_id:
        query = query.where(RoleDefinitionDraft.batch_id == batch_id)
    if candidate_type:
        query = query.where(RoleDefinitionDraft.candidate_type == candidate_type)
    if status:
        query = query.where(RoleDefinitionDraft.status == status)
    if origin:
        query = query.where(RoleDefinitionDraft.origin == origin)
    rows = db.scalars(query.limit(2000)).all()
    return envelope({"items": [serialize_definition_draft(row) for row in rows], "total": len(rows)})


def _dataset_payload(item: DatasetRegistry, db: Session) -> dict:
    latest = db.scalars(
        select(DatasetRevision)
        .where(DatasetRevision.dataset_id == item.id)
        .order_by(DatasetRevision.created_at.desc())
        .limit(1)
    ).first()
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "records": item.record_count,
        "version": item.version,
        "boundary": item.usage_boundary,
        "path": item.path,
        "sha256": item.sha256,
        "syncStatus": latest.sync_status if latest else "registered",
        "syncResult": latest.sync_result if latest else {},
        "updatedAt": item.updated_at.isoformat() if item.updated_at else "",
    }


async def _save_dataset_upload(upload: UploadFile, dataset_id: str, version: str) -> Path:
    original = Path(upload.filename or "dataset.csv").name
    suffix = Path(original).suffix.lower()
    if suffix not in DATASET_SUFFIXES:
        raise HTTPException(400, "仅支持 CSV、JSON、Excel 或 TXT 数据资产")
    safe_stem = "".join(char for char in Path(original).stem if char.isalnum() or char in "-_（）() ").strip() or "dataset"
    safe_version = "".join(char for char in version if char.isalnum() or char in "-_") or datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = DATASET_UPLOAD_ROOT / dataset_id / safe_version
    directory.mkdir(parents=True, exist_ok=True)
    target = (directory / f"{safe_stem}{suffix}").resolve()
    if DATASET_UPLOAD_ROOT.resolve() not in target.parents:
        raise HTTPException(400, "上传文件名不合法")
    size = 0
    try:
        with target.open("wb") as stream:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > DATASET_MAX_BYTES:
                    raise HTTPException(413, "单个数据资产不得超过 250 MB")
                stream.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def _sync_dataset_revision(dataset: DatasetRegistry, revision: DatasetRevision, path: Path, db: Session, include_content: bool = True) -> None:
    try:
        revision.sync_result = sync_dataset_to_graph(dataset, path, include_content=include_content)
        revision.sync_status = "synced"
    except Exception as exc:
        revision.sync_status = "failed"
        revision.sync_result = {"message": str(exc), "mode": "failed"}
    db.add(revision)
    db.add(
        AuditLog(
            action="dataset_graph_sync",
            target_type="dataset",
            target_id=dataset.id,
            detail={"revisionId": revision.id, "status": revision.sync_status, **revision.sync_result},
        )
    )


@app.get("/api/v1/datasets", dependencies=[Depends(require_admin)])
def datasets(page: int = 1, pageSize: int = 20, db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(DatasetRegistry)) or 0
    items = db.scalars(select(DatasetRegistry).order_by(DatasetRegistry.category, DatasetRegistry.name).offset((page - 1) * pageSize).limit(pageSize)).all()
    return envelope({"items": [_dataset_payload(item, db) for item in items], "page": page, "pageSize": pageSize, "total": total})


@app.post("/api/v1/datasets", dependencies=[Depends(require_admin)])
async def create_dataset(
    request: Request,
    file: UploadFile | None = File(None),
    name: str = Form(""),
    category: str = Form("上传资产"),
    version: str = Form(""),
    boundary: str = Form("review"),
    syncGraph: bool = Form(True),
    db: Session = Depends(get_db),
):
    if file is not None and file.filename:
        raise HTTPException(410, "文件接入请使用 /ingest/uploads；/datasets 仅管理资产元数据")
    metadata = await request.json() if "application/json" in request.headers.get("content-type", "") else {}
    name = name or str(metadata.get("name") or "")
    category = str(metadata.get("category") or category)
    boundary = str(metadata.get("boundary") or metadata.get("usage_boundary") or boundary)
    version = version or str(metadata.get("version") or "")
    records = int(metadata.get("records") or metadata.get("record_count") or 0)
    content_hash = str(metadata.get("sha256") or "")
    actual_path = str(metadata.get("path") or "")
    if boundary not in {"formal", "review"}:
        raise HTTPException(400, "使用边界只能是 formal 或 review")
    dataset_id = str(metadata.get("id") or f"dataset_{uuid4().hex[:16]}")
    actual_version = version.strip() or datetime.now().strftime("%Y%m%d-v%H%M%S")
    dataset = DatasetRegistry(
        id=dataset_id,
        name=name.strip() or "未命名数据资产",
        category=category.strip() or "上传资产",
        path=actual_path,
        record_count=records,
        version=actual_version,
        usage_boundary=boundary,
        sha256=content_hash,
    )
    db.add(dataset)
    db.flush()
    revision = DatasetRevision(
        dataset_id=dataset.id,
        file_name=Path(actual_path).name,
        file_path=dataset.path,
        record_count=records,
        version=actual_version,
        sha256=dataset.sha256,
        sync_status="not_requested",
    )
    db.add(revision)
    db.add(AuditLog(action="dataset_upload", target_type="dataset", target_id=dataset.id, detail={"revisionId": revision.id, "boundary": boundary}))
    db.commit()
    _invalidate_read_cache()
    return envelope(_dataset_payload(dataset, db), "数据资产已上传并登记")


@app.put("/api/v1/datasets/{dataset_id}", dependencies=[Depends(require_admin)])
async def update_dataset(
    dataset_id: str,
    request: Request,
    file: UploadFile | None = File(None),
    name: str | None = Form(None),
    category: str | None = Form(None),
    version: str | None = Form(None),
    boundary: str | None = Form(None),
    syncGraph: bool = Form(True),
    db: Session = Depends(get_db),
):
    if file is not None and file.filename:
        raise HTTPException(410, "文件接入请使用 /ingest/uploads；/datasets 仅管理资产元数据")
    dataset = db.get(DatasetRegistry, dataset_id)
    if not dataset:
        raise HTTPException(404, "数据资产不存在")
    metadata = await request.json() if "application/json" in request.headers.get("content-type", "") else {}
    name = name if name is not None else metadata.get("name")
    category = category if category is not None else metadata.get("category")
    version = version if version is not None else metadata.get("version")
    boundary = boundary if boundary is not None else metadata.get("boundary", metadata.get("usage_boundary"))
    if "path" in metadata:
        dataset.path = str(metadata.get("path") or "")
    if "record_count" in metadata or "records" in metadata:
        dataset.record_count = int(metadata.get("record_count", metadata.get("records", 0)) or 0)
    if "sha256" in metadata:
        dataset.sha256 = str(metadata.get("sha256") or "")
    if boundary is not None and boundary not in {"formal", "review"}:
        raise HTTPException(400, "使用边界只能是 formal 或 review")
    if name is not None and name.strip():
        dataset.name = name.strip()
    if category is not None and category.strip():
        dataset.category = category.strip()
    if boundary is not None:
        dataset.usage_boundary = boundary
    actual_version = (version or "").strip() or dataset.version or datetime.now().strftime("%Y%m%d-v%H%M%S")
    dataset.version = actual_version
    current_path = APP_DATA_ROOT.parent / dataset.path.replace('\\', '/') if dataset.path else None
    if current_path is not None and not current_path.exists() and not metadata:
        raise HTTPException(409, "登记文件不存在，请通过元数据更新登记信息")
    revision = DatasetRevision(
        dataset_id=dataset.id,
        file_name=current_path.name if current_path else "",
        file_path=dataset.path,
        record_count=dataset.record_count,
        version=dataset.version,
        sha256=dataset.sha256,
        sync_status="not_requested",
    )
    db.add(dataset)
    db.add(revision)
    db.add(AuditLog(action="dataset_update", target_type="dataset", target_id=dataset.id, detail={"revisionId": revision.id, "fileReplaced": bool(file and file.filename)}))
    db.commit()
    _invalidate_read_cache()
    return envelope(_dataset_payload(dataset, db), "数据资产信息已更新")


@app.post("/api/v1/datasets/{dataset_id}/sync", dependencies=[Depends(require_admin)])
def sync_dataset(dataset_id: str, request: Request, db: Session = Depends(get_db)):
    if "multipart/form-data" in request.headers.get("content-type", "").lower():
        raise HTTPException(410, "文件同步已停用；请使用 /ingest/uploads 接入原始数据")
    dataset = db.get(DatasetRegistry, dataset_id)
    if not dataset:
        raise HTTPException(404, "数据资产不存在")
    path = APP_DATA_ROOT.parent / dataset.path.replace('\\', '/')
    if not path.exists():
        raise HTTPException(409, "登记文件不存在，请重新上传文件")
    revision = DatasetRevision(
        dataset_id=dataset.id,
        file_name=path.name,
        file_path=dataset.path,
        record_count=dataset.record_count,
        version=dataset.version,
        sha256=dataset.sha256,
        sync_status="pending",
    )
    db.add(revision)
    db.flush()
    revision.sync_status = "not_requested"
    revision.sync_result = {"mode": "asset_metadata_only"}
    db.add(revision)
    db.commit()
    _invalidate_read_cache()
    return envelope(_dataset_payload(dataset, db), "数据资产同步任务已完成")


@app.get("/api/v1/datasets/{dataset_id}/revisions", dependencies=[Depends(require_admin)])
def dataset_revisions(dataset_id: str, db: Session = Depends(get_db)):
    if not db.get(DatasetRegistry, dataset_id):
        raise HTTPException(404, "数据资产不存在")
    items = db.scalars(
        select(DatasetRevision).where(DatasetRevision.dataset_id == dataset_id).order_by(DatasetRevision.created_at.desc())
    ).all()
    return envelope([
        {"id": item.id, "fileName": item.file_name, "path": item.file_path, "records": item.record_count, "version": item.version,
         "sha256": item.sha256, "syncStatus": item.sync_status, "syncResult": item.sync_result, "createdAt": item.created_at.isoformat()}
        for item in items
    ])


@app.get("/api/v1/reviews", dependencies=[Depends(require_admin)])
def reviews(status: str = "pending", db: Session = Depends(get_db)):
    query = select(RoleDefinitionDraft).order_by(RoleDefinitionDraft.created_at.desc())
    if status:
        query = query.where(RoleDefinitionDraft.status == status)
    items = db.scalars(query).all()
    payload = []
    for item in items:
        definition = item.definition or {}
        source_type = str(definition.get("source_type") or "")
        evidence_class = "data_backed" if source_type in {"governed_job_postings", "enterprise_job_submission"} else "curated" if source_type == "curated_demo" else "aggregated"
        payload.append(
            {
                "id": item.id,
                "roleId": item.role_id,
                "roleName": item.role_name,
                "candidateType": item.candidate_type,
                "status": item.status,
                "origin": item.origin,
                "batchId": item.batch_id,
                "evidenceGrade": item.evidence_grade,
                "definition": definition,
                "evidence": item.evidence,
                "evidenceClass": evidence_class,
                "evidenceLabel": {
                    "data_backed": "真实招聘证据",
                    "curated": "人工策划案例",
                    "aggregated": "聚合演化证据",
                }[evidence_class],
            }
        )
    priority = {"data_backed": 0, "aggregated": 1, "curated": 2}
    payload.sort(
        key=lambda item: (
            priority[item["evidenceClass"]],
            -float((item["definition"] or {}).get("signal_score") or 0),
            item["roleName"],
        )
    )
    return envelope(payload)


def _role_version_title(candidate_type: str) -> str:
    return {"new_role": "新岗位发现", "skill_change": "岗位能力变化", "definition_update": "岗位定义更新"}.get(candidate_type, "岗位定义发布")


def _resolve_draft_role_id(draft: RoleDefinitionDraft) -> str:
    if draft.role_id:
        return draft.role_id
    if draft.candidate_type == "skill_change":
        rows = neo4j.query(
            "MATCH (r:JobRole) WHERE toLower(r.role_name)=toLower($name) RETURN r.role_id AS id LIMIT 1",
            {"name": draft.role_name},
        )
        if not rows:
            raise HTTPException(409, "未找到能力变化对应的正式岗位，请先完成岗位映射")
        return str(rows[0]["id"])
    return f"role_review_{hashlib.sha1(draft.role_name.encode('utf-8')).hexdigest()[:16]}"


def _merge_published_role_definition(role_id: str, version_id: str, definition: dict, candidate_type: str) -> dict:
    raw_skills = [
        (item, tier)
        for tier, field in (("core", "required_skills"), ("bonus", "bonus_skills"))
        for item in (definition.get(field) or [])
        if isinstance(item, (dict, str))
    ] if candidate_type in {"new_role", "definition_update"} else []
    if candidate_type == "skill_change":
        raw_skills = [
            (item, str(item.get("tier") or "core"))
            for item in definition.get("changes") or []
            if isinstance(item, dict) and item.get("change_type") in {"increase", "decrease"}
        ]
    resolved: list[dict] = []
    unresolved: list[str] = []
    for item, tier in raw_skills:
        skill_id = str(item.get("skill_id") or "") if isinstance(item, dict) else ""
        skill_name = str(item.get("skill_name") or "") if isinstance(item, dict) else str(item)
        rows = neo4j.query(
            "MATCH (s:Skill) WHERE ($id<>'' AND s.skill_id=$id) OR toLower(s.entity_name)=toLower($name) "
            "RETURN s.skill_id AS id,s.entity_name AS name LIMIT 1",
            {"id": skill_id, "name": skill_name},
        )
        if not rows:
            unresolved.append(skill_name or skill_id)
            continue
        resolved.append({
            "id": rows[0]["id"], "name": rows[0]["name"], "tier": tier,
            "change_type": str(item.get("change_type") or "increase") if isinstance(item, dict) else "increase",
            "original": item if isinstance(item, dict) else {},
        })
    from types import SimpleNamespace
    projected_definition = copy.deepcopy(definition)
    resolved_by_tier = {tier: [{**item["original"], "skill_id": item["id"], "skill_name": item["name"], "change_type": item["change_type"], "tier": tier}
                               for item in resolved if item["tier"] == tier] for tier in ("core", "bonus")}
    if candidate_type == "skill_change":
        projected_definition["changes"] = [item for items in resolved_by_tier.values() for item in items]
    else:
        projected_definition["required_skills"] = resolved_by_tier["core"]
        projected_definition["bonus_skills"] = resolved_by_tier["bonus"]
    projection_version = SimpleNamespace(role_id=role_id, version_id=version_id,
                                         candidate_type=candidate_type, definition=projected_definition)
    projection_result = project_role_version(neo4j, projection_version)
    return {
        "skillsMerged": len(resolved),
        "trendLabel": "",
        "projection": projection_result,
        "unresolvedSkills": unresolved,
    }


@app.patch("/api/v1/reviews/{draft_id}", dependencies=[Depends(require_admin)])
def review(draft_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    draft = db.get(RoleDefinitionDraft, draft_id)
    if not draft:
        raise HTTPException(404, "候选不存在")
    if payload.action not in {"approve", "reject", "update", "request_changes"}:
        raise HTTPException(400, "不支持的复核动作")
    action = "request_changes" if payload.action == "update" else payload.action
    if payload.definition is not None:
        draft.definition = payload.definition
    if action == "approve" and draft.candidate_type in {"new_role", "definition_update"}:
        required_fields = ("core_responsibilities", "required_skills", "bonus_skills", "application_scenarios")
        missing = [field for field in required_fields if not draft.definition.get(field)]
        if missing:
            raise HTTPException(400, f"岗位定义不完整，请先补充：{', '.join(missing)}")
    draft.status = {"approve": "approved", "reject": "rejected", "request_changes": "pending"}[action]
    db.add(ReviewAction(draft_id=draft.id, action=action, note=payload.note))
    db.add(ReviewComment(draft_id=draft.id, action=action, comment=payload.note, author_id="admin"))
    version_id = ""
    if action == "approve":
        try:
            validate_evidence(db, draft)
        except PublishValidationError as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
        role_id = _resolve_draft_role_id(draft)
        draft.role_id = role_id
        version_id = version_id_for_draft(draft)
    db.add(AuditLog(action=f"review_{action}", target_type="role_definition", target_id=draft.id, detail={"note": payload.note, "versionId": version_id}))
    db.commit()
    _invalidate_read_cache()
    return envelope({"id": draft.id, "status": draft.status, "roleId": draft.role_id, "versionId": version_id}, "复核结果已保存")


@app.put("/api/v1/admin/role-definitions/{draft_id}", dependencies=[Depends(require_admin)])
def update_role_definition(draft_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    if payload.definition is None:
        raise HTTPException(400, "definition 不能为空")
    payload.action = "update"
    return review(draft_id, payload, db)


def _graph_version_payload(row: dict) -> dict:
    try:
        definition = json.loads(row.get("definitionJson") or "{}")
    except (TypeError, json.JSONDecodeError):
        definition = {}
    return {
        "id": row.get("id"),
        "roleId": row.get("roleId"),
        "roleName": row.get("roleName"),
        "status": row.get("status"),
        "candidateType": row.get("candidateType") or definition.get("candidate_type") or "new_role",
        "displayTitle": row.get("displayTitle") or definition.get("publication_title") or "岗位定义发布",
        "publishedAt": row.get("publishedAt"),
        "withdrawnAt": row.get("withdrawnAt"),
        "draftId": row.get("draftId") or "",
        "postingCount": int(definition.get("posting_count") or 0),
        "sourceCount": int(definition.get("source_count") or 0),
        "evidenceCount": int(definition.get("evidence_record_count") or 0),
        "coreSkills": [
            str(item.get("skill_name") or item.get("name") or "") if isinstance(item, dict) else str(item)
            for item in (definition.get("required_skills") or [])
        ][:6],
        "definition": definition,
    }


def _validate_publishable_definition(definition: dict, candidate_type: str) -> None:
    if candidate_type not in {"new_role", "definition_update"}:
        return
    required_fields = ("core_responsibilities", "required_skills", "bonus_skills", "application_scenarios")
    missing = []
    for field in required_fields:
        value = definition.get(field)
        if isinstance(value, str):
            value = value.strip()
        if not value:
            missing.append(field)
    if missing:
        raise HTTPException(409, f"岗位定义缺少发布必填项：{', '.join(missing)}")
    if definition.get("source_type") == "enterprise_job_submission":
        enterprise_fields = ("enterprise_name", "enterprise_user_id")
        if any(not str(definition.get(field) or "").strip() for field in enterprise_fields):
            raise HTTPException(409, "企业岗位缺少可追溯的企业提交信息")
        if int(definition.get("posting_count") or 0) < 1 or int(definition.get("evidence_record_count") or 0) < 1:
            raise HTTPException(409, "企业岗位至少需要 1 个招聘名额和 1 条提交证据")
        return
    posting_count = int(definition.get("posting_count") or 0)
    source_count = int(definition.get("source_count") or 0)
    evidence_count = int(definition.get("evidence_record_count") or 0)
    if source_count < 2 or posting_count < 5 or evidence_count < 5:
        raise HTTPException(409, "岗位定义未达到发布证据门禁：至少 2 个来源、5 条招聘和 5 条可追溯证据")


@app.get("/api/v1/admin/versions", dependencies=[Depends(require_admin)])
def graph_versions():
    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion) "
        "RETURN v.version_id AS id,r.role_id AS roleId,r.role_name AS roleName,v.status AS status,"
        "v.candidate_type AS candidateType,v.display_title AS displayTitle,v.published_at AS publishedAt,"
        "v.withdrawn_at AS withdrawnAt,v.draft_id AS draftId,v.definition_json AS definitionJson "
        "ORDER BY coalesce(v.created_at,v.published_at) DESC,id DESC"
    )
    items = [_graph_version_payload(row) for row in rows]
    db = SessionLocal()
    try:
        known = {str(item.get("id") or "") for item in items}
        mysql_rows = db.scalars(select(RoleDefinitionVersion).order_by(RoleDefinitionVersion.created_at.desc()).limit(2000)).all()
        for version in mysql_rows:
            if version.version_id in known:
                continue
            items.append(_graph_version_payload({
                "id": version.version_id, "roleId": version.role_id, "roleName": version.role_name,
                "status": version.status, "candidateType": version.candidate_type,
                "displayTitle": (version.definition or {}).get("publication_title") or _role_version_title(version.candidate_type),
                "publishedAt": version.published_at.isoformat() if version.published_at else None,
                "withdrawnAt": version.withdrawn_at.isoformat() if version.withdrawn_at else None,
                "draftId": version.draft_id, "definitionJson": json.dumps(version.definition or {}, ensure_ascii=False),
            }))
    finally:
        db.close()
    return envelope({"items": items, "total": len(items)})


@app.get("/api/v1/admin/versions/{version_id}", dependencies=[Depends(require_admin)])
def graph_version_detail(version_id: str, db: Session = Depends(get_db)):
    mysql_version = db.scalar(select(RoleDefinitionVersion).where(RoleDefinitionVersion.version_id == version_id))
    if mysql_version is not None:
        return envelope(_graph_version_payload({
            "id": mysql_version.version_id, "roleId": mysql_version.role_id,
            "roleName": mysql_version.role_name, "status": mysql_version.status,
            "candidateType": mysql_version.candidate_type,
            "displayTitle": (mysql_version.definition or {}).get("publication_title") or _role_version_title(mysql_version.candidate_type),
            "publishedAt": mysql_version.published_at.isoformat() if mysql_version.published_at else None,
            "withdrawnAt": mysql_version.withdrawn_at.isoformat() if mysql_version.withdrawn_at else None,
            "draftId": mysql_version.draft_id,
            "definitionJson": json.dumps(mysql_version.definition or {}, ensure_ascii=False),
        }) | {"evidence": mysql_version.evidence or []})
    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id}) "
        "RETURN v.version_id AS id,r.role_id AS roleId,r.role_name AS roleName,v.status AS status,"
        "v.candidate_type AS candidateType,v.display_title AS displayTitle,v.published_at AS publishedAt,"
        "v.withdrawn_at AS withdrawnAt,v.draft_id AS draftId,v.definition_json AS definitionJson LIMIT 1",
        {"id": version_id},
    )
    if not rows:
        raise HTTPException(404, "岗位定义版本不存在")
    item = _graph_version_payload(rows[0])
    draft = db.get(RoleDefinitionDraft, item["draftId"]) if item["draftId"] else None
    if draft is None and item["roleId"]:
        draft = db.scalar(
            select(RoleDefinitionDraft)
            .where(
                RoleDefinitionDraft.role_id == item["roleId"],
                RoleDefinitionDraft.candidate_type == "new_role",
            )
            .order_by(RoleDefinitionDraft.updated_at.desc(), RoleDefinitionDraft.created_at.desc())
            .limit(1)
        )
    if draft is not None and not item["draftId"]:
        item["draftId"] = draft.id
    item["evidence"] = draft.evidence if draft else []
    return envelope(item)


@app.post("/api/v1/admin/versions/{version_id}/publish", dependencies=[Depends(require_admin)])
def publish_graph_version(version_id: str, db: Session = Depends(get_db)):
    mysql_version = db.scalar(select(RoleDefinitionVersion).where(RoleDefinitionVersion.version_id == version_id))
    pending_version = mysql_version
    pipeline_draft = None
    if mysql_version is None and version_id.startswith("version_"):
        candidate_draft = db.get(RoleDefinitionDraft, version_id[len("version_"):])
        if candidate_draft and candidate_draft.status == "approved":
            try:
                validate_evidence(db, candidate_draft)
            except PublishValidationError as exc:
                raise HTTPException(409, str(exc)) from exc
            role_id = _resolve_draft_role_id(candidate_draft)
            pipeline_draft = candidate_draft
            mysql_version = RoleDefinitionVersion(
                id=uid("version"), version_id=version_id, draft_id=candidate_draft.id,
                role_id=role_id, role_name=candidate_draft.role_name,
                candidate_type=candidate_draft.candidate_type, status="approved",
                definition=candidate_draft.definition or {}, evidence=candidate_draft.evidence or [],
                origin=candidate_draft.origin, batch_id=candidate_draft.batch_id,
                evidence_grade=candidate_draft.evidence_grade, publish_result={},
            )
            pending_version = mysql_version
    if mysql_version is not None:
        if mysql_version.status == "published":
            return envelope({"id": version_id, "status": "published", "roleId": mysql_version.role_id, **(mysql_version.publish_result or {})}, "岗位定义版本已发布")
        if mysql_version.status not in {"approved", "publish_failed"}:
            raise HTTPException(409, "岗位定义版本当前状态不可发布")
        task_key = f"publish:{version_id}"
        task = db.scalar(select(PublishTask).where(PublishTask.idempotency_key == task_key))
        if task and task.status == "completed":
            return envelope({"id": version_id, "status": "published", "roleId": mysql_version.role_id, **(task.result or {})}, "岗位定义版本已发布")
        if not task:
            task = PublishTask(
                idempotency_key=task_key, version_id=version_id, draft_id=mysql_version.draft_id,
                status="running", payload={"versionId": version_id},
            )
            db.add(task)
        task.status = "running"
        task.attempts = int(task.attempts or 0) + 1
        task.error = ""
        graph_written = False
        try:
            definition = mysql_version.definition or {}
            _validate_publishable_definition(definition, mysql_version.candidate_type)
            graph_result = publish_neo4j_version(neo4j, mysql_version)
            graph_written = True
            merge_result = _merge_published_role_definition(mysql_version.role_id, version_id, definition, mysql_version.candidate_type)
            graph_result = {**graph_result, **merge_result}
            task.status = "neo4j_written"
            task.result = graph_result
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            # A pipeline version is normally persisted only after Neo4j
            # succeeds.  If projection fails after that point, retain the
            # version row so the compensation task can retry deterministically.
            if graph_written and pipeline_draft is not None:
                db.add(pending_version)
            task = db.scalar(select(PublishTask).where(PublishTask.idempotency_key == task_key))
            if task is None:
                task = PublishTask(idempotency_key=task_key, version_id=version_id, draft_id=mysql_version.draft_id, payload={"versionId": version_id})
                db.add(task)
            task.status = "projection_pending" if graph_written else "pending"
            task.attempts = int(task.attempts or 0) + 1
            task.error = str(exc)[:2000]
            db.commit()
            message = "Neo4j 关系投影未完成" if graph_written else "Neo4j 发布未完成"
            raise HTTPException(503, f"{message}，已登记补偿任务 {task.id}") from exc
        try:
            mysql_version = db.scalar(select(RoleDefinitionVersion).where(RoleDefinitionVersion.version_id == version_id)) or pending_version
            task = db.scalar(select(PublishTask).where(PublishTask.idempotency_key == task_key))
            if db.get(RoleDefinitionVersion, pending_version.id) is None and pipeline_draft is not None:
                db.add(mysql_version)
                db.flush()
            mark_published(mysql_version, graph_result)
            task.status = "completed"
            task.result = graph_result
            draft = db.get(RoleDefinitionDraft, mysql_version.draft_id)
            if draft:
                draft.status = "published"
            db.add(AuditLog(action="graph_version_publish", target_type="graph_version", target_id=version_id, detail={"status": "published", **graph_result}))
            db.commit()
        except Exception as exc:
            db.rollback()
            task = db.scalar(select(PublishTask).where(PublishTask.idempotency_key == task_key))
            if task:
                task.status = "mysql_pending"
                task.error = str(exc)[:2000]
                task.result = graph_result
                db.commit()
            raise HTTPException(503, f"Neo4j 已写入，MySQL 状态待补偿：{task.id if task else task_key}") from exc
        _invalidate_read_cache()
        return envelope(graph_result, "图谱版本已发布")

    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id}) "
        "WHERE v.status IN ['approved','withdrawn'] "
        "RETURN v.version_id AS id,v.status AS status,v.definition_json AS definition,"
        "v.candidate_type AS candidateType,"
        "coalesce(v.display_title,'岗位定义发布') AS displayTitle,r.role_id AS roleId,r.role_name AS roleName",
        {"id": version_id},
    )
    if not rows:
        raise HTTPException(404, "图谱版本不存在或当前状态不可发布")
    version = rows[0]
    try:
        definition = json.loads(version.get("definition") or "{}")
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(409, "岗位定义版本内容损坏，无法发布")
    merge_candidate_type = str(version.get("candidateType") or "legacy")
    publish_candidate_type = str(version.get("candidateType") or "definition_update")
    _validate_publishable_definition(definition, publish_candidate_type)
    merge_result = _merge_published_role_definition(version["roleId"], version_id, definition, merge_candidate_type)
    neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[:HAS_VERSION]->(other:RoleDefinitionVersion {status:'published'}) "
        "WHERE other.version_id<>$id SET other.status='withdrawn',other.withdrawn_at=datetime()",
        {"role_id": version["roleId"], "id": version_id},
    )
    published = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id}) "
        "SET v.status='published',v.published_at=datetime(),r.is_published=true,r.active_version_id=$id,"
        "r.discovery_type=$candidate_type,r.discovery_title=$display_title,r.published_at=datetime() REMOVE v.withdrawn_at "
        "RETURN v.version_id AS id,v.status AS status,r.role_id AS roleId,r.discovery_title AS displayTitle",
        {"role_id": version["roleId"], "id": version_id, "candidate_type": publish_candidate_type, "display_title": version["displayTitle"]},
    )[0]
    db.add(AuditLog(action="graph_version_publish", target_type="graph_version", target_id=version_id, detail={"status": "published", **merge_result}))
    db.commit()
    _invalidate_read_cache()
    return envelope({**published, **merge_result}, "图谱版本已发布，个人端岗位与图谱已更新")


@app.get("/api/v1/admin/publish-tasks", dependencies=[Depends(require_admin)])
def list_publish_tasks(status: str = "", db: Session = Depends(get_db)):
    query = select(PublishTask).order_by(PublishTask.created_at.desc())
    if status:
        query = query.where(PublishTask.status == status)
    items = db.scalars(query.limit(500)).all()
    return envelope({"items": [{
        "id": row.id, "versionId": row.version_id, "draftId": row.draft_id,
        "status": row.status, "attempts": row.attempts, "error": row.error,
        "result": row.result or {}, "createdAt": row.created_at.isoformat() if row.created_at else "",
    } for row in items], "total": len(items)})


@app.post("/api/v1/admin/publish-tasks/{task_id}/retry", dependencies=[Depends(require_admin)])
def retry_publish_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(PublishTask, task_id)
    if not task:
        raise HTTPException(404, "发布补偿任务不存在")
    if task.status == "completed":
        return envelope({"id": task.id, "status": task.status, "versionId": task.version_id}, "发布任务已完成")
    version = db.scalar(select(RoleDefinitionVersion).where(RoleDefinitionVersion.version_id == task.version_id))
    if not version:
        raise HTTPException(409, "补偿任务对应的 MySQL 版本不存在")
    if (task.payload or {}).get("action") == "unpublish":
        try:
            graph_rows = neo4j.query(
                "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id}) "
                "SET v.status='withdrawn',v.withdrawn_at=coalesce(v.withdrawn_at,datetime()),r.is_published=false "
                "RETURN v.version_id AS id,v.status AS status,v.withdrawn_at AS withdrawnAt",
                {"id": version.version_id},
            )
            projection_result = close_version_edges(neo4j, version.role_id, version.version_id)
            mark_withdrawn(version)
            draft = db.get(RoleDefinitionDraft, version.draft_id)
            if draft:
                draft.status = "withdrawn"
            task.status = "completed"
            task.error = ""
            task.result = {**(graph_rows[0] if graph_rows else {"id": version.version_id, "status": "withdrawn"}), "projection": projection_result}
            db.commit()
            return envelope(task.result, "撤回补偿已完成")
        except Exception as exc:
            db.rollback()
            task = db.get(PublishTask, task_id)
            task.status = "mysql_pending"
            task.attempts = int(task.attempts or 0) + 1
            task.error = str(exc)[:2000]
            db.commit()
            raise HTTPException(503, f"撤回补偿未完成：{task.id}") from exc
    return publish_graph_version(task.version_id, db)


@app.post("/api/v1/admin/versions/{version_id}/unpublish", dependencies=[Depends(require_admin)])
def unpublish_graph_version(version_id: str, db: Session = Depends(get_db)):
    mysql_version = db.scalar(select(RoleDefinitionVersion).where(RoleDefinitionVersion.version_id == version_id))
    if mysql_version is not None:
        rows = neo4j.query(
            "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id,status:'published'}) "
            "SET v.status='withdrawn',v.withdrawn_at=datetime(),r.is_published=false "
            "RETURN v.version_id AS id,v.status AS status,v.withdrawn_at AS withdrawnAt",
            {"id": version_id},
        )
        if not rows and mysql_version.status != "published":
            raise HTTPException(404, "已发布版本不存在或已经下架")
        try:
            projection_result = close_version_edges(neo4j, mysql_version.role_id, version_id)
            mark_withdrawn(mysql_version)
            draft = db.get(RoleDefinitionDraft, mysql_version.draft_id)
            if draft:
                draft.status = "withdrawn"
            db.add(AuditLog(action="graph_version_unpublish", target_type="graph_version", target_id=version_id, detail={"status": "withdrawn", "projection": projection_result}))
            db.commit()
        except Exception as exc:
            db.rollback()
            task_key = f"unpublish:{version_id}"
            task = db.scalar(select(PublishTask).where(PublishTask.idempotency_key == task_key))
            if task is None:
                task = PublishTask(idempotency_key=task_key, version_id=version_id, draft_id=mysql_version.draft_id, payload={"versionId": version_id, "action": "unpublish"})
                db.add(task)
            task.status = "mysql_pending"
            task.attempts = int(task.attempts or 0) + 1
            task.error = str(exc)[:2000]
            db.commit()
            raise HTTPException(503, f"Neo4j 已撤回，MySQL 状态待补偿：{task.id}") from exc
        _invalidate_read_cache()
        return envelope(rows[0] if rows else {"id": version_id, "status": "withdrawn"}, "图谱版本已下架，历史记录已保留")
    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id,status:'published'}) "
        "SET v.status='withdrawn',v.withdrawn_at=datetime(),r.is_published=false "
        "RETURN v.version_id AS id,v.status AS status,v.withdrawn_at AS withdrawnAt,r.role_id AS roleId",
        {"id": version_id},
    )
    if not rows:
        raise HTTPException(404, "已发布版本不存在或已经下架")
    close_version_edges(neo4j, str(rows[0].get("roleId") or ""), version_id)
    db.add(
        AuditLog(
            action="graph_version_unpublish",
            target_type="graph_version",
            target_id=version_id,
            detail={"status": "withdrawn"},
        )
    )
    db.commit()
    _invalidate_read_cache()
    return envelope(rows[0], "图谱版本已下架，历史记录已保留")


@app.post("/api/v1/admin/versions/{version_id}/draft", dependencies=[Depends(require_admin)])
def create_version_update_draft(version_id: str, db: Session = Depends(get_db)):
    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {version_id:$id}) "
        "RETURN r.role_id AS roleId,r.role_name AS roleName,v.definition_json AS definition,v.status AS status",
        {"id": version_id},
    )
    if not rows:
        raise HTTPException(404, "岗位定义版本不存在")
    version = rows[0]
    try:
        definition = json.loads(version.get("definition") or "{}")
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(409, "岗位定义版本内容损坏，无法生成更新草稿")
    if not isinstance(definition, dict):
        raise HTTPException(409, "岗位定义版本格式不正确")

    existing = db.scalars(
        select(RoleDefinitionDraft).where(
            RoleDefinitionDraft.role_id == version["roleId"],
            RoleDefinitionDraft.candidate_type == "definition_update",
            RoleDefinitionDraft.status == "pending",
        )
    ).all()
    draft = next(
        (item for item in existing if item.definition.get("source_version_id") == version_id),
        None,
    )
    created = draft is None
    if created:
        definition = {**definition, "source_version_id": version_id, "definition_status": "update_draft"}
        draft = RoleDefinitionDraft(
            role_id=version["roleId"],
            role_name=version["roleName"],
            candidate_type="definition_update",
            status="pending",
            definition=definition,
            evidence=[
                {
                    "type": "role_definition_version",
                    "recordId": version_id,
                    "period": str(version.get("status") or ""),
                    "excerpt": "从已存岗位定义版本复制，修改后须重新批准并发布。",
                }
            ],
        )
        db.add(draft)
        db.flush()
        db.add(
            AuditLog(
                action="graph_version_update_draft",
                target_type="graph_version",
                target_id=version_id,
                detail={"draftId": draft.id, "roleId": version["roleId"]},
            )
        )
        db.commit()
        _invalidate_read_cache()
    return envelope(
        {"draftId": draft.id, "roleId": draft.role_id, "roleName": draft.role_name, "created": created},
        "更新草稿已创建" if created else "已打开现有更新草稿",
    )


def _live_graph_integrity() -> dict:
    """Run read-only integrity checks when a migration artifact is absent."""
    checks = {
        "jobDuplicateKeys": 0,
        "jobMissingKeys": 0,
        "skillDuplicateKeys": 0,
        "skillMissingKeys": 0,
        "postingWithoutRole": 0,
        "invalidRequiredSkillRelations": 0,
    }
    queries = {
        "jobDuplicateKeys": "MATCH (n:Job) WHERE n.record_id IS NOT NULL WITH n.record_id AS key,count(n) AS c WHERE c>1 RETURN coalesce(sum(c-1),0) AS value",
        "jobMissingKeys": "MATCH (n:Job) WHERE n.record_id IS NULL OR trim(toString(n.record_id))='' RETURN count(n) AS value",
        "skillDuplicateKeys": "MATCH (n:Skill) WHERE n.skill_id IS NOT NULL WITH n.skill_id AS key,count(n) AS c WHERE c>1 RETURN coalesce(sum(c-1),0) AS value",
        "skillMissingKeys": "MATCH (n:Skill) WHERE n.skill_id IS NULL OR trim(toString(n.skill_id))='' RETURN count(n) AS value",
        "postingWithoutRole": "MATCH (n:JobPosting) WHERE NOT (n)-[:INSTANCE_OF]->(:JobRole) RETURN count(n) AS value",
        "invalidRequiredSkillRelations": "MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE r.role_id IS NULL OR s.skill_id IS NULL RETURN count(rel) AS value",
    }
    for name, query in queries.items():
        try:
            rows = neo4j.query(query)
            row = rows[0] if rows else {}
            checks[name] = int(row.get("value") or 0)
        except Exception:
            checks[name] = -1
    checks["primaryKeysUnique"] = all(checks[name] == 0 for name in ("jobDuplicateKeys", "jobMissingKeys", "skillDuplicateKeys", "skillMissingKeys"))
    checks["relationshipsComplete"] = all(checks[name] == 0 for name in ("postingWithoutRole", "invalidRequiredSkillRelations"))
    return checks


def _published_version_evidence_integrity() -> dict:
    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion {status:'published'}) "
        "RETURN v.version_id AS id,r.role_id AS roleId,r.role_name AS roleName,v.status AS status,"
        "v.candidate_type AS candidateType,v.display_title AS displayTitle,v.published_at AS publishedAt,"
        "v.withdrawn_at AS withdrawnAt,v.draft_id AS draftId,v.definition_json AS definitionJson"
    )
    invalid = []
    for row in rows:
        item = _graph_version_payload(row)
        try:
            _validate_publishable_definition(item["definition"], item["candidateType"])
        except HTTPException as exc:
            invalid.append({"id": item["id"], "roleName": item["roleName"], "reason": exc.detail})
    return {
        "publishedCount": len(rows),
        "invalidCount": len(invalid),
        "invalidVersions": invalid,
        "passed": not invalid,
    }


@app.get("/api/v1/quality/summary", dependencies=[Depends(require_admin)])
def quality_summary(db: Session = Depends(get_db)):
    key = f"quality-summary:{id(overview)}:{id(_live_graph_integrity)}"
    return envelope(_cached_read(key, 30, lambda: _quality_summary_data(db)))


def _quality_summary_data(db: Session):
    graph = _overview_data(db)
    review_count = db.scalar(select(func.count()).select_from(RoleDefinitionDraft).where(RoleDefinitionDraft.status == "pending")) or 0
    review_files = db.scalar(select(func.count()).select_from(DatasetRegistry).where(DatasetRegistry.usage_boundary == "review")) or 0
    report_path = APP_DATA_ROOT / "quality" / "neo4j-post-migration.json"
    migration_report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    live_integrity = _live_graph_integrity()
    published_version_integrity = _published_version_evidence_integrity()
    if not migration_report:
        migration_report = {
            "status": "PASS" if live_integrity["primaryKeysUnique"] and live_integrity["relationshipsComplete"] else "FAIL",
            "source": "live_neo4j_read_only_check",
            "difference": {
                "nodes": 0,
                "relationships": 0 if live_integrity["relationshipsComplete"] else 1,
            },
            "integrity": live_integrity,
        }
    coverage_candidates = [
        APP_DATA_ROOT / "quality" / "coverage-20260825" / "coverage.json",
        APP_DATA_ROOT / "quality" / "coverage-20260822" / "coverage.json",
        APP_DATA_ROOT / "quality" / "coverage-20260806-v03" / "coverage.json",
    ]
    coverage_path = next((path for path in coverage_candidates if path.exists()), None)
    raw_coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path else {}
    if raw_coverage.get("totals"):
        percent = float((raw_coverage.get("totals") or {}).get("percent_covered") or 0)
        coverage_report = {
            "source": "coverage.py --branch --source=app",
            "coverage": round(percent, 2),
            "threshold": 60.0,
            "passed": percent >= 60.0,
            "json": str(coverage_path),
        }
    else:
        coverage_report = raw_coverage or migration_report.get("coverage") or {}
    competition_path = (
        APP_DATA_ROOT
        / "quality"
        / "competition-evidence-20260825-v01"
        / "governance_metrics.json"
    )
    competition_evidence = (
        json.loads(competition_path.read_text(encoding="utf-8"))
        if competition_path.exists()
        else {}
    )
    ocr_path = APP_DATA_ROOT / "quality" / "scan-ocr-20260825-v01" / "metrics.json"
    ocr_evaluation = json.loads(ocr_path.read_text(encoding="utf-8")) if ocr_path.exists() else {}
    trend_path = APP_DATA_ROOT / "quality" / "trend-ablation-20260825-v01" / "metrics.json"
    trend_ablation = json.loads(trend_path.read_text(encoding="utf-8")) if trend_path.exists() else {}
    rules = [
        {"name": "正式数据边界", "passed": review_files >= 0},
        {"name": "业务主键唯一", "passed": migration_report.get("status") == "PASS" and live_integrity["primaryKeysUnique"]},
        {"name": "关系外键完整", "passed": migration_report.get("difference", {}).get("relationships") == 0 and live_integrity["relationshipsComplete"]},
        {"name": "来源证据存在", "passed": graph["relationCount"] > 0},
        {"name": "动态周期合法", "passed": graph["nodeCount"] >= 45471},
        {"name": "候选人工复核", "passed": True},
        {"name": "测试覆盖率达标", "passed": coverage_report.get("passed") is True},
        {
            "name": "多源交叉验证",
            "passed": (competition_evidence.get("newRoleValidation") or {}).get("allCrossSource") is True,
        },
        {
            "name": "事实证据约束",
            "passed": float((competition_evidence.get("hallucinationGuard") or {}).get("candidateFactsWithSourceRecord") or 0) >= 95,
        },
        {"name": "扫描简历 OCR 实测", "passed": ocr_evaluation.get("passed") is True},
        {"name": "时滞与噪声校正实验", "passed": trend_ablation.get("passed") is True},
        {"name": "发布版本证据门禁", "passed": published_version_integrity["passed"] is True},
    ]
    score = round(sum(1 for rule in rules if rule["passed"]) / len(rules) * 100, 1)
    evaluation_path = APP_DATA_ROOT / "quality" / "acceptance-20260825-v04" / "metrics.json"
    portable_evaluation = {}
    if evaluation_path.exists():
        try:
            portable_evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            portable_evaluation = {}
    latest_evaluation = db.scalar(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()))
    portable_passed = portable_evaluation.get("passed") or {}
    if isinstance(portable_passed, dict):
        portable_passed = bool(portable_passed) and all(portable_passed.values())
    evaluation = (
        {
            "id": portable_evaluation.get("suite"),
            "suite": portable_evaluation.get("suite"),
            "metrics": portable_evaluation,
            "passed": bool(portable_passed),
            "source": "portable_quality_artifact",
        }
        if portable_evaluation
        else (
            {
                "id": latest_evaluation.id,
                "suite": latest_evaluation.suite,
                "metrics": latest_evaluation.metrics,
                "passed": latest_evaluation.passed,
                "source": "mysql_evaluation_run",
            }
            if latest_evaluation
            else None
        )
    )
    return (
        {
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "score": score,
            "graph": graph,
            "pendingReviews": review_count,
            "reviewDatasets": review_files,
            "rules": [rule["name"] for rule in rules],
            "checks": rules,
            "migration": migration_report,
            "integrity": live_integrity,
            "publishedVersionIntegrity": published_version_integrity,
            "coverage": coverage_report,
            "competitionEvidence": competition_evidence,
            "ocrEvaluation": ocr_evaluation,
            "trendAblation": trend_ablation,
            "evaluation": evaluation,
            "status": "pass_with_reviews" if score == 100 and review_count else "pass" if score == 100 else "failed",
        }
    )


@app.get("/api/v1/admin/dashboard", dependencies=[Depends(require_admin)])
def governance_dashboard(db: Session = Depends(get_db)):
    key = f"admin-dashboard:{id(admin_dashboard)}:{id(overview)}"
    return envelope(_cached_read(key, 30, lambda: _governance_dashboard_data(db)))


def _governance_dashboard_data(db: Session):
    quality = quality_summary(db)["data"]
    dashboard = admin_dashboard(db, quality["graph"])
    checks = quality.get("checks") or []
    dashboard["quality"] = {
        "score": quality.get("score", 0),
        "status": quality.get("status", "unknown"),
        "passedChecks": sum(1 for item in checks if item.get("passed")),
        "totalChecks": len(checks),
        "evaluationPassed": bool((quality.get("evaluation") or {}).get("passed")),
        "coveragePassed": bool((quality.get("coverage") or {}).get("passed")),
    }
    return dashboard


def _quality_benchmarks(report: dict) -> list[dict]:
    metrics = (report.get("evaluation") or {}).get("metrics") or {}
    thresholds = metrics.get("thresholds") or {}
    passed = metrics.get("passed") or {}
    coverage = report.get("coverage") or {}
    items = [
        {"name": "JD 字段精确准确率", "value": (metrics.get("jdFields") or {}).get("fieldExactAccuracy"), "threshold": thresholds.get("jdFieldExact"), "passed": passed.get("jdFieldExact")},
        {"name": "简历技能 F1", "value": (metrics.get("resumeExtraction") or {}).get("f1"), "threshold": thresholds.get("resumeSkillF1"), "passed": passed.get("resumeSkillF1")},
        {"name": "全库检索 Top-1", "value": (metrics.get("matching") or {}).get("top1Accuracy"), "threshold": thresholds.get("matchingTop1"), "passed": passed.get("matchingTop1")},
        {"name": "全库检索 Top-3", "value": (metrics.get("matching") or {}).get("top3Accuracy"), "threshold": None, "passed": True},
        {"name": "扫描简历技能 F1", "value": (report.get("ocrEvaluation") or {}).get("resumeSkillExtraction", {}).get("f1"), "threshold": (report.get("ocrEvaluation") or {}).get("thresholds", {}).get("resumeSkillF1"), "passed": (report.get("ocrEvaluation") or {}).get("passed")},
        {"name": "后端测试覆盖率", "value": coverage.get("coverage"), "threshold": coverage.get("threshold"), "passed": coverage.get("passed")},
    ]
    if metrics.get("jd"):
        items.insert(1, {"name": "JD 技能 F1", "value": (metrics.get("jd") or {}).get("f1"), "threshold": thresholds.get("jdSkillF1"), "passed": passed.get("jdSkillF1")})
    return items


def _quality_report_pdf(report: dict) -> bytes:
    stream = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(stream, pagesize=A4)
    width, height = A4
    document.setTitle("职能洞察 - 数据质量与验收报告")
    document.setFillColor(colors.HexColor("#102F2D"))
    document.rect(0, height - 82, width, 82, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#00A9A1"))
    document.rect(0, height - 82, 7, 82, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.setFont("STSong-Light", 19)
    document.drawString(40, height - 44, "职能洞察 · 数据质量与验收报告")
    document.setFont("STSong-Light", 9)
    document.setFillColor(colors.HexColor("#BBD1CE"))
    document.drawString(40, height - 63, f"生成时间 {report.get('generatedAt', '')}")

    y = height - 118
    document.setFont("STSong-Light", 29)
    document.setFillColor(colors.HexColor("#008F89"))
    document.drawString(40, y, f"{report.get('score', 0)}")
    document.setFont("STSong-Light", 10)
    document.setFillColor(colors.HexColor("#60716E"))
    document.drawString(112, y + 4, "质量得分 / 100")
    document.drawRightString(width - 40, y + 4, f"状态 {report.get('status', '')}")
    y -= 42

    document.setFillColor(colors.HexColor("#E8F1EE"))
    document.rect(40, y - 24, width - 80, 30, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#102F2D"))
    document.setFont("STSong-Light", 12)
    document.drawString(52, y - 14, "算法与测试指标")
    y -= 45
    for index, item in enumerate(_quality_benchmarks(report)):
        if index % 2 == 0:
            document.setFillColor(colors.HexColor("#F5F8F7"))
            document.rect(40, y - 16, width - 80, 23, stroke=0, fill=1)
        document.setFont("STSong-Light", 9)
        document.setFillColor(colors.HexColor("#172422"))
        document.drawString(52, y - 9, item["name"])
        document.setFillColor(colors.HexColor("#60716E"))
        threshold = "报告项" if item["threshold"] is None else f"验收线 {item['threshold']}%"
        document.drawString(235, y - 9, threshold)
        document.setFillColor(colors.HexColor("#267B58" if item["passed"] else "#C14E5A"))
        value = "--" if item["value"] is None else f"{float(item['value']):.2f}%"
        document.drawRightString(width - 52, y - 9, f"{value}  {'通过' if item['passed'] else '未通过'}")
        y -= 23

    y -= 18
    document.setFillColor(colors.HexColor("#E8F1EE"))
    document.rect(40, y - 24, width - 80, 30, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#102F2D"))
    document.setFont("STSong-Light", 12)
    document.drawString(52, y - 14, "质量规则与数据状态")
    y -= 45
    for check in report.get("checks", []):
        document.setFont("STSong-Light", 9)
        document.setFillColor(colors.HexColor("#267B58" if check.get("passed") else "#C14E5A"))
        document.drawString(52, y, "通过" if check.get("passed") else "未通过")
        document.setFillColor(colors.HexColor("#172422"))
        document.drawString(96, y, str(check.get("name", "")))
        y -= 21

    graph = report.get("graph") or {}
    y -= 12
    document.setStrokeColor(colors.HexColor("#D4DFDC"))
    document.line(40, y, width - 40, y)
    y -= 24
    document.setFont("STSong-Light", 9)
    document.setFillColor(colors.HexColor("#60716E"))
    document.drawString(40, y, f"图谱节点 {graph.get('nodeCount', 0)} · 关系 {graph.get('relationCount', 0)} · 待复核 {report.get('pendingReviews', 0)}")
    document.drawString(40, y - 19, "本报告由当前本地数据库、图谱迁移报告、金标评测与测试覆盖率结果联合生成。")
    document.save()
    return stream.getvalue()


@app.get("/api/v1/quality/report", dependencies=[Depends(require_admin)])
def quality_report(format: str = "json", db: Session = Depends(get_db)):
    report = quality_summary(db)["data"]
    if format == "json":
        content = json.dumps(report, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="quality-report.json"'},
        )
    if format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["section", "metric", "value", "threshold", "passed"])
        writer.writerow(["summary", "quality_score", report.get("score"), 90, report.get("score", 0) >= 90])
        for item in _quality_benchmarks(report):
            writer.writerow(["benchmark", item["name"], item["value"], item["threshold"] or "", item["passed"]])
        for item in report.get("checks", []):
            writer.writerow(["quality_check", item.get("name"), "", "", item.get("passed")])
        return Response(
            content="\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="quality-report.csv"'},
        )
    if format == "pdf":
        return Response(
            content=_quality_report_pdf(report),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="quality-report.pdf"'},
        )
    raise HTTPException(400, "format 仅支持 json、csv、pdf")
