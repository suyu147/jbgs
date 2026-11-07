from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppUser(Base, TimestampMixin):
    __tablename__ = "app_users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("user"))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(24), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DatasetRegistry(Base, TimestampMixin):
    __tablename__ = "dataset_registry"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80))
    path: Mapped[str] = mapped_column(Text)
    record_count: Mapped[int] = mapped_column(BigInteger, default=0)
    version: Mapped[str] = mapped_column(String(80), default="")
    usage_boundary: Mapped[str] = mapped_column(String(80), default="formal")
    sha256: Mapped[str] = mapped_column(String(64), default="")


class DatasetRevision(Base, TimestampMixin):
    __tablename__ = "dataset_revisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("dataset_revision"))
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_path: Mapped[str] = mapped_column(Text, default="")
    record_count: Mapped[int] = mapped_column(BigInteger, default=0)
    version: Mapped[str] = mapped_column(String(80), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    sync_status: Mapped[str] = mapped_column(String(24), default="pending")
    sync_result: Mapped[dict] = mapped_column(JSON, default=dict)


class PipelineBatch(Base, TimestampMixin):
    __tablename__ = "pipeline_batches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("batch"))
    source_type: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(255), default="")
    dataset_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="ingest")
    retry_count: Mapped[int] = mapped_column(default=0)
    statistics: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PipelineStageLog(Base):
    __tablename__ = "pipeline_stage_logs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("stage_log"))
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24))
    statistics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RawRecord(Base):
    __tablename__ = "raw_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("raw"))
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    source_record_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    node_type: Mapped[str] = mapped_column(String(64), default="")
    source_canonical: Mapped[str] = mapped_column(String(255), default="")
    company_name: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    observation_count: Mapped[int] = mapped_column(default=1)
    duplicate_count: Mapped[int] = mapped_column(default=0)
    duplicate_of: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExtractedRecord(Base, TimestampMixin):
    __tablename__ = "extracted_records"
    __table_args__ = (UniqueConstraint("batch_id", "raw_record_id", name="uq_extracted_batch_raw"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("extracted"))
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    raw_record_id: Mapped[str] = mapped_column(String(64), index=True)
    parser_name: Mapped[str] = mapped_column(String(80), default="")
    parser_version: Mapped[str] = mapped_column(String(40), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class NormalizedRecord(Base, TimestampMixin):
    __tablename__ = "normalized_records"
    __table_args__ = (UniqueConstraint("batch_id", "raw_record_id", name="uq_normalized_batch_raw"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("normalized"))
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    raw_record_id: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    linker_version: Mapped[str] = mapped_column(String(40), default="")


class EntityLink(Base, TimestampMixin):
    __tablename__ = "entity_links"
    __table_args__ = (UniqueConstraint(
        "batch_id", "raw_record_id", "entity_type", "normalized_surface_form",
        name="uq_entity_links_batch_raw_type_surface",
    ),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("entity_link"))
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    raw_record_id: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    surface_form: Mapped[str] = mapped_column(String(500))
    normalized_surface_form: Mapped[str] = mapped_column(String(500))
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), index=True)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    entity_origin: Mapped[str] = mapped_column(String(24), default="asset")
    linker_version: Mapped[str] = mapped_column(String(40), default="")


class FeatureSnapshot(Base, TimestampMixin):
    __tablename__ = "feature_snapshots"
    __table_args__ = (UniqueConstraint("period_key", "granularity", "cohort_key", name="uq_feature_snapshots_period_cohort"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("feature"))
    period_key: Mapped[str] = mapped_column(String(32), index=True)
    granularity: Mapped[str] = mapped_column(String(16), default="month")
    cohort_key: Mapped[str] = mapped_column(String(255), index=True)
    cohort_basis: Mapped[str] = mapped_column(String(16), default="title")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_version: Mapped[str] = mapped_column(String(40), default="feature-v1")


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("signal_type", "cohort_key", "period_key", "granularity", name="uq_signals_type_cohort_period"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("sig"))
    signal_type: Mapped[str] = mapped_column(String(40), index=True)
    cohort_key: Mapped[str] = mapped_column(String(255), index=True)
    period_key: Mapped[str] = mapped_column(String(32), index=True)
    granularity: Mapped[str] = mapped_column(String(16), default="month")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    suppression_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    signal_version: Mapped[str] = mapped_column(String(40), default="signal-v1")


class ProcessingTask(Base, TimestampMixin):
    __tablename__ = "processing_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("task"))
    task_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    progress: Mapped[int] = mapped_column(default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class ResumeProfile(Base, TimestampMixin):
    __tablename__ = "resume_profiles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("resume"))
    user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_path: Mapped[str] = mapped_column(Text, default="")
    education: Mapped[str] = mapped_column(String(80), default="")
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    certificates: Mapped[list] = mapped_column(JSON, default=list)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class UserWorkspaceProfile(Base, TimestampMixin):
    __tablename__ = "user_workspace_profiles"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audience: Mapped[str] = mapped_column(String(24), default="seeker")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    hr_evaluation_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    work_style_assessment: Mapped[dict] = mapped_column(JSON, default=dict)


class FavoriteJob(Base, TimestampMixin):
    __tablename__ = "favorite_jobs"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_favorite_jobs_user_role"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("favorite"))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(80), index=True)
    role_name: Mapped[str] = mapped_column(String(255))
    role_field: Mapped[str] = mapped_column(String(255), default="")


class ResumeSkill(Base, TimestampMixin):
    __tablename__ = "resume_skills"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("rskill"))
    resume_id: Mapped[str] = mapped_column(String(64), index=True)
    skill_id: Mapped[str] = mapped_column(String(80), default="")
    skill_name: Mapped[str] = mapped_column(String(160))
    evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class MatchReport(Base, TimestampMixin):
    __tablename__ = "match_reports"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("match"))
    resume_id: Mapped[str] = mapped_column(String(64), default="")
    role_id: Mapped[str] = mapped_column(String(80), index=True)
    role_name: Mapped[str] = mapped_column(String(255))
    score: Mapped[float] = mapped_column(Float)
    result: Mapped[dict] = mapped_column(JSON)
    algorithm_version: Mapped[str] = mapped_column(String(40), default="match-v1")


class TalentAssessmentBatch(Base, TimestampMixin):
    __tablename__ = "talent_assessment_batches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("talent_batch"))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(80), index=True)
    role_name: Mapped[str] = mapped_column(String(255), default="")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="running")


class TalentAssessmentCandidate(Base, TimestampMixin):
    __tablename__ = "talent_assessment_candidates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("talent_candidate"))
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    candidate_code: Mapped[str] = mapped_column(String(32))
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    resume_id: Mapped[str] = mapped_column(String(64), default="")
    match_report_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="completed")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class LearningPath(Base, TimestampMixin):
    __tablename__ = "learning_paths"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("path"))
    match_report_id: Mapped[str] = mapped_column(String(64), index=True)
    stages: Mapped[list] = mapped_column(JSON, default=list)


class RoleDefinitionDraft(Base, TimestampMixin):
    __tablename__ = "role_definition_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("draft"))
    role_id: Mapped[str] = mapped_column(String(80), default="")
    role_name: Mapped[str] = mapped_column(String(255))
    candidate_type: Mapped[str] = mapped_column(String(40), default="new_role")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    # M4 lineage fields. Legacy seed rows retain their defaults; pipeline
    # generated candidates populate all three fields explicitly.
    origin: Mapped[str] = mapped_column(String(24), default="legacy", index=True)
    batch_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    evidence_grade: Mapped[str] = mapped_column(String(32), default="legacy")


class ReviewAction(Base, TimestampMixin):
    __tablename__ = "review_actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("review"))
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")


class ReviewComment(Base, TimestampMixin):
    __tablename__ = "review_comments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("comment"))
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(24), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[str] = mapped_column(String(64), default="")


class RoleDefinitionVersion(Base, TimestampMixin):
    __tablename__ = "role_definition_versions"
    __table_args__ = (UniqueConstraint("version_id", name="uq_role_definition_versions_version_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("version"))
    version_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    role_name: Mapped[str] = mapped_column(String(255), default="")
    candidate_type: Mapped[str] = mapped_column(String(40), default="new_role")
    status: Mapped[str] = mapped_column(String(24), default="approved", index=True)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(24), default="legacy", index=True)
    batch_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    evidence_grade: Mapped[str] = mapped_column(String(32), default="legacy")
    publish_result: Mapped[dict] = mapped_column(JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PublishTask(Base, TimestampMixin):
    __tablename__ = "publish_tasks"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_publish_tasks_idempotency_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("publish_task"))
    idempotency_key: Mapped[str] = mapped_column(String(160), index=True)
    version_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InterviewSession(Base, TimestampMixin):
    __tablename__ = "interview_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("itv"))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(80), index=True)
    role_name: Mapped[str] = mapped_column(String(255), default="")
    resume_id: Mapped[str] = mapped_column(String(64), default="")
    self_intro: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="in_progress")
    questions: Mapped[list] = mapped_column(JSON, default=list)
    current_index: Mapped[int] = mapped_column(default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("agent"))
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("msg"))
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("eval"))
    suite: Mapped[str] = mapped_column(String(80))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uid("audit"))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(80), default="")
    target_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
