"""Durable first-stage ingest primitives shared by all submission channels."""

import hashlib
import io
import json
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import PipelineBatch, PipelineStageLog, RawRecord, uid


FIELD_ALIASES = {
    "source_record_id": ("source_record_id", "record_id", "recordId", "id"),
    "title": ("title", "job_title", "job_title_canonical", "title_canonical", "role_name", "roleName", "职位名称", "岗位名称", "标题"),
    "content": ("content", "description", "description_clean", "requirements", "raw_text", "jd_text", "jdText", "正文", "岗位内容", "职位描述", "工作内容"),
    "source_canonical": ("source_canonical", "source_canonical_final", "source", "source_name", "sourceName", "platform", "source_platform"),
    "company_name": ("company_name", "company", "companyName", "企业名称", "公司名称"),
    "node_type": ("node_type", "entity_type", "label", "类型"),
    "city": ("city", "city_canonical", "location", "城市"),
    "salary": ("salary", "salary_raw", "salary_range", "薪资"),
}

NODE_PRIMARY_KEYS = {
    "JobPosting": ("record_id",),
    "JobRole": ("role_id",),
    "Skill": ("skill_id",),
    "Certificate": ("certificate_id",),
    "Course": ("course_id",),
    "Major": ("major_id",),
    "OccupationStandard": ("standard_id",),
    "Requirement": ("requirement_id",),
    "TrendReport": ("document_id",),
    "TrendSignal": ("signal_id",),
    "TrendTopic": ("topic_id",),
    "SkillDemandSnapshot": ("snapshot_id",),
    "TimePeriod": ("time_id",),
}

NODE_TYPE_ALIASES = {
    "JobPosting": ("jobposting", "job_posting", "招聘记录", "岗位记录"),
    "JobRole": ("jobrole", "job_role", "岗位", "职能"),
    "Skill": ("skill", "技能"),
    "Certificate": ("certificate", "证书"),
    "Course": ("course", "课程"),
    "Major": ("major", "专业"),
    "OccupationStandard": ("occupationstandard", "standard", "职业标准"),
    "Requirement": ("requirement", "职业要求"),
    "TrendReport": ("trendreport", "趋势报告"),
    "TrendSignal": ("trendsignal", "趋势信号"),
    "TrendTopic": ("trendtopic", "趋势主题"),
    "SkillDemandSnapshot": ("skilldemandsnapshot", "技能需求快照"),
    "TimePeriod": ("timeperiod", "时间周期"),
}

NODE_TYPE_HIT_COLUMNS = {
    "JobPosting": ("job_title", "job_title_canonical", "company_name", "source_url", "description", "description_clean", "requirements_clean"),
    "JobRole": ("role_name", "role_family", "role_id"),
    "Skill": ("skill_name", "skill_id", "aliases_canonical", "proficiency_level"),
    "Certificate": ("certificate_id", "issuer_canonical", "assessed_skills_clean"),
    "Course": ("course_id", "provider_canonical", "objectives_clean", "learning_outcomes_clean"),
    "Major": ("major_id", "major_code", "discipline_code"),
    "OccupationStandard": ("standard_id", "occupation_code", "definition_canonical"),
    "Requirement": ("requirement_id", "requirement_type", "skill_keywords_canonical"),
    "TrendReport": ("document_id", "report_title", "publisher"),
    "TrendSignal": ("signal_id", "signal_type", "signal_name"),
    "TrendTopic": ("topic_id", "topic_name", "topic_type"),
    "SkillDemandSnapshot": ("snapshot_id", "demand_value", "period_key"),
    "TimePeriod": ("time_id", "period_key", "period_start"),
}


def _normalized_key(value: str) -> str:
    return re.sub(r"[\s_\-]", "", value).casefold()


def _field(row: dict, name: str) -> str:
    by_normalized = {_normalized_key(str(key)): value for key, value in row.items()}
    for alias in FIELD_ALIASES[name]:
        value = by_normalized.get(_normalized_key(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_node_type(row: dict) -> str:
    explicit = _field(row, "node_type")
    if explicit:
        normalized = _normalized_key(explicit)
        for node_type, aliases in NODE_TYPE_ALIASES.items():
            if normalized in {_normalized_key(item) for item in (node_type, *aliases)}:
                return node_type
        raise HTTPException(422, f"无法解析 node_type：{explicit}")

    keys = {_normalized_key(str(key)) for key, value in row.items() if value is not None and str(value).strip()}
    unique_matches = [node_type for node_type, ids in NODE_PRIMARY_KEYS.items() if any(_normalized_key(item) in keys for item in ids)]
    if len(unique_matches) == 1:
        return unique_matches[0]

    scored = []
    for node_type, ids in NODE_PRIMARY_KEYS.items():
        score = sum(_normalized_key(item) in keys for item in (*ids, *NODE_TYPE_HIT_COLUMNS[node_type]))
        if score:
            scored.append((score, node_type))
    if not scored:
        raise HTTPException(422, "無法解析记录节点类型")
    best = max(score for score, _ in scored)
    winners = [node_type for score, node_type in scored if score == best]
    if len(winners) != 1:
        raise HTTPException(422, "记录节点类型判定并列，请补充 node_type")
    return winners[0]


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _split_txt(text: str) -> tuple[list[tuple[str, int, int]], str]:
    lines = text.splitlines()
    separators = [index for index, line in enumerate(lines) if re.fullmatch(r"\s*(?:={4,}|-{4,}|_{4,}|\*{4,})\s*", line)]
    if separators:
        groups, start = [], 0
        for separator in separators:
            groups.append(("\n".join(lines[start:separator]).strip(), start + 1, separator))
            start = separator + 1
        groups.append(("\n".join(lines[start:]).strip(), start + 1, len(lines)))
        return groups, "explicit_separator"
    if any(not line.strip() for line in lines):
        groups, start = [], 0
        for index, line in enumerate(lines):
            if not line.strip():
                if any(item.strip() for item in lines[start:index]):
                    groups.append(("\n".join(lines[start:index]).strip(), start + 1, index))
                start = index + 1
        if any(item.strip() for item in lines[start:]):
            groups.append(("\n".join(lines[start:]).strip(), start + 1, len(lines)))
        return groups, "blank_line"
    return [(text.strip(), 1, len(lines))], "whole_file"


def read_upload(filename: str, payload: bytes, dataset_name: str = "") -> tuple[list[dict], dict]:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".json", ".xlsx", ".xls", ".txt"}:
        raise HTTPException(422, "无法解析：仅支持 CSV、JSON、Excel 或 TXT")
    try:
        if suffix == ".csv":
            import csv

            rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
            metadata = {"adapter": "csv"}
        elif suffix == ".json":
            value = json.loads(payload.decode("utf-8-sig"))
            rows = value if isinstance(value, list) else value.get("records", [value]) if isinstance(value, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("JSON 顶层必须是对象或对象数组")
            metadata = {"adapter": "json"}
        elif suffix in {".xlsx", ".xls"}:
            import pandas as pd

            frame = pd.read_excel(io.BytesIO(payload), dtype=str)
            rows = frame.where(frame.notna(), "").to_dict(orient="records")
            metadata = {"adapter": "excel"}
        else:
            text = payload.decode("utf-8-sig")
            chunks, strategy = _split_txt(text)
            rows = []
            for content, start, end in chunks:
                title_match = re.search(r"(?:职位名称|岗位名称|职位|岗位|标题)\s*[:：]\s*(.+)", content)
                rows.append({
                    "content": content,
                    "title": title_match.group(1).strip() if title_match else "",
                    "node_type": "JobPosting",
                    "__short_content_reject": len(content) < 20,
                    "__locator": {"lineStart": start, "lineEnd": end},
                })
            metadata = {"adapter": "txt", "split_strategy": strategy}
        if suffix != ".txt":
            for index, row in enumerate(rows, start=2 if suffix in {".csv", ".xlsx", ".xls"} else 0):
                row["__locator"] = {"rowNumber": index} if suffix in {".csv", ".xlsx", ".xls"} else {"recordIndex": index}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"无法解析上传文件：{exc}") from exc
    if not rows:
        raise HTTPException(422, "无法解析上传文件：没有可接入的数据记录")
    return rows, metadata


def add_raw_record(db: Session, batch: PipelineBatch, incoming: dict, *, locator: dict | None = None,
                   source_inferred_from: str = "", default_source: str = "") -> tuple[RawRecord | None, str]:
    payload = {str(key): value for key, value in incoming.items() if not str(key).startswith("__")}
    content = _field(payload, "content")
    if not content:
        raise HTTPException(422, "记录内容缺失")
    if len(content) < 20:
        return None, "rejected_content"
    try:
        node_type = normalize_node_type(payload)
    except HTTPException:
        # The canonical posting export is not a graph-node export, but its fields
        # are a fixed, explicit JobPosting schema.
        keys = {_normalized_key(str(key)) for key in payload}
        if {"recordid", "jobtitle", "companyname"}.issubset(keys) and ("description" in keys or "descriptionclean" in keys):
            node_type = "JobPosting"
        else:
            raise
    title = _field(payload, "title")
    source = _field(payload, "source_canonical")
    company = _field(payload, "company_name")
    metadata = {}
    if not source and source_inferred_from:
        metadata["source_inferred_from"] = source_inferred_from
    if not company and default_source:
        metadata["company_inferred_from"] = source_inferred_from or "entrypoint"
    if not title:
        metadata["title_inference_pending"] = True
    source_record_id = _field(payload, "source_record_id")
    if source_record_id:
        existing = db.query(RawRecord).filter_by(batch_id=batch.id, source_record_id=source_record_id).first()
        if existing:
            return existing, "duplicate_idempotent"
    raw = RawRecord(
        id=uid("raw"), batch_id=batch.id, source_record_id=source_record_id, node_type=node_type,
        source_canonical=source or default_source, company_name=company or default_source, title=title, content=content,
        raw_payload=payload, source_locator=locator or incoming.get("__locator", {}), metadata_json=metadata,
        content_sha256=_hash_content(content),
    )
    db.add(raw)
    db.flush()
    prior = db.query(RawRecord).filter(
        RawRecord.id != raw.id,
        RawRecord.content_sha256 == raw.content_sha256,
        RawRecord.company_name == raw.company_name,
        RawRecord.title == raw.title,
    ).order_by(RawRecord.created_at.asc()).first()
    if prior:
        raw.duplicate_of = prior.duplicate_of or prior.id
        raw.observation_count = 0
        raw.metadata_json["duplicate_observation"] = True
        prior.duplicate_count = (prior.duplicate_count or 0) + 1
    return raw, "accepted"


def finish_ingest(db: Session, batch: PipelineBatch, counts: dict) -> None:
    batch.statistics = counts
    batch.status = "received"
    batch.stage = "ingest"
    db.add(PipelineStageLog(batch_id=batch.id, stage="ingest", status="completed", statistics=counts))

