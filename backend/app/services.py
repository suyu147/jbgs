import csv
from datetime import date, datetime
import hashlib
import json
import math
import re
import statistics
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import APP_DATA_ROOT, EXAMPLE_ROOT, settings
from .models import (
    AuditLog,
    DatasetRegistry,
    DatasetRevision,
    LearningPath,
    MatchReport,
    ProcessingTask,
    RoleDefinitionDraft,
)
from .neo4j_client import neo4j


_AGENT_RESPONSE_CACHE: dict[str, tuple[float, str, str]] = {}
_AGENT_CACHE_LOCK = threading.Lock()
_AGENT_CACHE_TTL_SECONDS = 300
_AGENT_CACHE_MAX_ITEMS = 48
_FORECAST_QUERY_CACHE: dict[str, tuple[float, list[dict]]] = {}
_FORECAST_QUERY_CACHE_LOCK = threading.Lock()
_FORECAST_QUERY_CACHE_TTL_SECONDS = 30


class AgentProviderError(ValueError):
    def __init__(self, reason: str = "provider_unavailable"):
        super().__init__(reason)
        self.reason = reason


def coze_failure_reason(item: dict) -> str:
    nested = item.get("data") if isinstance(item.get("data"), dict) else {}
    last_error = item.get("last_error") if isinstance(item.get("last_error"), dict) else nested.get("last_error", {})
    code = str(last_error.get("code") or "") if isinstance(last_error, dict) else ""
    if code == "4028":
        return "insufficient_credits"
    if code in {"401", "4010", "4011", "4100", "4101"}:
        return "authentication_failed"
    if code in {"429", "4290", "4291"}:
        return "rate_limited"
    return "provider_unavailable"


def _forecast_query(statement: str, parameters: dict[str, Any] | None = None) -> list[dict]:
    """Reuse immutable graph aggregates across scenario and horizon switches."""
    normalized_parameters = parameters or {}
    key = hashlib.sha256(
        (statement + json.dumps(normalized_parameters, ensure_ascii=False, sort_keys=True)).encode("utf-8")
    ).hexdigest()
    now = time.monotonic()
    with _FORECAST_QUERY_CACHE_LOCK:
        cached = _FORECAST_QUERY_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    rows = neo4j.query(statement, normalized_parameters)
    with _FORECAST_QUERY_CACHE_LOCK:
        _FORECAST_QUERY_CACHE[key] = (now + _FORECAST_QUERY_CACHE_TTL_SECONDS, rows)
        if len(_FORECAST_QUERY_CACHE) > 64:
            expired = [cache_key for cache_key, value in _FORECAST_QUERY_CACHE.items() if value[0] <= now]
            for cache_key in expired or list(_FORECAST_QUERY_CACHE)[:16]:
                _FORECAST_QUERY_CACHE.pop(cache_key, None)
    return rows


def _agent_cache_key(prompt: str, context: dict, agent_mode: str, conversation_id: str) -> str:
    payload = {
        "mode": agent_mode,
        "conversationId": conversation_id or "",
        "prompt": prompt.strip(),
        # Role and prompt identify a short-lived answer cache. Do not include
        # the full evidence payload: snapshot ordering can change between two
        # requests even when the user's question is identical.
        "roleId": str(context.get("roleId") or context.get("id") or ""),
        "roleName": str(context.get("roleName") or context.get("name") or ""),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _cached_agent_response(key: str) -> tuple[str, str] | None:
    now = time.monotonic()
    with _AGENT_CACHE_LOCK:
        item = _AGENT_RESPONSE_CACHE.get(key)
        if not item:
            return None
        created, answer, conversation_id = item
        if now - created > _AGENT_CACHE_TTL_SECONDS:
            _AGENT_RESPONSE_CACHE.pop(key, None)
            return None
        return answer, conversation_id


def _store_agent_response(key: str, answer: str, conversation_id: str) -> None:
    with _AGENT_CACHE_LOCK:
        _AGENT_RESPONSE_CACHE[key] = (time.monotonic(), answer, conversation_id)
        if len(_AGENT_RESPONSE_CACHE) > _AGENT_CACHE_MAX_ITEMS:
            oldest = min(_AGENT_RESPONSE_CACHE, key=lambda cache_key: _AGENT_RESPONSE_CACHE[cache_key][0])
            _AGENT_RESPONSE_CACHE.pop(oldest, None)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        return max(sum(1 for _ in stream) - 1, 0)


GRAPH_NODE_SPECS = (
    ({"snapshot_id", "entity_name"}, "SkillDemandSnapshot", "snapshot_id"),
    ({"time_id", "entity_name"}, "TimePeriod", "time_id"),
    ({"role_id", "role_name"}, "JobRole", "role_id"),
    ({"record_id", "entity_name"}, "JobPosting", "record_id"),
    ({"skill_id", "entity_name"}, "Skill", "skill_id"),
    ({"certificate_id", "entity_name"}, "Certificate", "certificate_id"),
    ({"course_id", "entity_name"}, "Course", "course_id"),
    ({"major_id", "entity_name"}, "Major", "major_id"),
    ({"standard_id", "entity_name"}, "OccupationStandard", "standard_id"),
    ({"requirement_id", "entity_name"}, "Requirement", "requirement_id"),
    ({"document_id", "entity_name"}, "TrendReport", "document_id"),
    ({"signal_id", "entity_name"}, "TrendSignal", "signal_id"),
    ({"topic_id", "entity_name"}, "TrendTopic", "topic_id"),
)

GRAPH_RELATION_SPECS = {
    "MENTIONS_SKILL": ("JobPosting", "record_id", "Skill", "skill_id"),
    "IS_SUBSKILL_OF": ("Skill", "skill_id", "Skill", "skill_id"),
    "HAS_REQUIREMENT": ("OccupationStandard", "standard_id", "Requirement", "requirement_id"),
    "HAS_POSTING_PERIOD": ("JobRole", "role_id", "TimePeriod", "time_id"),
    "BELONGS_TO_MAJOR": ("Course", "course_id", "Major", "major_id"),
    "TEACHES_SKILL": ("Course", "course_id", "Skill", "skill_id"),
    "VALIDATES_SKILL": ("Certificate", "certificate_id", "Skill", "skill_id"),
    "HAS_TREND_SIGNAL": ("TrendReport", "document_id", "TrendSignal", "signal_id"),
    "INDICATES_TOPIC": ("TrendReport", "document_id", "TrendTopic", "topic_id"),
    "INDICATES_SKILL_TREND": ("TrendSignal", "signal_id", "Skill", "skill_id"),
    "INSTANCE_OF": ("JobPosting", "record_id", "JobRole", "role_id"),
    "REQUIRES_SKILL": ("JobRole", "role_id", "Skill", "skill_id"),
    "STANDARD_FOR": ("OccupationStandard", "standard_id", "JobRole", "role_id"),
    "MAPS_TO_SKILL": ("Requirement", "requirement_id", "Skill", "skill_id"),
}


def _graph_row_allowed(row: dict[str, str]) -> bool:
    review = str(row.get("review_status_final") or "approved").strip().lower()
    eligible = str(row.get("eligible_for_graph_final") or "true").strip().lower()
    return review in {"approved", "正式", "通过"} and eligible in {"true", "1", "yes", "是"}


def _clean_graph_properties(row: dict[str, str]) -> dict[str, str]:
    return {str(key): str(value) for key, value in row.items() if key and value not in (None, "") and not str(key).startswith("__")}


def _batches(rows: list[dict], size: int = 250):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def sync_dataset_to_graph(dataset: DatasetRegistry, path: Path, include_content: bool = True) -> dict:
    """Mirror registry metadata and idempotently upsert supported formal CSV graph assets."""
    neo4j.query(
        "MERGE (d:DatasetAsset {dataset_id:$id}) SET d.name=$name,d.category=$category,d.path=$path," 
        "d.record_count=$records,d.version=$version,d.usage_boundary=$boundary,d.sha256=$sha256,d.updated_at=datetime()",
        {
            "id": dataset.id,
            "name": dataset.name,
            "category": dataset.category,
            "path": dataset.path,
            "records": int(dataset.record_count or 0),
            "version": dataset.version,
            "boundary": dataset.usage_boundary,
            "sha256": dataset.sha256,
        },
    )
    result = {
        "mode": "metadata_only",
        "schema": "",
        "rowsRead": 0,
        "rowsAccepted": 0,
        "nodesMerged": 0,
        "relationsMerged": 0,
        "message": "资产登记信息已同步到 Neo4j",
    }
    if not include_content:
        return result
    if dataset.usage_boundary != "formal":
        result["message"] = "复核数据仅同步资产元数据，不进入正式业务图谱"
        return result
    if path.suffix.lower() != ".csv":
        result["message"] = "当前文件不是 CSV，仅同步资产元数据"
        return result

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = set(reader.fieldnames or [])
        node_spec = next((item for item in GRAPH_NODE_SPECS if item[0].issubset(headers)), None)
        rows = [row for row in reader]
    result["rowsRead"] = len(rows)
    accepted = [row for row in rows if _graph_row_allowed(row)]
    result["rowsAccepted"] = len(accepted)

    if node_spec:
        _, label, key = node_spec
        prepared = [
            {"key": row.get(key, ""), "props": _clean_graph_properties(row)}
            for row in accepted if row.get(key)
        ]
        for batch in _batches(prepared):
            merged = neo4j.scalar(
                f"UNWIND $rows AS row MERGE (n:{label} {{{key}:row.key}}) "
                "SET n += row.props,n.dataset_id=$dataset_id,n.dataset_version=$version,n.asset_updated_at=datetime() "
                "RETURN count(n)",
                {"rows": batch, "dataset_id": dataset.id, "version": dataset.version},
            )
            result["nodesMerged"] += int(merged or 0)
        result["mode"] = "graph_upsert"
        result["schema"] = label

    relation_groups: dict[str, list[dict]] = defaultdict(list)
    for row in accepted:
        relation_type = str(row.get("relationship_type") or "").strip().upper()
        if relation_type in GRAPH_RELATION_SPECS and row.get("from_id") and row.get("to_id"):
            relation_groups[relation_type].append(
                {
                    "from": row["from_id"],
                    "to": row["to_id"],
                    "edge": row.get("edge_id") or hashlib.sha1(
                        f"{relation_type}|{row['from_id']}|{row['to_id']}".encode("utf-8")
                    ).hexdigest(),
                    "props": _clean_graph_properties(row),
                }
            )
    for relation_type, relation_rows in relation_groups.items():
        from_label, from_key, to_label, to_key = GRAPH_RELATION_SPECS[relation_type]
        for batch in _batches(relation_rows):
            merged = neo4j.scalar(
                f"UNWIND $rows AS row MATCH (a:{from_label} {{{from_key}:row.from}}) "
                f"MATCH (b:{to_label} {{{to_key}:row.to}}) "
                f"MERGE (a)-[rel:{relation_type} {{edge_id:row.edge}}]->(b) "
                "SET rel += row.props,rel.dataset_id=$dataset_id,rel.dataset_version=$version,rel.asset_updated_at=datetime() "
                "RETURN count(rel)",
                {"rows": batch, "dataset_id": dataset.id, "version": dataset.version},
            )
            result["relationsMerged"] += int(merged or 0)
        result["mode"] = "graph_upsert"
        result["schema"] = result["schema"] or "+".join(sorted(relation_groups))

    if {"snapshot_id", "role_id", "skill_id"}.issubset(headers):
        snapshot_rows = [
            {"snapshot": row["snapshot_id"], "role": row["role_id"], "skill": row["skill_id"]}
            for row in accepted if row.get("snapshot_id") and row.get("role_id") and row.get("skill_id")
        ]
        for batch in _batches(snapshot_rows):
            merged = neo4j.scalar(
                "UNWIND $rows AS row MATCH (r:JobRole {role_id:row.role}) "
                "MATCH (snap:SkillDemandSnapshot {snapshot_id:row.snapshot}) MATCH (s:Skill {skill_id:row.skill}) "
                "MERGE (r)-[:HAS_DEMAND_SNAPSHOT]->(snap) MERGE (snap)-[:FOR_SKILL]->(s) RETURN count(snap)",
                {"rows": batch},
            )
            result["relationsMerged"] += int(merged or 0) * 2
        result["mode"] = "graph_upsert"
        result["schema"] = "SkillDemandSnapshot"

    if not node_spec and not relation_groups and "snapshot_id" not in headers:
        result["message"] = "CSV 结构未匹配受支持的图谱资产，仅同步资产元数据"
    else:
        result["message"] = "正式数据已按业务主键幂等合并到 Neo4j"
    return result


def seed_datasets(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(DatasetRegistry)):
        return
    roots = [EXAMPLE_ROOT / "各类所需数据", EXAMPLE_ROOT / "知识图谱"]
    for root in roots:
        for path in root.rglob("*.csv"):
            relative = path.relative_to(EXAMPLE_ROOT)
            usage = "review" if "待复核" in str(relative) else "formal"
            db.add(
                DatasetRegistry(
                    id=f"dataset_{hashlib.sha1(str(relative).encode('utf-8')).hexdigest()[:16]}",
                    name=path.stem,
                    category=path.parent.name,
                    path=str(relative),
                    record_count=count_csv_rows(path),
                    version="20260801-v01" if "知识图谱" in str(relative) else "20260720-v01",
                    usage_boundary=usage,
                    sha256=file_sha256(path),
                )
            )
    db.commit()


def _clean_responsibility(text: str) -> str:
    item = re.sub(r"^(?:岗位职责|工作职责|职位描述|职位介绍)\s*[:：]?\s*", "", text).strip()
    item = re.sub(r"^\s*(?:\d+[.、)）]|[（(]?\d+[）)])\s*", "", item).strip(" ：:，,。；;")
    return item[:180]


def build_new_role_definition(candidate: dict, postings: list[dict], skill_rows: list[dict]) -> tuple[dict, list[dict]]:
    record_ids = {item.get("record_id", "") for item in postings}
    responsibilities: list[str] = []
    seen_responsibilities: set[str] = set()
    for posting in postings:
        text = posting.get("description_clean") or posting.get("description") or ""
        for sentence in re.split(r"[。；;\n]", text):
            cleaned = _clean_responsibility(sentence)
            if len(cleaned) < 8 or not any(word in cleaned for word in ("负责", "参与", "主导", "建设", "设计", "开发", "维护", "推动")):
                continue
            key = re.sub(r"\s+", "", cleaned).lower()
            if key not in seen_responsibilities:
                seen_responsibilities.add(key)
                responsibilities.append(cleaned)
            if len(responsibilities) >= 6:
                break
        if len(responsibilities) >= 6:
            break

    skills: dict[str, dict] = {}
    skill_records: dict[str, set[str]] = defaultdict(set)
    for item in skill_rows:
        record_id = item.get("record_id", "")
        if record_id not in record_ids or str(item.get("eligible_for_graph_final", "true")).lower() != "true":
            continue
        skill_id = item.get("skill_id", "")
        if not skill_id:
            continue
        skill_records[skill_id].add(record_id)
        current = skills.setdefault(
            skill_id,
            {
                "skill_id": skill_id,
                "skill_name": item.get("skill_name", ""),
                "evidence": item.get("evidence_text_final") or item.get("evidence_text") or "",
            },
        )
        if not current["evidence"]:
            current["evidence"] = item.get("evidence_text_final") or item.get("evidence_text") or ""

    total_postings = max(len(record_ids), 1)
    ranked_skills = []
    for skill_id, item in skills.items():
        evidence_count = len(skill_records[skill_id])
        ranked_skills.append(
            {
                **item,
                "evidence_count": evidence_count,
                "posting_penetration": round(evidence_count / total_postings, 4),
            }
        )
    ranked_skills.sort(key=lambda item: (-item["evidence_count"], item["skill_name"]))
    required = [item for item in ranked_skills if item["posting_penetration"] >= 0.25][:6]
    if len(required) < min(3, len(ranked_skills)):
        required = ranked_skills[: min(5, len(ranked_skills))]
    required_ids = {item["skill_id"] for item in required}
    bonus = [item for item in ranked_skills if item["skill_id"] not in required_ids][:5]
    if not bonus and len(required) > 1:
        bonus_count = min(2, max(1, len(required) // 3))
        bonus = required[-bonus_count:]
        required = required[:-bonus_count]

    scenario_counter: Counter[tuple[str, str]] = Counter()
    for posting in postings:
        industry = (posting.get("industry") or "数字化产业").strip()
        category = (posting.get("job_category_canonical") or posting.get("job_category") or candidate.get("job_category", "")).strip()
        scenario_counter[(industry, category)] += 1
    scenarios = [
        {
            "scenario": f"{industry}行业中的{category or candidate.get('job_category', '岗位能力')}应用",
            "evidence_count": count,
        }
        for (industry, category), count in scenario_counter.most_common(4)
    ]

    evidence = [
        {
            "type": "job_posting",
            "recordId": item.get("record_id", ""),
            "source": item.get("source_canonical_final") or item.get("source", ""),
            "url": item.get("source_url", ""),
            "period": item.get("posted_month_canonical") or item.get("posted_date_canonical", ""),
            "excerpt": (item.get("description_clean") or item.get("requirements_clean") or "")[:220],
            "confidence": "source_record",
        }
        for item in postings[:8]
    ]
    definition = {
        "job_category": candidate.get("job_category", ""),
        "first_seen": candidate.get("first_seen_month", ""),
        "latest_seen": candidate.get("latest_seen_month", ""),
        "posting_count": int(candidate.get("posting_count") or len(postings)),
        "source_count": int(candidate.get("source_count") or len({item.get('source') for item in postings})),
        "candidate_reason": candidate.get("candidate_reason", ""),
        "core_responsibilities": responsibilities,
        "required_skills": required,
        "bonus_skills": bonus,
        "application_scenarios": scenarios,
        "definition_status": "human_review_required",
        "evidence_record_count": len(record_ids),
    }
    return definition, evidence


def _curated_review_candidates() -> list[dict]:
    """Governance demos stay pending and are explicitly separated from collected evidence."""
    def skills(*names: str) -> list[dict]:
        return [
            {
                "skill_id": "",
                "skill_name": name,
                "evidence": "公开职业能力资料与常见岗位职责的人工整理，待复核",
                "evidence_count": 0,
                "posting_penetration": 0,
            }
            for name in names
        ]

    def references(topic: str) -> list[dict]:
        return [
            {
                "type": "curated_reference",
                "source": "人力资源社会保障部公开资料",
                "url": "https://www.mohrss.gov.cn/",
                "period": "2026-08",
                "excerpt": f"围绕{topic}的职业分类、职责边界和能力要求进行人工归纳，供治理人员复核。",
                "confidence": "curated_demo",
            },
            {
                "type": "curated_reference",
                "source": "工业和信息化部公开资料",
                "url": "https://www.miit.gov.cn/",
                "period": "2026-08",
                "excerpt": f"结合数字产业与产业数字化公开信息整理{topic}的典型应用方向。",
                "confidence": "curated_demo",
            },
            {
                "type": "curated_reference",
                "source": "国家职业技能标准公开信息",
                "url": "http://biaozhun.osta.org.cn/",
                "period": "2026-08",
                "excerpt": f"参照相邻职业技能标准梳理{topic}的知识、技能和实践边界，需人工确认后使用。",
                "confidence": "curated_demo",
            },
        ]

    def role_definition(
        family: str,
        responsibilities: list[str],
        required: tuple[str, ...],
        bonus: tuple[str, ...],
        scenarios: tuple[str, ...],
        reason: str,
    ) -> dict:
        return {
            "job_category": family,
            "first_seen": "2025-01",
            "latest_seen": "2026-08",
            "source_count": 3,
            "candidate_reason": f"策划演示候选：{reason}；不是自动采集事实，须经人工复核后方可发布。",
            "core_responsibilities": responsibilities,
            "required_skills": skills(*required),
            "bonus_skills": skills(*bonus),
            "application_scenarios": [{"scenario": item, "evidence_count": 0} for item in scenarios],
            "definition_status": "human_review_required",
            "evidence_record_count": 3,
            "source_type": "curated_demo",
        }

    candidates = [
        {
            "role_name": "AI智能体应用工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "人工智能/软件工程",
                ["设计智能体任务流程与工具调用链路", "建设知识检索、评测与安全控制机制", "监控智能体运行质量并持续优化"],
                ("大语言模型", "智能体编排", "检索增强生成", "Python", "模型评测"),
                ("提示词工程", "MLOps", "数据安全"),
                ("企业知识助手", "业务流程自动化", "智能客服与运营协同"),
                "大模型工程化从单轮问答转向可执行工作流，职责边界与传统算法岗位不同",
            ),
        },
        {
            "role_name": "工业数据治理工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "智能制造/数据治理",
                ["建设工业数据标准、主数据与质量规则", "打通设备、生产与经营数据链路", "维护数据资产目录和血缘关系"],
                ("数据治理", "主数据管理", "数据质量", "工业互联网", "SQL"),
                ("知识图谱", "数据安全", "数据资产管理"),
                ("制造数据中台", "设备数据治理", "生产质量追溯"),
                "制造企业的数据资产治理逐渐形成独立于通用数据工程的岗位职责",
            ),
        },
        {
            "role_name": "智能制造数据工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "智能制造/数据工程",
                ["采集并治理产线与设备时序数据", "建设面向生产分析的数据模型", "支持设备预测维护和工艺优化"],
                ("数据工程", "时序数据", "工业协议", "Python", "数据建模"),
                ("数字孪生", "机器学习", "边缘计算"),
                ("预测性维护", "能耗分析", "工艺参数优化"),
                "工业现场数据接入与分析能力组合具有明确、稳定的应用边界",
            ),
        },
        {
            "role_name": "数据安全运营工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "网络安全/数据治理",
                ["识别数据资产及敏感数据分布", "运营数据访问审计与异常处置", "推动分类分级、脱敏和权限治理"],
                ("数据分类分级", "访问控制", "安全审计", "隐私保护", "风险评估"),
                ("数据防泄漏", "云安全", "合规治理"),
                ("数据安全运营中心", "敏感数据治理", "数据出境风险评估"),
                "数据安全从制度合规延伸到持续运营，能力组合区别于传统网络安全运维",
            ),
        },
        {
            "role_name": "大模型安全评测工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "人工智能/网络安全",
                ["设计大模型安全与可靠性评测方案", "建设对抗测试、内容安全和风险分级数据集", "跟踪模型风险并推动修复验证"],
                ("大语言模型", "模型评测", "内容安全", "对抗测试", "风险分析"),
                ("红队测试", "数据合规", "提示词工程"),
                ("生成式人工智能上线评审", "模型安全治理", "高风险场景专项测试"),
                "生成式人工智能应用需要独立的安全、可靠性和合规评测职责",
            ),
        },
        {
            "role_name": "具身智能数据工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "人工智能/机器人",
                ["建设机器人感知与动作数据采集流程", "完成多模态轨迹数据清洗、标注和质量评估", "支持具身模型训练与仿真验证"],
                ("多模态数据", "机器人技术", "数据工程", "Python", "仿真测试"),
                ("强化学习", "计算机视觉", "传感器融合"),
                ("工业机器人训练", "服务机器人交互", "仿真数据生成"),
                "机器人基础模型发展带来感知、动作和仿真数据一体化建设需求",
            ),
        },
        {
            "role_name": "工业视觉质检工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "智能制造/计算机视觉",
                ["设计制造缺陷视觉检测方案", "建设样本采集、标注和模型迭代闭环", "完成算法与产线设备的部署联调"],
                ("计算机视觉", "缺陷检测", "深度学习", "工业相机", "模型部署"),
                ("边缘计算", "光学成像", "MLOps"),
                ("外观缺陷检测", "装配质量检测", "产线异常识别"),
                "工业视觉正在形成兼顾算法、光学和产线交付的复合岗位边界",
            ),
        },
        {
            "role_name": "数字孪生运维工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "工业互联网/数字孪生",
                ["维护物理设备与数字模型的状态同步", "配置孪生场景、告警和运行规则", "分析模型偏差并优化运维策略"],
                ("数字孪生", "物联网", "时序数据", "设备运维", "数据可视化"),
                ("三维引擎", "预测性维护", "边缘计算"),
                ("园区设备运维", "生产线状态监控", "能源系统仿真"),
                "数字孪生平台投入运行后产生了模型维护、状态校准和业务运营职责",
            ),
        },
        {
            "role_name": "隐私计算解决方案工程师",
            "candidate_type": "new_role",
            "definition": role_definition(
                "数据安全/解决方案",
                ["分析跨机构数据协作中的安全与合规约束", "设计隐私计算技术方案并完成验证", "推动方案部署、性能调优和效果验收"],
                ("隐私计算", "数据安全", "密码学基础", "解决方案设计", "性能测试"),
                ("联邦学习", "可信执行环境", "数据要素流通"),
                ("金融联合风控", "医疗科研协作", "跨组织数据分析"),
                "数据协作场景需要同时理解安全技术、业务规则和工程交付的复合角色",
            ),
        },
        {
            "role_name": "碳数据治理专员",
            "candidate_type": "new_role",
            "definition": role_definition(
                "绿色低碳/数据治理",
                ["建立组织碳排放数据口径和采集规则", "核验能耗与排放活动数据质量", "支持碳盘查、核算和披露材料编制"],
                ("碳核算", "数据治理", "统计分析", "数据质量", "环境管理"),
                ("生命周期评价", "ESG披露", "能源管理"),
                ("企业碳盘查", "供应链碳数据管理", "园区能碳分析"),
                "双碳管理正在将分散的统计与环境职责整合为持续的数据治理岗位",
            ),
        },
        {
            "role_name": "低空飞行数据运营专员",
            "candidate_type": "new_role",
            "definition": role_definition(
                "低空经济/数据运营",
                ["维护低空飞行任务、航线与运行数据", "监控飞行运营指标并识别异常", "协同安全、调度和业务团队形成运营分析"],
                ("数据运营", "地理信息系统", "运行监控", "安全管理", "数据分析"),
                ("无人机系统", "空域管理", "可视化分析"),
                ("物流无人机运营", "低空巡检", "城市低空服务"),
                "低空应用规模化需要连接飞行运行、安全管理和数据分析的运营岗位",
            ),
        },
        {
            "role_id": "role_23453144f0f0efad",
            "role_name": "算法工程师",
            "candidate_type": "definition_update",
            "definition": role_definition(
                "人工智能/算法",
                ["训练、评估并部署机器学习模型", "构建可复现的数据与实验流程", "监控模型质量、成本与风险"],
                ("Python", "机器学习", "深度学习", "模型评测", "MLOps"),
                ("大语言模型", "分布式训练", "推理优化"),
                ("推荐与搜索", "视觉与语言模型", "企业智能应用"),
                "岗位能力已从单一模型开发扩展到评测、部署和持续运营",
            ),
        },
        {
            "role_id": "role_da9ced2540bde221",
            "role_name": "网络安全工程师",
            "candidate_type": "definition_update",
            "definition": role_definition(
                "网络安全",
                ["建设网络与云环境的安全防护体系", "开展风险监测、响应和复盘", "落实数据安全与合规控制"],
                ("网络安全", "安全运营", "漏洞管理", "云原生安全", "数据安全治理"),
                ("零信任", "容器安全", "威胁情报"),
                ("安全运营中心", "云平台防护", "数据安全治理"),
                "云原生与数据安全职责已成为既有网络安全岗位的重要组成部分",
            ),
        },
        {
            "role_id": "role_32f619c0fc80a1fc",
            "role_name": "数据分析师",
            "candidate_type": "definition_update",
            "definition": role_definition(
                "数据分析/商业分析",
                ["建设业务指标体系并监控经营表现", "设计分析方案并验证业务假设", "将分析结论转化为产品或运营动作"],
                ("SQL", "数据分析", "指标体系", "统计分析", "数据可视化"),
                ("实验分析", "Python", "数据产品"),
                ("经营分析", "用户增长分析", "产品决策支持"),
                "岗位由报表制作转向指标治理、实验验证和跨团队决策支持",
            ),
        },
        {
            "role_id": "role_1d5486b92522266c",
            "role_name": "嵌入式软件工程师",
            "candidate_type": "definition_update",
            "definition": role_definition(
                "嵌入式/物联网",
                ["设计并实现嵌入式软件模块", "完成软硬件联调、性能优化与故障定位", "保障实时性、可靠性和可维护性"],
                ("C/C++", "嵌入式系统", "实时操作系统", "驱动开发", "软件调试"),
                ("边缘计算", "功能安全", "Linux"),
                ("智能硬件", "工业控制", "车载电子"),
                "边缘计算、实时系统与功能安全正在重塑嵌入式岗位能力边界",
            ),
        },
        {
            "role_id": "role_38cf0d1bd6bc663f",
            "role_name": "软件测试工程师",
            "candidate_type": "definition_update",
            "definition": role_definition(
                "软件工程/质量保障",
                ["设计覆盖业务风险的测试策略", "建设自动化测试和持续质量反馈", "定位性能、稳定性与兼容性问题"],
                ("测试设计", "接口自动化", "性能测试", "持续集成", "缺陷分析"),
                ("安全测试", "测试开发", "可观测性"),
                ("持续交付质量门禁", "复杂系统回归", "线上质量监控"),
                "质量保障已从执行测试用例升级为自动化、性能和持续交付协同",
            ),
        },
    ]

    skill_changes = [
        (
            "role_c23f11f8576ccaf7",
            "运维工程师",
            "IT运维/云计算",
            [("Kubernetes", 4.8), ("自动化运维", 4.1), ("可观测性", 3.4), ("传统手工巡检", -3.2)],
        ),
        (
            "role_38cf0d1bd6bc663f",
            "软件测试工程师",
            "软件工程/质量保障",
            [("接口自动化", 4.5), ("性能测试", 3.7), ("CI/CD", 3.1), ("手工回归测试", -2.8)],
        ),
        (
            "role_da9ced2540bde221",
            "网络安全工程师",
            "网络安全",
            [("云原生安全", 4.2), ("数据安全治理", 3.8), ("安全运营", 3.3), ("单点边界防护", -2.4)],
        ),
    ]
    for role_id, role_name, family, changes in skill_changes:
        candidates.append(
            {
                "role_id": role_id,
                "role_name": role_name,
                "candidate_type": "skill_change",
                "definition": {
                    "job_category": family,
                    "first_seen": "2025-01",
                    "latest_seen": "2026-08",
                    "candidate_reason": "策划演示候选：基于公开技术演进方向整理，百分点为演示信号，须经人工复核。",
                    "changes": [
                        {
                            "skill_id": "",
                            "skill_name": name,
                            "change_type": "increase" if change > 0 else "decrease",
                            "change_pp": change,
                            "analysis_note": "该变化与岗位工具链和交付方式演进方向一致，仍需结合正式招聘证据确认。",
                        }
                        for name, change in changes
                    ],
                    "source_type": "curated_demo",
                },
            }
        )

    for candidate in candidates:
        candidate["evidence"] = references(candidate["role_name"])
    return candidates


def seed_candidates(db: Session) -> None:
    dynamic = EXAMPLE_ROOT / "各类所需数据" / "03_动态演示"
    new_roles = dynamic / "新兴岗位候选_动态演示.csv"
    changes = dynamic / "既有岗位技能变化候选_动态演示.csv"
    candidate_rows: list[dict] = []
    if new_roles.exists():
        with new_roles.open("r", encoding="utf-8-sig", newline="") as stream:
            candidate_rows = list(csv.DictReader(stream))

    candidate_titles = {item["job_title_canonical"] for item in candidate_rows}
    postings_by_title: dict[str, list[dict]] = defaultdict(list)
    posting_file = EXAMPLE_ROOT / "各类所需数据" / "01_标准化" / "第一类招聘数据_标准化.csv"
    if posting_file.exists():
        with posting_file.open("r", encoding="utf-8-sig", newline="") as stream:
            for posting in csv.DictReader(stream):
                title = posting.get("job_title_canonical", "")
                if title in candidate_titles and str(posting.get("eligible_for_graph", "true")).lower() == "true":
                    postings_by_title[title].append(posting)

    relevant_record_ids = {item.get("record_id", "") for rows in postings_by_title.values() for item in rows}
    skill_rows: list[dict] = []
    skill_file = EXAMPLE_ROOT / "各类所需数据" / "02_归一化" / "岗位技能关系_归一化.csv"
    if skill_file.exists():
        with skill_file.open("r", encoding="utf-8-sig", newline="") as stream:
            skill_rows = [item for item in csv.DictReader(stream) if item.get("record_id", "") in relevant_record_ids]

    existing = {
        (item.role_name, item.candidate_type): item
        for item in db.scalars(select(RoleDefinitionDraft)).all()
    }

    competition_path = (
        APP_DATA_ROOT
        / "quality"
        / "competition-evidence-20260825-v01"
        / "competition_evidence.json"
    )
    if competition_path.exists():
        competition = json.loads(competition_path.read_text(encoding="utf-8"))
        governed_candidates = [
            *(competition.get("newRoleCandidates") or []),
            *(competition.get("skillChangeCandidates") or []),
        ]
        for candidate in governed_candidates:
            key = (candidate["role_name"], candidate["candidate_type"])
            draft = existing.get(key)
            if draft:
                if draft.status == "pending":
                    draft.definition = candidate.get("definition") or draft.definition
                    draft.evidence = candidate.get("evidence") or draft.evidence
                continue
            draft = RoleDefinitionDraft(
                id="draft_evidence_" + hashlib.sha1(f"{key[0]}:{key[1]}".encode("utf-8")).hexdigest()[:16],
                role_name=candidate["role_name"],
                candidate_type=candidate["candidate_type"],
                definition=candidate.get("definition") or {},
                evidence=candidate.get("evidence") or [],
            )
            db.add(draft)
            existing[key] = draft
    for row in candidate_rows:
        title = row["job_title_canonical"]
        definition, evidence = build_new_role_definition(row, postings_by_title[title], skill_rows)
        draft = existing.get((title, "new_role"))
        if draft:
            if draft.status == "pending":
                draft.definition = {**draft.definition, **definition}
                draft.evidence = evidence or draft.evidence
        else:
            db.add(
                    RoleDefinitionDraft(
                        role_name=title,
                        candidate_type="new_role",
                        definition=definition,
                        evidence=evidence or [{"type": "candidate_file", "period": row["latest_seen_month"]}],
                    )
                )
    grouped: dict[str, list[dict]] = {}
    if changes.exists():
        with changes.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                grouped.setdefault(row["job_title_canonical"], []).append(
                    {
                        "skill_id": row["skill_id"],
                        "skill_name": row["skill_name"],
                        "change_type": row["change_type"],
                        "change_pp": float(row["penetration_change_pp"]),
                        "analysis_note": row["analysis_note"],
                    }
                )
    for role_name, items in grouped.items():
        key = (role_name, "skill_change")
        if key not in existing:
            draft = RoleDefinitionDraft(
                role_name=role_name,
                candidate_type="skill_change",
                definition={"changes": items},
                evidence=[{"type": "evolution", "period": "2025-2026"}],
            )
            db.add(draft)
            existing[key] = draft
    for candidate in _curated_review_candidates():
        key = (candidate["role_name"], candidate["candidate_type"])
        if key in existing:
            continue
        draft_id = "draft_curated_" + hashlib.sha1(f"{key[0]}:{key[1]}".encode("utf-8")).hexdigest()[:16]
        db.add(
            RoleDefinitionDraft(
                id=draft_id,
                role_id=candidate.get("role_id", ""),
                role_name=candidate["role_name"],
                candidate_type=candidate["candidate_type"],
                definition=candidate["definition"],
                evidence=candidate["evidence"],
            )
        )
    db.commit()


def overview(db: Session) -> dict:
    counts = neo4j.query(
        "MATCH (n) WITH count(n) AS nodes "
        "MATCH ()-[r]->() RETURN nodes, count(r) AS relationships"
    )[0]
    labels = neo4j.query(
        "CALL db.labels() YIELD label CALL (label) { WITH label MATCH (n) "
        "WHERE label IN labels(n) RETURN count(n) AS count } RETURN label,count"
    )
    by_label = {item["label"]: item["count"] for item in labels}
    candidates = db.scalar(
        select(func.count()).select_from(RoleDefinitionDraft).where(RoleDefinitionDraft.status == "pending")
    )
    datasets = db.scalar(select(func.count()).select_from(DatasetRegistry))
    reports = db.scalar(select(func.count()).select_from(MatchReport))
    return {
        "jobCount": by_label.get("JobRole", by_label.get("Job", 0)),
        "postingCount": by_label.get("JobPosting", by_label.get("Job", 0)),
        "skillCount": by_label.get("Skill", 0),
        "snapshotCount": by_label.get("SkillDemandSnapshot", 0),
        "timePeriodCount": by_label.get("TimePeriod", 0),
        "relationCount": counts["relationships"],
        "nodeCount": counts["nodes"],
        "datasetCount": datasets or 0,
        "pendingReviewCount": candidates or 0,
        "reportCount": reports or 0,
        "updatedAt": "2026-08-14T00:00:00+08:00",
        "governanceVersion": "20260814-v01",
        "graphVersion": "neo4j-20260814-v01",
    }


def admin_dashboard(db: Session, graph_summary: dict | None = None) -> dict:
    """Aggregate the read-only governance cockpit from the live graph and app database."""
    graph = graph_summary or overview(db)

    def grouped_counts(model, field) -> dict[str, int]:
        rows = db.execute(select(field, func.count()).select_from(model).group_by(field)).all()
        return {str(value or "unknown"): int(count or 0) for value, count in rows}

    draft_statuses = grouped_counts(RoleDefinitionDraft, RoleDefinitionDraft.status)
    candidate_types = grouped_counts(RoleDefinitionDraft, RoleDefinitionDraft.candidate_type)
    dataset_boundaries = grouped_counts(DatasetRegistry, DatasetRegistry.usage_boundary)
    revision_statuses = grouped_counts(DatasetRevision, DatasetRevision.sync_status)
    task_statuses = grouped_counts(ProcessingTask, ProcessingTask.status)

    versions = neo4j.query(
        "MATCH (v:RoleDefinitionVersion) "
        "RETURN coalesce(v.status,'unknown') AS status,count(v) AS count ORDER BY status"
    )
    version_statuses = {str(item.get("status") or "unknown"): int(item.get("count") or 0) for item in versions}

    entity_labels = [
        "Certificate", "Course", "Major", "OccupationStandard", "Requirement",
        "TrendReport", "TrendSignal", "TrendTopic", "TimePeriod",
    ]
    entity_rows = neo4j.query(
        "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) "
        "UNWIND labels(n) AS label WITH label,count(*) AS count "
        "WHERE label IN $labels RETURN label,count ORDER BY label",
        {"labels": entity_labels},
    )
    entity_counts = {str(item.get("label")): int(item.get("count") or 0) for item in entity_rows}

    monthly_evidence = neo4j.query(
        "MATCH (j:JobPosting) "
        "WHERE toString(j.posted_month_canonical) =~ '\\d{4}-\\d{2}' "
        "RETURN toString(j.posted_month_canonical) AS period,count(j) AS postingCount "
        "ORDER BY period"
    )
    locations = job_location_options()[:8]

    total_records = int(db.scalar(select(func.sum(DatasetRegistry.record_count))) or 0)
    latest_dataset_update = db.scalar(select(func.max(DatasetRegistry.updated_at)))
    recent_actions = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(8)).all()

    pending_reviews = int(draft_statuses.get("pending", 0))
    failed_syncs = int(revision_statuses.get("failed", 0))
    failed_tasks = int(task_statuses.get("failed", 0))
    review_datasets = int(dataset_boundaries.get("review", 0))
    risks = [
        {"key": "pendingReviews", "label": "待人工复核", "count": pending_reviews, "route": "/admin/reviews"},
        {"key": "failedSyncs", "label": "数据同步失败", "count": failed_syncs, "route": "/admin/data"},
        {"key": "failedTasks", "label": "处理任务失败", "count": failed_tasks, "route": "/admin/quality"},
        {"key": "reviewDatasets", "label": "复核数据集", "count": review_datasets, "route": "/admin/data"},
    ]

    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "governanceVersion": graph.get("governanceVersion", ""),
        "graphVersion": graph.get("graphVersion", ""),
        "graph": {
            **graph,
            "entityCounts": entity_counts,
        },
        "dataAssets": {
            "datasetCount": int(graph.get("datasetCount") or 0),
            "totalRecords": total_records,
            "boundaries": dataset_boundaries,
            "revisionStatuses": revision_statuses,
            "latestUpdatedAt": latest_dataset_update.isoformat() if latest_dataset_update else "",
        },
        "governance": {
            "draftStatuses": draft_statuses,
            "candidateTypes": candidate_types,
            "versionStatuses": version_statuses,
            "taskStatuses": task_statuses,
            "funnel": [
                {"key": "candidates", "label": "候选发现", "count": sum(draft_statuses.values()), "route": "/admin/reviews"},
                {"key": "pending", "label": "待复核", "count": pending_reviews, "route": "/admin/reviews"},
                {"key": "approved", "label": "已批准", "count": int(draft_statuses.get("approved", 0)), "route": "/admin/reviews"},
                {"key": "published", "label": "已发布", "count": int(version_statuses.get("published", 0)), "route": "/admin/reviews"},
                {"key": "withdrawn", "label": "已下架", "count": int(version_statuses.get("withdrawn", 0)), "route": "/admin/reviews"},
            ],
        },
        "monthlyEvidence": monthly_evidence,
        "locations": locations,
        "risks": risks,
        "recentActions": [
            {
                "id": item.id,
                "action": item.action,
                "targetType": item.target_type,
                "targetId": item.target_id,
                "detail": item.detail or {},
                "createdAt": item.created_at.isoformat() if item.created_at else "",
            }
            for item in recent_actions
        ],
        "system": {
            "api": True,
            "neo4j": True,
            "mysql": True,
            "agentProvider": settings.agent_provider,
            "agentConfigured": settings.agent_configured,
        },
    }


_SEARCH_SEPARATOR_RE = re.compile(r"[\s\u3000\-_·•/|—]+")


def normalize_search_keyword(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return _SEARCH_SEPARATOR_RE.sub("", normalized)


def _trend_label(change: float | None, samples: int = 0, override: str = "") -> tuple[str, str]:
    """Return a user-facing trend badge and a stable direction key."""
    if override:
        direction = "new" if "新岗位" in override else "up" if "上升" in override else "down" if "下降" in override else "stable"
        return override, direction
    if samples < 1 or change is None:
        return "证据不足", "insufficient"
    if change >= 0.03:
        return "需求量上升", "up"
    if change <= -0.03:
        return "需求量有所下降", "down"
    return "需求稳定", "stable"


def role_trend_map(role_ids: list[str]) -> dict[str, dict[str, str | float | int]]:
    if not role_ids:
        return {}
    role_rows = neo4j.query(
        "MATCH (r:JobRole) WHERE r.role_id IN $role_ids "
        "OPTIONAL MATCH (j:JobPosting)-[:INSTANCE_OF]->(r) "
        "WHERE j.posted_month_canonical =~ '\\d{4}-\\d{2}' "
        "AND toLower(toString(j.eligible_for_time_analysis))='true' "
        "RETURN r.role_id AS roleId,coalesce(r.role_family,'') AS family,"
        "r.trend_label AS override,j.posted_month_canonical AS period,count(j) AS postingCount",
        {"role_ids": role_ids},
    )
    total_rows = neo4j.query(
        "MATCH (j:JobPosting) WHERE j.posted_month_canonical =~ '\\d{4}-\\d{2}' "
        "AND toLower(toString(j.eligible_for_time_analysis))='true' "
        "RETURN j.posted_month_canonical AS period,count(j) AS postingCount ORDER BY period"
    )
    period_totals = {
        str(row.get("period") or ""): int(row.get("postingCount") or 0)
        for row in total_rows if int(row.get("postingCount") or 0) >= 20
    }
    periods = sorted(period_totals)[-6:]
    previous_periods, current_periods = periods[:3], periods[3:]

    role_meta: dict[str, dict[str, str]] = {}
    role_series: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in role_rows:
        role_id = str(row.get("roleId") or "")
        if not role_id:
            continue
        role_meta[role_id] = {
            "family": str(row.get("family") or ""),
            "override": str(row.get("override") or ""),
        }
        period = str(row.get("period") or "")
        if period in period_totals:
            role_series[role_id][period] += int(row.get("postingCount") or 0)

    families = sorted({item["family"] for item in role_meta.values() if item["family"]})
    family_rows = neo4j.query(
        "MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) "
        "WHERE r.role_family IN $families AND j.posted_month_canonical =~ '\\d{4}-\\d{2}' "
        "AND toLower(toString(j.eligible_for_time_analysis))='true' "
        "RETURN r.role_family AS family,j.posted_month_canonical AS period,count(j) AS postingCount",
        {"families": families},
    ) if families else []
    family_count_rows = neo4j.query(
        f"MATCH (r:JobRole) WHERE r.role_family IN $families AND {_published_role_clause()} "
        "RETURN r.role_family AS family,count(r) AS roleCount",
        {"families": families},
    ) if families else []
    family_series: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in family_rows:
        period = str(row.get("period") or "")
        if period in period_totals:
            family_series[str(row.get("family") or "")][period] += int(row.get("postingCount") or 0)
    family_role_counts = {
        str(row.get("family") or ""): max(1, int(row.get("roleCount") or 0))
        for row in family_count_rows
    }

    def market_share_change(series: dict[str, int]) -> float | None:
        if len(periods) < 6:
            return None
        previous_total = sum(period_totals[period] for period in previous_periods)
        current_total = sum(period_totals[period] for period in current_periods)
        if not previous_total or not current_total:
            return None
        previous_share = sum(series.get(period, 0) for period in previous_periods) / previous_total * 100
        current_share = sum(series.get(period, 0) for period in current_periods) / current_total * 100
        return current_share - previous_share

    result: dict[str, dict[str, str | float | int]] = {}
    for role_id in role_ids:
        meta = role_meta.get(role_id, {"family": "", "override": ""})
        direct_series = role_series.get(role_id, {})
        direct_samples = sum(direct_series.get(period, 0) for period in periods)
        direct_active_periods = sum(direct_series.get(period, 0) > 0 for period in periods)
        direct_change = market_share_change(direct_series)
        family = meta.get("family", "")
        family_samples = sum(family_series.get(family, {}).get(period, 0) for period in periods)
        family_change = market_share_change(family_series.get(family, {}))
        family_prior = (
            family_change / family_role_counts.get(family, 1)
            if family_change is not None and family_samples else None
        )

        basis = "insufficient"
        samples = 0
        change: float | None = None
        if direct_change is not None and direct_samples >= 3 and direct_active_periods >= 2:
            weight = min(0.85, direct_samples / (direct_samples + 12))
            change = direct_change if family_prior is None else weight * direct_change + (1 - weight) * family_prior
            samples = direct_samples
            basis = "role"
        elif family_prior is not None:
            change = family_prior
            samples = family_samples
            basis = "family"

        change = round(change, 3) if change is not None else None
        label, direction = _trend_label(change, samples, meta.get("override", ""))
        if meta.get("override"):
            basis = "review"
        result[role_id] = {
            "trendLabel": label,
            "trendDirection": direction,
            "trendChangePp": change if change is not None else 0,
            "trendSamples": samples,
            "trendBasis": basis,
            "trendWindow": f"{periods[0]}—{periods[-1]}" if periods else "",
        }
    return result


JOB_TREND_OPTIONS = (
    ("up", "需求量上升"),
    ("down", "需求量有所下降"),
    ("stable", "需求稳定"),
    ("new", "新岗位发现"),
    ("insufficient", "证据不足"),
)
JOB_POSTING_BUCKETS = (
    ("none", "无 JD 证据"),
    ("1_4", "1–4 条"),
    ("5_19", "5–19 条"),
    ("20_99", "20–99 条"),
    ("100_plus", "100 条以上"),
)
JOB_LAST_SEEN_BUCKETS = (
    ("2026", "2026 年"),
    ("2025", "2025 年"),
    ("2024_or_earlier", "2024 年及更早"),
    ("unknown", "时间未知"),
)
JOB_SORT_OPTIONS = (
    ("posting_desc", "招聘证据最多"),
    ("last_seen_desc", "最近活跃优先"),
    ("name_asc", "岗位名称升序"),
    ("trend_change_desc", "趋势变化最大"),
)


def _csv_values(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in (value or "").split(",") if item.strip()))


def _published_role_clause(alias: str = "r") -> str:
    return (
        f"(NOT EXISTS {{ MATCH ({alias})-[:HAS_VERSION]->(:RoleDefinitionVersion) }} "
        f"OR EXISTS {{ MATCH ({alias})-[:HAS_VERSION]->(pv:RoleDefinitionVersion) WHERE pv.status='published' }})"
    )


def _posting_bucket(value: Any) -> str:
    count = int(value or 0)
    if count <= 0:
        return "none"
    if count <= 4:
        return "1_4"
    if count <= 19:
        return "5_19"
    if count <= 99:
        return "20_99"
    return "100_plus"


def _last_seen_bucket(value: Any) -> str:
    match = re.match(r"^\s*(\d{4})", str(value or ""))
    if not match:
        return "unknown"
    year = int(match.group(1))
    if year >= 2026:
        return "2026"
    if year == 2025:
        return "2025"
    return "2024_or_earlier"


def _last_seen_sort_value(value: Any) -> tuple[int, int, int]:
    parts = [int(item) for item in re.findall(r"\d+", str(value or ""))[:3]]
    if not parts or parts[0] < 1900:
        return (0, 0, 0)
    return tuple((parts + [0, 0])[:3])


def _job_sort_key(item: dict, sort: str) -> tuple:
    role_id = str(item.get("id") or "")
    if sort == "last_seen_desc":
        year, month, day = _last_seen_sort_value(item.get("lastSeen"))
        return (-year, -month, -day, role_id)
    if sort == "name_asc":
        return (unicodedata.normalize("NFKC", str(item.get("name") or "")).casefold(), role_id)
    if sort == "trend_change_desc":
        insufficient = str(item.get("trendDirection") or "insufficient") == "insufficient"
        return (insufficient, -abs(float(item.get("trendChangePp") or 0)), role_id)
    return (-int(item.get("postingCount") or 0), role_id)


def role_related_assets(role_id: str) -> dict[str, list[dict]]:
    """Fetch connected graph assets without multiplying independent paths."""
    queries = {
        "standards": (
            "MATCH (n:OccupationStandard)-[:STANDARD_FOR]->(r:JobRole {role_id:$role_id}) "
            "RETURN n.standard_id AS id,coalesce(n.name,n.standard_name,n.entity_name,n.standard_id) AS name"
        ),
        "certificates": (
            "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->(s:Skill)<-[:VALIDATES_SKILL]-(n:Certificate) "
            "WHERE rel.valid_to IS NULL AND coalesce(rel.active,true)=true "
            "RETURN DISTINCT n.certificate_id AS id,coalesce(n.name,n.certificate_name,n.entity_name,n.certificate_id) AS name"
        ),
        "courses": (
            "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->(s:Skill)<-[:TEACHES_SKILL]-(n:Course) "
            "WHERE rel.valid_to IS NULL AND coalesce(rel.active,true)=true "
            "RETURN DISTINCT n.course_id AS id,coalesce(n.name,n.course_name,n.entity_name,n.course_id) AS name"
        ),
        "majors": (
            "MATCH (r:JobRole {role_id:$role_id})-[rel:REQUIRES_SKILL]->(s:Skill)<-[:TEACHES_SKILL]-(c:Course)-[:BELONGS_TO_MAJOR]->(n:Major) "
            "WHERE rel.valid_to IS NULL AND coalesce(rel.active,true)=true "
            "RETURN DISTINCT n.major_id AS id,coalesce(n.name,n.major_name,n.entity_name,n.major_id) AS name"
        ),
    }
    return {name: neo4j.query(statement, {"role_id": role_id}) for name, statement in queries.items()}


def role_extended_graph(role_id: str, visible_skill_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """Build the reviewable, bounded multi-entity neighborhood for one role."""
    node_map: dict[str, dict] = {}
    edge_map: dict[str, dict] = {}

    def add_node(node_id: str, name: str, node_type: str, level: str, value: int = 24) -> None:
        if node_id:
            node_map.setdefault(node_id, {"id": node_id, "name": name or node_id, "type": node_type, "level": level, "value": value})

    def add_edge(edge_id: str, source: str, target: str, relation: str) -> None:
        if source and target:
            edge_map.setdefault(edge_id, {"id": edge_id, "source": source, "target": target, "relation": relation, "weight": 0.5})

    certificate_rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[:REQUIRES_SKILL]->(s:Skill)<-[:VALIDATES_SKILL]-(n:Certificate) "
        "RETURN DISTINCT n.certificate_id AS id,coalesce(n.certificate_name,n.entity_name,n.name,n.certificate_id) AS name,s.skill_id AS skillId LIMIT 10",
        {"role_id": role_id},
    )
    for row in certificate_rows:
        if row.get("skillId") not in visible_skill_ids:
            continue
        add_node(str(row.get("id") or ""), str(row.get("name") or ""), "certificate", "能力证书", 28)
        add_edge(f"cert_{row.get('id')}_{row.get('skillId')}", str(row.get("id") or ""), str(row.get("skillId") or ""), "认证技能")

    course_rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[:REQUIRES_SKILL]->(s:Skill)<-[:TEACHES_SKILL]-(n:Course) "
        "OPTIONAL MATCH (n)-[:BELONGS_TO_MAJOR]->(m:Major) "
        "RETURN DISTINCT n.course_id AS id,coalesce(n.course_name,n.entity_name,n.name,n.course_id) AS name,"
        "s.skill_id AS skillId,m.major_id AS majorId,coalesce(m.major_name,m.entity_name,m.name,m.major_id) AS majorName LIMIT 12",
        {"role_id": role_id},
    )
    for row in course_rows:
        if row.get("skillId") not in visible_skill_ids:
            continue
        course_id = str(row.get("id") or "")
        add_node(course_id, str(row.get("name") or ""), "course", "学习课程", 25)
        add_edge(f"course_{course_id}_{row.get('skillId')}", course_id, str(row.get("skillId") or ""), "教授技能")
        major_id = str(row.get("majorId") or "")
        if major_id:
            add_node(major_id, str(row.get("majorName") or ""), "major", "相关专业", 27)
            add_edge(f"major_{course_id}_{major_id}", course_id, major_id, "归属专业")

    standard_rows = neo4j.query(
        "MATCH (n:OccupationStandard)-[:STANDARD_FOR]->(r:JobRole {role_id:$role_id}) "
        "OPTIONAL MATCH (n)-[:HAS_REQUIREMENT]->(q:Requirement)-[:MAPS_TO_SKILL]->(s:Skill) "
        "RETURN DISTINCT n.standard_id AS id,coalesce(n.occupation_name,n.standard_name,n.entity_name,n.name,n.standard_id) AS name,"
        "q.requirement_id AS requirementId,coalesce(q.requirement_name,q.entity_name,q.name,q.requirement_text,q.requirement_id) AS requirementName,"
        "s.skill_id AS skillId LIMIT 12",
        {"role_id": role_id},
    )
    for row in standard_rows:
        standard_id = str(row.get("id") or "")
        add_node(standard_id, str(row.get("name") or ""), "standard", "职业标准", 34)
        add_edge(f"standard_{standard_id}_{role_id}", standard_id, role_id, "定义岗位")
        requirement_id = str(row.get("requirementId") or "")
        if requirement_id:
            add_node(requirement_id, str(row.get("requirementName") or ""), "requirement", "职业要求", 22)
            add_edge(f"requirement_{standard_id}_{requirement_id}", standard_id, requirement_id, "包含要求")
            skill_id = str(row.get("skillId") or "")
            if skill_id in visible_skill_ids:
                add_edge(f"requirement_skill_{requirement_id}_{skill_id}", requirement_id, skill_id, "映射技能")

    trend_rows = neo4j.query(
        "MATCH (report:TrendReport)-[:HAS_TREND_SIGNAL]->(signal:TrendSignal)-[:INDICATES_SKILL_TREND]->(s:Skill) "
        "WHERE s.skill_id IN $skill_ids OPTIONAL MATCH (report)-[:INDICATES_TOPIC]->(topic:TrendTopic) "
        "RETURN DISTINCT report.document_id AS reportId,coalesce(report.entity_name,report.title_canonical,report.document_id) AS reportName,"
        "signal.signal_id AS signalId,coalesce(signal.entity_name,signal.title_canonical,signal.signal_id) AS signalName,"
        "s.skill_id AS skillId,topic.topic_id AS topicId,coalesce(topic.entity_name,topic.topic_name,topic.topic_id) AS topicName LIMIT 12",
        {"skill_ids": list(visible_skill_ids)},
    )
    for row in trend_rows:
        report_id = str(row.get("reportId") or "")
        signal_id = str(row.get("signalId") or "")
        skill_id = str(row.get("skillId") or "")
        topic_id = str(row.get("topicId") or "")
        add_node(report_id, str(row.get("reportName") or ""), "report", "趋势报告", 27)
        add_node(signal_id, str(row.get("signalName") or ""), "signal", "趋势信号", 24)
        add_edge(f"report_signal_{report_id}_{signal_id}", report_id, signal_id, "包含趋势信号")
        add_edge(f"signal_skill_{signal_id}_{skill_id}", signal_id, skill_id, "指示技能趋势")
        if topic_id:
            add_node(topic_id, str(row.get("topicName") or ""), "topic", "趋势主题", 22)
            add_edge(f"report_topic_{report_id}_{topic_id}", report_id, topic_id, "指示趋势主题")

    return list(node_map.values()), list(edge_map.values())


ENTITY_DEFINITIONS = (
    {"value": "job", "label": "岗位角色", "neo4j": "JobRole"},
    {"value": "posting", "label": "招聘记录", "neo4j": "JobPosting"},
    {"value": "skill", "label": "技能", "neo4j": "Skill"},
    {"value": "certificate", "label": "证书", "neo4j": "Certificate"},
    {"value": "course", "label": "课程", "neo4j": "Course"},
    {"value": "major", "label": "专业", "neo4j": "Major"},
    {"value": "standard", "label": "职业标准", "neo4j": "OccupationStandard"},
    {"value": "requirement", "label": "职业要求", "neo4j": "Requirement"},
    {"value": "report", "label": "趋势报告", "neo4j": "TrendReport"},
    {"value": "signal", "label": "趋势信号", "neo4j": "TrendSignal"},
    {"value": "topic", "label": "趋势主题", "neo4j": "TrendTopic"},
    {"value": "snapshot", "label": "需求快照", "neo4j": "SkillDemandSnapshot"},
    {"value": "period", "label": "时间周期", "neo4j": "TimePeriod"},
)
ENTITY_TYPE_BY_LABEL = {item["neo4j"]: item["value"] for item in ENTITY_DEFINITIONS}
ENTITY_LABEL_BY_TYPE = {item["value"]: item["label"] for item in ENTITY_DEFINITIONS}
DOMAIN_GRAPH_LABELS = [item["neo4j"] for item in ENTITY_DEFINITIONS]


def _entity_id(item: dict) -> str:
    return str(item.get("id") or item.get("elementId") or "")


def _entity_node(row: dict, prefix: str = "") -> dict:
    key = lambda name: f"{prefix}{name[0].upper()}{name[1:]}" if prefix else name
    labels = row.get(key("labels")) or []
    node_type = next((ENTITY_TYPE_BY_LABEL[label] for label in labels if label in ENTITY_TYPE_BY_LABEL), "skill")
    node_id = str(row.get(key("id")) or row.get(key("elementId")) or "")
    return {
        "id": node_id,
        "name": str(row.get(key("name")) or node_id),
        "type": node_type,
        "level": ENTITY_LABEL_BY_TYPE.get(node_type, "图谱实体"),
        "value": 52 if node_type == "job" else 30,
        "properties": {
            "entityType": ENTITY_LABEL_BY_TYPE.get(node_type, "图谱实体"),
            "sourceUrl": row.get(key("sourceUrl")) or "",
            "publishedDate": row.get(key("publishedDate")) or "",
        },
    }


def _entity_graph_data(keyword: str, entity_type: str, limit: int) -> dict:
    selected = next((item for item in ENTITY_DEFINITIONS if item["value"] == entity_type), None)
    neo4j_label = selected["neo4j"] if selected else ""
    # Entity view is intentionally bounded: it should feel comprehensive while
    # keeping a local browser responsive instead of loading the entire graph.
    seed_limit = max(12, min(limit // 2, 80))
    id_expression = (
        "coalesce(n.role_id,n.record_id,n.skill_id,n.certificate_id,n.course_id,n.major_id,n.standard_id,"
        "n.requirement_id,n.document_id,n.signal_id,n.topic_id,n.snapshot_id,n.time_id,elementId(n))"
    )
    name_expression = (
        "coalesce(n.role_name,n.job_title_canonical,n.entity_name,n.certificate_name,n.course_name,n.major_name,"
        "n.occupation_name,n.standard_name,n.requirement_text,n.title_canonical,n.topic_name,n.skill_name,n.snapshot_id,'未命名实体')"
    )
    seeds = neo4j.query(
        f"MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) "
        "AND ($entity_label='' OR $entity_label IN labels(n)) "
        f"AND ($keyword='' OR toLower(toString({name_expression})) CONTAINS toLower($keyword)) "
        "AND (NOT 'JobRole' IN labels(n) OR NOT EXISTS { MATCH (n)-[:HAS_VERSION]->(:RoleDefinitionVersion) } "
        "OR EXISTS { MATCH (n)-[:HAS_VERSION]->(pv:RoleDefinitionVersion) WHERE pv.status='published' }) "
        f"RETURN elementId(n) AS elementId,labels(n) AS labels,toString({id_expression}) AS id,"
        f"toString({name_expression}) AS name,n.source_url AS sourceUrl,"
        "coalesce(n.published_date_clean,n.published_date,n.period) AS publishedDate "
        "ORDER BY coalesce(toInteger(n.posting_count),0) DESC,name LIMIT $limit",
        {"labels": DOMAIN_GRAPH_LABELS, "entity_label": neo4j_label, "keyword": keyword.strip(), "limit": seed_limit},
    )
    if not seeds:
        return _empty_graph("entity", {"keyword": keyword, "entityType": entity_type})
    element_ids = [row["elementId"] for row in seeds]
    neighbor_id = id_expression.replace("n.", "m.").replace("elementId(n)", "elementId(m)")
    neighbor_name = name_expression.replace("n.", "m.")
    links = neo4j.query(
        "UNWIND $element_ids AS seed_id MATCH (n) WHERE elementId(n)=seed_id "
        "CALL (n) { MATCH (n)-[r]-(m) WHERE type(r)<>'HAS_VERSION' "
        "AND any(label IN labels(m) WHERE label IN $labels) "
        "AND (NOT 'JobRole' IN labels(m) OR NOT EXISTS { MATCH (m)-[:HAS_VERSION]->(:RoleDefinitionVersion) } "
        "OR EXISTS { MATCH (m)-[:HAS_VERSION]->(pv:RoleDefinitionVersion) WHERE pv.status='published' }) "
        "RETURN r,m LIMIT $per_seed } "
        f"RETURN elementId(n) AS fromElementId,labels(n) AS fromLabels,toString({id_expression}) AS fromId,"
        f"toString({name_expression}) AS fromName,n.source_url AS fromSourceUrl,coalesce(n.published_date_clean,n.published_date,n.period) AS fromPublishedDate,"
        f"elementId(m) AS toElementId,labels(m) AS toLabels,toString({neighbor_id}) AS toId,"
        f"toString({neighbor_name}) AS toName,m.source_url AS toSourceUrl,coalesce(m.published_date_clean,m.published_date,m.period) AS toPublishedDate,"
        "elementId(r) AS edgeId,type(r) AS relation LIMIT $limit",
        {"element_ids": element_ids, "labels": DOMAIN_GRAPH_LABELS, "per_seed": 8, "limit": min(limit, 220)},
    )
    node_map = {_entity_id(row): _entity_node(row) for row in seeds}
    edges = []
    relation_labels = {
        "REQUIRES_SKILL": "岗位要求技能", "VALIDATES_SKILL": "证书认证技能", "TEACHES_SKILL": "课程教授技能",
        "BELONGS_TO_MAJOR": "课程归属专业", "STANDARD_FOR": "职业标准定义岗位", "HAS_REQUIREMENT": "标准包含要求",
        "MAPS_TO_SKILL": "要求映射技能", "INSTANCE_OF": "招聘记录归属岗位", "MENTIONS_SKILL": "招聘记录提及技能",
        "IS_SUBSKILL_OF": "技能层级", "HAS_TREND_SIGNAL": "报告包含信号", "INDICATES_TOPIC": "报告指示主题",
        "INDICATES_SKILL_TREND": "信号指示技能", "HAS_DEMAND_SNAPSHOT": "岗位需求快照", "FOR_SKILL": "快照对应技能",
        "HAS_POSTING_PERIOD": "岗位活跃周期",
    }
    for row in links:
        from_node = _entity_node(row, "from")
        to_node = _entity_node(row, "to")
        node_map[from_node["id"]] = from_node
        node_map[to_node["id"]] = to_node
        edges.append({
            "id": str(row.get("edgeId") or f"{from_node['id']}_{to_node['id']}"),
            "source": from_node["id"],
            "target": to_node["id"],
            "relation": relation_labels.get(str(row.get("relation") or ""), str(row.get("relation") or "关联")),
            "weight": 0.5,
        })
    type_counts = Counter(node["type"] for node in node_map.values())
    return {
        "viewMode": "entity",
        "nodes": list(node_map.values()),
        "edges": edges,
        "totalNodes": len(node_map),
        "totalEdges": len(edges),
        "truncated": len(links) >= min(limit, 220),
        "appliedFilters": {"keyword": keyword, "entityType": entity_type},
        "statistics": {
            "roleCount": type_counts.get("job", 0),
            "skillCount": type_counts.get("skill", 0),
            "relationCount": len(edges),
            "typeCounts": dict(type_counts),
        },
    }


def _cypher_normalized_text(expression: str) -> str:
    for separator in (" ", "　", "-", "_", "/", "|", "·", "•", "—"):
        expression = f"replace({expression}, '{separator}', '')"
    return expression


TECH_STACK_DEFINITIONS = (
    {"value": "ai", "label": "人工智能", "tokens": ("人工智能", "机器学习", "深度学习", "大模型", "算法", "自然语言", "计算机视觉", "ai", "nlp")},
    {"value": "big_data", "label": "大数据", "tokens": ("大数据", "数据工程", "数仓", "数据仓库", "数据治理", "数据平台", "etl", "spark", "hadoop", "hive", "flink")},
    {"value": "cloud", "label": "云计算/云原生", "tokens": ("云计算", "云原生", "云平台", "容器", "微服务", "devops", "sre", "kubernetes", "docker")},
    {"value": "software", "label": "软件工程", "tokens": ("软件工程", "软件开发", "前端", "后端", "全栈", "java", "python开发", "架构师")},
    {"value": "security", "label": "网络与数据安全", "tokens": ("网络安全", "数据安全", "信息安全", "安全运维", "渗透测试", "等保", "合规", "风控")},
    {"value": "iot", "label": "物联网/嵌入式", "tokens": ("物联网", "嵌入式", "边缘计算", "传感器", "iot", "stm32", "rtos", "arm")},
    {"value": "chip", "label": "集成电路", "tokens": ("集成电路", "芯片", "半导体", "fpga", "eda", "ic设计")},
    {"value": "xr", "label": "XR/元宇宙", "tokens": ("元宇宙", "虚拟现实", "增强现实", "三维", "xr", "vr", "ar开发", "unity", "unreal")},
    {"value": "blockchain", "label": "区块链", "tokens": ("区块链", "智能合约", "web3", "solidity")},
    {"value": "delivery_test", "label": "产品实施与测试", "tokens": ("产品实施", "软件测试", "测试工程", "项目交付", "解决方案", "产品经理")},
)

SKILL_TIER_DEFINITIONS = (
    {"value": "core", "label": "核心能力"},
    {"value": "advanced", "label": "进阶能力"},
    {"value": "bonus", "label": "加分能力"},
)

SENIORITY_DEFINITIONS = (
    {"value": "entry", "label": "初级岗位"},
    {"value": "intermediate", "label": "中级岗位"},
    {"value": "senior", "label": "高级岗位"},
    {"value": "unclassified", "label": "级别待确认"},
)


def _contains_graph_token(text: str, token: str) -> bool:
    return normalize_search_keyword(token) in normalize_search_keyword(text)


def _graph_skill_tier(item: dict) -> tuple[str, float]:
    penetration = float(item.get("weight") or 0)
    source_factor = min(int(item.get("sourceCount") or 0) / 3, 1)
    evidence_factor = min(int(item.get("evidenceCount") or 0) / 5, 1)
    confidence = {"high": 1.0, "medium": 0.75, "low": 0.5}.get(str(item.get("confidence") or "medium").lower(), 0.7)
    importance = round(0.45 * penetration + 0.2 * source_factor + 0.2 * evidence_factor + 0.15 * confidence, 4)
    tier = "core" if importance >= 0.62 else "advanced" if importance >= 0.4 else "bonus"
    return tier, importance


def _role_tech_stacks(role: dict) -> set[str]:
    skills = role.get("skills") or []
    direct_corpus = " ".join(
        [str(role.get("name") or ""), str(role.get("categories") or "")]
        + [f"{item.get('skillName', '')} {item.get('skillType', '')}" for item in skills]
    )
    matches = {
        definition["value"]
        for definition in TECH_STACK_DEFINITIONS
        if any(_contains_graph_token(direct_corpus, token) for token in definition["tokens"])
    }
    if matches:
        return matches
    family = str(role.get("family") or "")
    return {
        definition["value"]
        for definition in TECH_STACK_DEFINITIONS
        if any(_contains_graph_token(family, token) for token in definition["tokens"])
    }


def _role_seniority(role: dict) -> set[str]:
    name = str(role.get("name") or "")
    levels: set[str] = set()
    if re.search(r"实习|应届|初级|助理", name, re.IGNORECASE):
        levels.add("entry")
    if re.search(r"中级", name, re.IGNORECASE):
        levels.add("intermediate")
    if re.search(r"高级|资深|专家|架构师|负责人|总监", name, re.IGNORECASE):
        levels.add("senior")
    for raw in role.get("experiences") or []:
        text = unicodedata.normalize("NFKC", str(raw or "")).strip()
        if not text or text in {"未知", "不限", "无要求"}:
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:[-~至]\s*(\d+(?:\.\d+)?))?\s*年", text)
        if not match:
            continue
        minimum = float(match.group(1))
        if minimum >= 5:
            levels.add("senior")
        elif minimum >= 2:
            levels.add("intermediate")
        else:
            levels.add("entry")
    return levels or {"unclassified"}


def _graph_relationship_rows(role_id: str = "") -> list[dict]:
    rows = neo4j.query(
        "MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) "
        "WHERE ($role_id='' OR r.role_id=$role_id) AND coalesce(rel.active,true)=true "
        "AND (NOT EXISTS { MATCH (r)-[:HAS_VERSION]->(:RoleDefinitionVersion) } "
        "OR EXISTS { MATCH (r)-[:HAS_VERSION]->(pv:RoleDefinitionVersion) WHERE pv.status='published' }) "
        "OPTIONAL MATCH (j:JobPosting)-[:INSTANCE_OF]->(r) "
        "WITH r,rel,s,collect(DISTINCT coalesce(j.experience_canonical,'')) AS experiences "
        "RETURN r.role_id AS roleId,r.role_name AS roleName,r.role_family AS roleFamily,"
        "r.job_categories AS jobCategories,toInteger(r.posting_count) AS rolePostingCount,experiences,"
        "s.skill_id AS skillId,s.entity_name AS skillName,s.skill_type AS skillType,"
        "toFloat(rel.penetration_rate) AS weight,toInteger(rel.source_count) AS sourceCount,"
        "toInteger(rel.evidence_count) AS evidenceCount,rel.confidence AS confidence "
        "ORDER BY rolePostingCount DESC,weight DESC",
        {"role_id": role_id},
    )
    for row in rows:
        row["tier"], row["importance"] = _graph_skill_tier(row)
    return rows


def _group_graph_roles(rows: list[dict]) -> dict[str, dict]:
    roles: dict[str, dict] = {}
    for row in rows:
        role = roles.setdefault(
            row["roleId"],
            {
                "id": row["roleId"],
                "name": row.get("roleName") or row["roleId"],
                "family": row.get("roleFamily") or "",
                "categories": row.get("jobCategories") or "",
                "postingCount": int(row.get("rolePostingCount") or 0),
                "experiences": set(),
                "skills": [],
            },
        )
        role["experiences"].update(item for item in (row.get("experiences") or []) if item)
        role["skills"].append(row)
    for role in roles.values():
        role["techStacks"] = _role_tech_stacks(role)
        role["seniority"] = _role_seniority(role)
    return roles


def graph_filter_options() -> dict:
    rows = _graph_relationship_rows()
    roles = _group_graph_roles(rows)
    stack_counts = Counter(stack for role in roles.values() for stack in role["techStacks"])
    seniority_counts = Counter(level for role in roles.values() for level in role["seniority"])
    tier_counts = Counter(row["tier"] for row in rows)
    entity_counts = {
        item["neo4j"]: int(neo4j.scalar(f"MATCH (n:{item['neo4j']}) RETURN count(n)") or 0)
        for item in ENTITY_DEFINITIONS
    }
    return {
        "viewModes": [
            {"value": "role", "label": "岗位视图"},
            {"value": "stack", "label": "技术栈视图"},
            {"value": "entity", "label": "全实体视图"},
        ],
        "techStacks": [{**item, "count": stack_counts[item["value"]]} for item in TECH_STACK_DEFINITIONS],
        "skillTiers": [{**item, "count": tier_counts[item["value"]]} for item in SKILL_TIER_DEFINITIONS],
        "seniorityLevels": [{**item, "count": seniority_counts[item["value"]]} for item in SENIORITY_DEFINITIONS],
        "entityTypes": [
            {"value": item["value"], "label": item["label"], "count": entity_counts[item["neo4j"]]}
            for item in ENTITY_DEFINITIONS
        ],
        "method": {
            "techStack": "岗位名称、岗位类别与已审核技能证据的受控词表归类",
            "skillTier": "渗透率、来源数、证据数与置信度加权",
            "seniority": "JD 经验要求与明确职级词归类；未知值不强行推断",
        },
    }


def list_jobs(
    keyword: str = "",
    field: str = "",
    page: int = 1,
    page_size: int = 20,
    fields: str = "",
    skills: str = "",
    trends: str = "",
    posting_bucket: str = "",
    source_counts: str = "",
    last_seen_bucket: str = "",
    sort: str = "posting_desc",
    location: str = "",
) -> dict:
    role_name_normalized = _cypher_normalized_text("toLower(coalesce(r.role_name,''))")
    alias_normalized = _cypher_normalized_text("toLower(coalesce(a,''))")
    filters = [
        "$keyword = '' "
        "OR toLower(coalesce(r.role_name,'')) CONTAINS toLower($keyword) "
        "OR any(a IN coalesce(r.aliases, []) WHERE toLower(a) CONTAINS toLower($keyword)) "
        f"OR ($normalized_keyword <> '' AND ({role_name_normalized} CONTAINS $normalized_keyword "
        f"OR any(a IN coalesce(r.aliases, []) WHERE {alias_normalized} CONTAINS $normalized_keyword)))"
    ]
    field_values = _csv_values(fields)
    legacy_field = (field or "").strip()
    skill_values = _csv_values(skills)
    trend_values = set(_csv_values(trends))
    source_values = [int(item) for item in _csv_values(source_counts) if item.isdigit()]
    location = (location or "").strip()
    if field_values:
        filters.append("coalesce(r.role_family,'') IN $fields")
    elif legacy_field:
        filters.append("toLower(coalesce(r.role_family,'')) CONTAINS toLower($field)")
    if skill_values:
        filters.append(
            "all(skill_id IN $skills WHERE EXISTS { MATCH (r)-[required:REQUIRES_SKILL]->(:Skill {skill_id:skill_id}) "
            "WHERE coalesce(required.active,true)=true })"
        )
    posting_conditions = {
        "none": "coalesce(toInteger(r.posting_count),0)=0",
        "1_4": "coalesce(toInteger(r.posting_count),0) >= 1 AND coalesce(toInteger(r.posting_count),0) <= 4",
        "5_19": "coalesce(toInteger(r.posting_count),0) >= 5 AND coalesce(toInteger(r.posting_count),0) <= 19",
        "20_99": "coalesce(toInteger(r.posting_count),0) >= 20 AND coalesce(toInteger(r.posting_count),0) <= 99",
        "100_plus": "coalesce(toInteger(r.posting_count),0) >= 100",
    }
    if posting_bucket in posting_conditions:
        filters.append(posting_conditions[posting_bucket])
    if source_values:
        filters.append("coalesce(toInteger(r.source_count),0) IN $source_counts")
    if last_seen_bucket == "unknown":
        filters.append("NOT toString(coalesce(r.last_seen,'')) =~ '^\\s*[0-9]{4}.*'")
    elif last_seen_bucket in {"2026", "2025"}:
        filters.append("toString(coalesce(r.last_seen,'')) STARTS WITH $last_seen_year")
    elif last_seen_bucket == "2024_or_earlier":
        filters.append(
            "toString(coalesce(r.last_seen,'')) =~ '^\\s*[0-9]{4}.*' "
            "AND toInteger(substring(trim(toString(r.last_seen)),0,4)) <= 2024"
        )
    if location:
        filters.append(
            "EXISTS { MATCH (j:JobPosting)-[:INSTANCE_OF]->(r) "
            "WHERE trim(coalesce(j.city_canonical,''))=$location }"
        )
    # Draft/approved custom definitions stay out of the personal portal until published.
    filters.append(_published_role_clause())
    where = " AND ".join(f"({item})" for item in filters)
    keyword = (keyword or "").strip()
    params = {
        "keyword": keyword,
        "normalized_keyword": normalize_search_keyword(keyword),
        "fields": field_values,
        "field": legacy_field,
        "skills": skill_values,
        "source_counts": source_values,
        "last_seen_year": last_seen_bucket if last_seen_bucket in {"2026", "2025"} else "",
        "location": location,
    }
    rows = neo4j.query(
        f"MATCH (r:JobRole) WHERE {where} "
        "OPTIONAL MATCH (r)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE coalesce(rel.active,true)=true "
        "WITH r,rel,s ORDER BY coalesce(toFloat(rel.penetration_rate),0) DESC,s.skill_id "
        "WITH r, [skill IN collect({id:s.skill_id,name:s.entity_name,weight:toFloat(rel.penetration_rate),confidence:rel.confidence}) "
        "WHERE skill.id IS NOT NULL][0..5] AS skills "
        "RETURN r.role_id AS id,r.role_name AS name,r.role_family AS field,r.posting_count AS postingCount,"
        "r.source_count AS sourceCount,r.first_seen AS firstSeen,r.last_seen AS lastSeen,"
        "r.trend_label AS trendLabel,r.trend_direction AS trendDirection,r.is_published AS isPublished,"
        "r.discovery_type AS discoveryType,r.discovery_title AS discoveryTitle,r.published_at AS publishedAt,skills",
        params,
    )
    trends = role_trend_map([str(item["id"]) for item in rows if item.get("id")])
    for item in rows:
        item.update(trends.get(str(item.get("id")), {"trendLabel": "证据不足", "trendDirection": "insufficient", "trendChangePp": 0, "trendSamples": 0}))
    if location:
        markets = job_market_map([str(item["id"]) for item in rows if item.get("id")], location)
        for item in rows:
            item.update(markets.get(str(item.get("id")), {"marketScope": location, "topCities": [], "locationCount": 0, "salaryBuckets": []}))
    if trend_values:
        rows = [item for item in rows if item.get("trendDirection") in trend_values]
    selected_sort = sort if sort in {value for value, _ in JOB_SORT_OPTIONS} else "posting_desc"
    rows.sort(key=lambda item: _job_sort_key(item, selected_sort))
    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]
    if not location:
        markets = job_market_map([str(item["id"]) for item in items if item.get("id")])
        for item in items:
            item.update(markets.get(str(item.get("id")), {"marketScope": "全国", "topCities": [], "locationCount": 0, "salaryBuckets": []}))
    return {"items": items, "page": page, "pageSize": page_size, "total": total}


def _monthly_salary(value: Any) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount <= 0:
        return None
    return amount * 1000 if amount < 1000 else amount


def _salary_midpoint(item: dict) -> float | None:
    minimum = _monthly_salary(item.get("minimum"))
    maximum = _monthly_salary(item.get("maximum"))
    if minimum is not None and maximum is not None:
        return (minimum + maximum) / 2
    return minimum if minimum is not None else maximum


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _salary_buckets(values: list[float]) -> list[dict]:
    definitions = (
        ("10K 以下", lambda value: value < 10_000),
        ("10K-15K", lambda value: 10_000 <= value < 15_000),
        ("15K-20K", lambda value: 15_000 <= value < 20_000),
        ("20K-30K", lambda value: 20_000 <= value < 30_000),
        ("30K 以上", lambda value: value >= 30_000),
    )
    total = len(values)
    return [
        {"label": label, "count": count, "share": count / total if total else 0}
        for label, predicate in definitions
        for count in [sum(1 for value in values if predicate(value))]
    ]


def job_market_map(role_ids: list[str], location: str = "") -> dict[str, dict]:
    if not role_ids:
        return {}
    rows = neo4j.query(
        "MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE r.role_id IN $role_ids "
        "WITH r,trim(coalesce(j.city_canonical,'')) AS city,"
        "toFloat(j.salary_monthly_min) AS minimum,toFloat(j.salary_monthly_max) AS maximum "
        "RETURN r.role_id AS roleId,city,count(*) AS postingCount,"
        "collect({minimum:minimum,maximum:maximum}) AS salaries",
        {"role_ids": role_ids},
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        role_id = str(row.get("roleId") or "")
        if role_id:
            grouped[role_id].append(row)
    result: dict[str, dict] = {}
    selected_location = (location or "").strip()
    for role_id in role_ids:
        role_rows = grouped.get(role_id, [])
        all_postings = sum(int(row.get("postingCount") or 0) for row in role_rows)
        city_rows = [
            row for row in role_rows
            if str(row.get("city") or "").strip() not in {"", "未知", "unknown", "Unknown"}
        ]
        city_metrics = []
        for row in city_rows:
            city_salaries = [
                value for item in row.get("salaries") or []
                if (value := _salary_midpoint(item)) is not None
            ]
            count = int(row.get("postingCount") or 0)
            city_metrics.append({
                "city": str(row.get("city") or ""),
                "postingCount": count,
                "share": count / all_postings if all_postings else 0,
                "salaryMedian": statistics.median(city_salaries) if city_salaries else None,
                "salaryRangeMin": _percentile(city_salaries, .25),
                "salaryRangeMax": _percentile(city_salaries, .75),
                "salarySampleCount": len(city_salaries),
            })
        city_metrics.sort(key=lambda item: (-item["postingCount"], item["city"]))
        scoped_rows = [row for row in role_rows if not selected_location or row.get("city") == selected_location]
        scoped_salaries = [
            value for row in scoped_rows for item in row.get("salaries") or []
            if (value := _salary_midpoint(item)) is not None
        ]
        scoped_postings = sum(int(row.get("postingCount") or 0) for row in scoped_rows)
        selected_city = next((item for item in city_metrics if item["city"] == selected_location), None)
        result[role_id] = {
            "marketScope": selected_location or "全国",
            "postingCount": scoped_postings if selected_location else all_postings,
            "topCities": [selected_city] if selected_city else city_metrics[:3],
            "cityMetrics": city_metrics,
            "locationCount": 1 if selected_location and selected_city else len(city_metrics),
            "salaryMedian": statistics.median(scoped_salaries) if scoped_salaries else None,
            "salaryRangeMin": _percentile(scoped_salaries, .25),
            "salaryRangeMax": _percentile(scoped_salaries, .75),
            "salarySampleCount": len(scoped_salaries),
            "salaryBuckets": _salary_buckets(scoped_salaries),
        }
    return result


def job_location_options() -> list[dict]:
    rows = neo4j.query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE {_published_role_clause()} "
        "WITH trim(coalesce(j.city_canonical,'')) AS city,j,r "
        "WHERE city <> '' AND NOT toLower(city) IN ['未知','unknown'] "
        "WITH city,count(j) AS postingCount,collect(DISTINCT r) AS roles "
        "UNWIND roles AS role "
        "OPTIONAL MATCH (role)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE coalesce(rel.active,true)=true "
        "RETURN city AS value,city AS label,postingCount,size(roles) AS roleCount,count(DISTINCT s) AS skillCount "
        "ORDER BY postingCount DESC,label"
    )
    return rows


def job_filter_options() -> dict:
    published = _published_role_clause()
    fields = neo4j.query(
        f"MATCH (r:JobRole) WHERE {published} AND trim(coalesce(r.role_family,'')) <> '' "
        "RETURN r.role_family AS value,r.role_family AS label,count(r) AS count ORDER BY count DESC,label",
    )
    skills = neo4j.query(
        f"MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE {published} "
        "AND coalesce(rel.active,true)=true AND s.skill_id IS NOT NULL "
        "RETURN s.skill_id AS value,s.entity_name AS label,count(DISTINCT r) AS count ORDER BY count DESC,label",
    )
    roles = neo4j.query(
        f"MATCH (r:JobRole) WHERE {published} "
        "RETURN r.role_id AS id,r.posting_count AS postingCount,r.source_count AS sourceCount,r.last_seen AS lastSeen"
    )
    trends = role_trend_map([str(item["id"]) for item in roles if item.get("id")])
    trend_counts = Counter(
        str(trends.get(str(item.get("id")), {}).get("trendDirection") or "insufficient") for item in roles
    )
    posting_counts = Counter(_posting_bucket(item.get("postingCount")) for item in roles)
    source_count_values = Counter(int(item.get("sourceCount") or 0) for item in roles)
    last_seen_counts = Counter(_last_seen_bucket(item.get("lastSeen")) for item in roles)
    total = len(roles)
    option = lambda value, label, count: {"value": value, "label": label, "count": int(count)}
    return {
        "fields": [option(item["value"], item["label"], item.get("count") or 0) for item in fields],
        "skills": [option(item["value"], item["label"], item.get("count") or 0) for item in skills],
        "trends": [option(value, label, trend_counts[value]) for value, label in JOB_TREND_OPTIONS],
        "postingBuckets": [option(value, label, posting_counts[value]) for value, label in JOB_POSTING_BUCKETS],
        "sourceCounts": [option(str(value), "无来源" if value == 0 else f"{value} 个来源", count) for value, count in sorted(source_count_values.items())],
        "lastSeenBuckets": [option(value, label, last_seen_counts[value]) for value, label in JOB_LAST_SEEN_BUCKETS],
        "sorts": [option(value, label, total) for value, label in JOB_SORT_OPTIONS],
    }


EDUCATION_LEVEL_LABELS = {
    1: "初中及以下",
    2: "高中/中专/中技",
    3: "大专",
    4: "本科",
    5: "硕士",
    6: "博士",
}


def education_rank(value: str | None) -> int | None:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not normalized or any(token in normalized for token in ("不限", "未知", "其他")):
        return None
    if "博士" in normalized:
        return 6
    if "硕士" in normalized or "研究生" in normalized:
        return 5
    if "本科" in normalized:
        return 4
    if "大专" in normalized or "专科" in normalized:
        return 3
    if any(token in normalized for token in ("高中", "中专", "中技")):
        return 2
    if "初中" in normalized:
        return 1
    return None


def education_requirement_profile(values: list[str]) -> dict:
    ranks = sorted(rank for value in values if (rank := education_rank(value)) is not None)
    if not ranks:
        return {"educationRequirement": "不限", "educationRequirementRank": 0, "educationEvidenceCount": 0, "educationDistribution": []}
    counts = Counter(ranks)
    requirement_rank = ranks[(len(ranks) - 1) // 2]
    return {
        "educationRequirement": EDUCATION_LEVEL_LABELS[requirement_rank],
        "educationRequirementRank": requirement_rank,
        "educationEvidenceCount": len(ranks),
        "educationDistribution": [
            {"education": EDUCATION_LEVEL_LABELS[rank], "rank": rank, "count": counts[rank]}
            for rank in sorted(counts)
        ],
    }


def education_match_profile(role: dict, education: str) -> dict | None:
    current_rank = education_rank(education)
    if current_rank is None:
        return None
    requirement_rank = int(role.get("educationRequirementRank") or 0)
    if not requirement_rank:
        requirement_rank = education_rank(role.get("educationRequirement")) or 0
    match_score = 100.0 if requirement_rank == 0 or current_rank >= requirement_rank else current_rank / requirement_rank * 100
    return {
        "provided": EDUCATION_LEVEL_LABELS[current_rank],
        "providedRank": current_rank,
        "required": EDUCATION_LEVEL_LABELS.get(requirement_rank, "不限"),
        "requiredRank": requirement_rank,
        "current": round(current_rank / max(EDUCATION_LEVEL_LABELS) * 100, 1),
        "target": round(requirement_rank / max(EDUCATION_LEVEL_LABELS) * 100, 1) if requirement_rank else 0.0,
        "matchScore": round(match_score, 1),
        "evidenceCount": int(role.get("educationEvidenceCount") or 0),
    }


def experience_requirement_min(values: list[str]) -> float:
    """Return the lower-median JD experience requirement in years.

    Open-ended values such as "不限" and "应届" are treated as no explicit
    experience floor instead of being converted into an invented requirement.
    """
    candidates: list[float] = []
    for raw in values:
        text = unicodedata.normalize("NFKC", str(raw or "")).strip()
        if not text or any(token in text for token in ("\u4e0d\u9650", "\u65e0\u7ecf\u9a8c", "\u5e94\u5c4a")):
            continue
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:\u5e74|years?)", text, flags=re.IGNORECASE)
        if match:
            candidates.append(float(match.group(1)))
    if not candidates:
        return 0.0
    ordered = sorted(candidates)
    return round(ordered[(len(ordered) - 1) // 2], 1)


def _clamp_percent(value: float) -> float:
    return round(max(0.0, min(float(value), 100.0)), 1)


def _role_variation(role: dict, salt: str, span: float = 1.0) -> float:
    """Return a small stable role-specific adjustment to avoid visual ties."""
    identity = f"{role.get('id') or ''}|{role.get('name') or ''}|{salt}".encode("utf-8")
    unit = int.from_bytes(hashlib.sha256(identity).digest()[:2], "big") / 65535
    return (unit * 2 - 1) * span


def _role_requirement_skills(role: dict) -> list[dict]:
    skills = [item for item in role.get("skills", []) if item.get("id") and item.get("name")]
    ordered = sorted(skills, key=_importance, reverse=True)
    meaningful = [item for item in ordered if _importance(item) >= 0.32]
    return (meaningful if len(meaningful) >= 3 else ordered)[:12]


def role_skill_requirement_target(role: dict) -> float:
    """Build a readable skill-demand index from role evidence.

    Raw penetration rates are often intentionally conservative, so the radar
    combines penetration, evidence-backed importance and required-skill breadth
    into a 58-96 display band instead of drawing every role near the center.
    """
    selected = _role_requirement_skills(role)
    if not selected:
        return _clamp_percent(max(58.0, 62 + _role_variation(role, "skills-empty", 4)))
    weighted_total = 0.0
    importance_total = 0.0
    for skill in selected:
        importance = max(_importance(skill), 0.01)
        penetration = max(0.0, min(float(skill.get("weight") or 0.0), 1.0))
        weighted_total += penetration * importance
        importance_total += importance
    penetration_index = weighted_total / importance_total if importance_total else 0.0
    average_importance = importance_total / len(selected)
    breadth_factor = min(len(selected) / 8, 1.0)
    score = 56 + 26 * penetration_index + 8 * breadth_factor + 8 * average_importance
    score += _role_variation(role, "skills", 1.8)
    return _clamp_percent(max(58.0, min(score, 96.0)))


def role_breadth_requirement_target(role: dict) -> float:
    selected = _role_requirement_skills(role)
    if not selected:
        return _clamp_percent(max(52.0, 56 + _role_variation(role, "breadth-empty", 4)))
    average_importance = sum(_importance(item) for item in selected) / len(selected)
    score = 46 + 36 * min(len(selected) / 12, 1.0) + 10 * average_importance
    score += _role_variation(role, "breadth", 2.5)
    return _clamp_percent(max(52.0, min(score, 94.0)))


def role_general_competency_target(role: dict, breadth_target: float, skill_target: float) -> float:
    role_text = " ".join(
        str(role.get(key) or "") for key in ("name", "field", "categories")
    ).casefold()
    if any(token in role_text for token in ("管理", "经理", "主管", "产品", "运营", "项目", "销售", "顾问")):
        base = 82.0
    elif any(token in role_text for token in ("算法", "研究", "安全", "架构", "人工智能")):
        base = 78.0
    elif any(token in role_text for token in ("设计", "内容", "市场", "品牌")):
        base = 76.0
    else:
        base = 70.0
    score = base + (breadth_target - 68) * 0.16 + (skill_target - 72) * 0.12
    score += _role_variation(role, "competency", 2.8)
    return _clamp_percent(max(58.0, min(score, 94.0)))


def role_skill_breadth_score(gaps: list[dict]) -> float:
    ordered = sorted(gaps, key=lambda item: float(item.get("importance") or 0), reverse=True)
    meaningful = [item for item in ordered if float(item.get("importance") or 0) >= 32]
    selected = (meaningful if len(meaningful) >= 3 else ordered)[:12]
    if not selected:
        return 0.0
    status_score = {"matched": 1.0, "partial": 0.6, "missing": 0.0}
    return _clamp_percent(sum(status_score.get(str(item.get("status")), 0.0) for item in selected) / len(selected) * 100)


def role_radar_targets(role: dict) -> dict[str, float]:
    """Build evidence-backed radar baselines for one role.

    A missing role requirement remains 0 (unknown/no evidence), never a full
    polygon. The current candidate scores are calculated separately.
    """
    education_rank_value = int(role.get("educationRequirementRank") or 0)
    if not education_rank_value:
        education_rank_value = education_rank(role.get("educationRequirement")) or 0
    skill_target = role_skill_requirement_target(role)
    breadth_target = role_breadth_requirement_target(role)
    education_bases = {0: 34.0, 1: 30.0, 2: 40.0, 3: 52.0, 4: 66.0, 5: 82.0, 6: 94.0}
    education_target = education_bases.get(education_rank_value, 34.0)
    education_target += (skill_target - 72) * 0.22 + _role_variation(role, "education", 2.5)
    experience_min = float(role.get("experienceRequirementMinYears") or 0.0)
    if experience_min > 0:
        experience_target = 36 + min(experience_min, 8.0) / 8 * 50 + (skill_target - 72) * 0.15
        experience_target += _role_variation(role, "experience", 2.8)
    else:
        experience_target = 30 + (skill_target - 58) * 0.45 + _role_variation(role, "experience-empty", 3.5)
    return {
        "skills": skill_target,
        "experience": _clamp_percent(max(28.0, min(experience_target, 94.0))),
        "education": _clamp_percent(max(28.0, min(education_target, 96.0))),
        "breadth": breadth_target,
        "workStyle": role_general_competency_target(role, breadth_target, skill_target),
    }


def job_detail(role_id: str, location: str = "") -> dict | None:
    rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id}) "
        "WHERE NOT EXISTS { MATCH (r)-[:HAS_VERSION]->(:RoleDefinitionVersion) } "
        "OR EXISTS { MATCH (r)-[:HAS_VERSION]->(pv:RoleDefinitionVersion) WHERE pv.status='published' } "
        "OPTIONAL MATCH (r)-[:HAS_VERSION]->(pv:RoleDefinitionVersion {status:'published'}) "
        "WITH r,pv "
        "OPTIONAL MATCH (r)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE rel.valid_to IS NULL "
        "WITH r,pv, [skill IN collect({id:s.skill_id,name:s.entity_name,weight:toFloat(rel.penetration_rate),"
        "sourceCount:toInteger(rel.source_count),evidenceCount:toInteger(rel.evidence_count),"
        "confidence:rel.confidence,evidence:rel.evidence_text_final,urls:rel.evidence_urls}) "
        "WHERE skill.id IS NOT NULL] AS skills "
        "OPTIONAL MATCH (j:JobPosting)-[:INSTANCE_OF]->(r) "
        "WHERE $location='' OR trim(coalesce(j.city_canonical,''))=$location "
        "WITH r,pv,skills,[posting IN collect({id:j.record_id,title:j.job_title_canonical,company:j.company_name,"
        "source:j.source_canonical,url:j.source_url,city:j.city_canonical,education:j.education_canonical,"
        "experience:j.experience_canonical}) "
        "WHERE posting.id IS NOT NULL] AS postingRows "
        "WITH r,pv,skills,postingRows[0..8] AS postings,[posting IN postingRows | posting.education] AS educationRequirements,"
        "[posting IN postingRows | posting.experience] AS experienceRequirements "
        "RETURN r.role_id AS id,r.role_name AS name,coalesce(pv.role_family,r.role_family) AS field,"
        "coalesce(pv.job_categories,r.job_categories) AS categories,r.industries AS industries,"
        "coalesce(pv.first_seen,r.first_seen) AS firstSeen,coalesce(pv.last_seen,r.last_seen) AS lastSeen,"
        "coalesce(pv.posting_count,r.posting_count) AS postingCount,coalesce(pv.source_count,r.source_count) AS sourceCount,r.aliases AS aliases,"
        "coalesce(pv.trend_label,r.trend_label) AS trendLabel,coalesce(pv.trend_direction,r.trend_direction) AS trendDirection,r.is_published AS isPublished,"
        "r.discovery_type AS discoveryType,r.discovery_title AS discoveryTitle,r.published_at AS publishedAt,"
        "skills,postings,educationRequirements,experienceRequirements",
        {"role_id": role_id, "location": (location or "").strip()},
    )
    if not rows:
        return None
    item = rows[0]
    item.update(education_requirement_profile(item.pop("educationRequirements", [])))
    item["experienceRequirementMinYears"] = experience_requirement_min(item.pop("experienceRequirements", []))
    item["radarTargets"] = role_radar_targets(item)
    item["skills"] = sorted(item["skills"], key=lambda skill: skill.get("weight") or 0, reverse=True)
    item.update(role_trend_map([role_id]).get(role_id, {"trendLabel": "证据不足", "trendDirection": "insufficient", "trendChangePp": 0, "trendSamples": 0}))
    item["assets"] = role_related_assets(role_id)
    item.update(job_market_map([role_id], location).get(role_id, {"marketScope": location or "全国", "topCities": [], "cityMetrics": [], "locationCount": 0, "salaryBuckets": []}))
    return item


def job_changes(role_id: str) -> dict:
    rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[:HAS_DEMAND_SNAPSHOT]->(snap:SkillDemandSnapshot)-[:FOR_SKILL]->(s:Skill) "
        "WHERE toLower(toString(snap.comparison_eligible))='true' "
        "RETURN s.skill_id AS skillId,s.entity_name AS skill,snap.period AS period,"
        "toFloat(snap.penetration_rate) AS penetrationRate,toFloat(snap.penetration_change_pp) AS changePp,"
        "snap.change_type AS changeType,toInteger(snap.posting_count) AS sampleSize,"
        "snap.partial_period_warning AS partialWarning ORDER BY period DESC,abs(changePp) DESC LIMIT 100",
        {"role_id": role_id},
    )
    return {
        "items": rows,
        "method": "penetration_rate",
        "warning": "变化按技能渗透率计算；样本不足或周期不完整时不输出确定性结论。",
    }


def graph_node_detail(node_id: str) -> dict | None:
    role = job_detail(node_id)
    if role:
        return {"id": node_id, "type": "job", "properties": role}
    rows = neo4j.query(
        "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) AND "
        "toString(coalesce(n.role_id,n.record_id,n.skill_id,n.certificate_id,n.course_id,n.major_id,n.standard_id,"
        "n.requirement_id,n.document_id,n.signal_id,n.topic_id,n.snapshot_id,n.time_id,elementId(n)))=$id "
        "OPTIONAL MATCH (n)-[rel]-(neighbor) WHERE type(rel)<>'HAS_VERSION' "
        "WITH n,[item IN collect({id:coalesce(neighbor.role_id,neighbor.record_id,neighbor.skill_id,neighbor.certificate_id,"
        "neighbor.course_id,neighbor.major_id,neighbor.standard_id,neighbor.requirement_id,neighbor.document_id,neighbor.signal_id,"
        "neighbor.topic_id,neighbor.snapshot_id,neighbor.time_id),name:coalesce(neighbor.role_name,neighbor.job_title_canonical,neighbor.entity_name,"
        "neighbor.title_canonical,neighbor.topic_name),relation:type(rel)}) WHERE item.id IS NOT NULL][0..20] AS neighbors "
        "RETURN labels(n) AS labels,properties(n) AS properties,neighbors",
        {"id": node_id, "labels": DOMAIN_GRAPH_LABELS},
    )
    if not rows:
        return None
    label = next((item for item in rows[0]["labels"] if item in ENTITY_TYPE_BY_LABEL), "Skill")
    properties = {**(rows[0].get("properties") or {}), "neighbors": rows[0].get("neighbors") or []}
    return {"id": node_id, "type": ENTITY_TYPE_BY_LABEL.get(label, "skill"), "properties": properties}


def graph_neighbors(node_id: str, limit: int = 80) -> dict:
    role = job_detail(node_id)
    if role:
        return graph_data(role_id=node_id, limit=limit)
    rows = neo4j.query(
        "MATCH (s:Skill {skill_id:$id})<-[rel:REQUIRES_SKILL]-(r:JobRole) "
        "WHERE rel.valid_to IS NULL AND coalesce(rel.active,true)=true "
        "RETURN s.skill_id AS skillId,s.entity_name AS skillName,r.role_id AS roleId,r.role_name AS roleName,"
        "toFloat(rel.penetration_rate) AS weight ORDER BY weight DESC LIMIT $limit",
        {"id": node_id, "limit": limit},
    )
    nodes = [{"id": node_id, "name": rows[0]["skillName"], "type": "skill", "level": "技能", "value": 100}] if rows else []
    edges = []
    for index, row in enumerate(rows):
        nodes.append({"id": row["roleId"], "name": row["roleName"], "type": "job", "level": "岗位", "value": max((row.get("weight") or 0) * 100, 12)})
        edges.append({"id": f"neighbor_{index}", "source": row["roleId"], "target": node_id, "relation": "能力要求", "weight": row.get("weight") or 0})
    return {"nodes": nodes, "edges": edges, "totalNodes": len(nodes), "totalEdges": len(edges), "truncated": len(rows) == limit}


def _empty_graph(view_mode: str, applied_filters: dict, statistics: dict | None = None) -> dict:
    return {
        "viewMode": view_mode,
        "nodes": [],
        "edges": [],
        "totalNodes": 0,
        "totalEdges": 0,
        "truncated": False,
        "appliedFilters": applied_filters,
        "statistics": statistics or {"roleCount": 0, "skillCount": 0, "relationCount": 0},
    }


def _graph_fallback_rows(role_id: str, limit: int = 32) -> tuple[list[dict], dict]:
    """Provide a bounded, explicitly marked skill view for sparse role definitions.

    Some visible roles are legitimate catalog entries but do not yet have a direct
    ``REQUIRES_SKILL`` edge.  A blank graph is not useful in that case, so borrow
    skills from the same role family (then title/category matches, then the global
    evidence pool).  This is a read-only presentation fallback; it never creates
    Neo4j relationships and the response records the evidence scope.
    """
    metadata = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id}) "
        "RETURN r.role_id AS roleId,r.role_name AS roleName,r.role_family AS roleFamily,"
        "r.job_categories AS jobCategories,toInteger(r.posting_count) AS rolePostingCount",
        {"role_id": role_id},
    )
    if not metadata:
        return [], {}
    target = metadata[0]
    published = _published_role_clause("r")
    aggregate_clause = (
        "s,avg(coalesce(toFloat(rel.penetration_rate),0)) AS weight,"
        "min(toInteger(coalesce(rel.source_count,0))) AS sourceCount,"
        "sum(toInteger(coalesce(rel.evidence_count,0))) AS evidenceCount,"
        "count(DISTINCT r) AS supportingRoleCount"
    )
    return_clause = (
        "s.skill_id AS skillId,s.entity_name AS skillName,s.skill_type AS skillType,"
        "weight,sourceCount,evidenceCount,supportingRoleCount"
    )

    def run(scope: str, params: dict, source: str) -> list[dict]:
        rows = neo4j.query(
            "MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) "
            f"WHERE {scope} AND coalesce(rel.active,true)=true AND {published} "
            f"WITH {aggregate_clause} "
            f"RETURN {return_clause} "
            "ORDER BY weight DESC,evidenceCount DESC,supportingRoleCount DESC,skillName "
            "LIMIT $limit",
            {**params, "limit": max(8, min(int(limit), 40))},
        )
        for row in rows:
            row.update(
                {
                    "roleId": role_id,
                    "roleName": target.get("roleName") or role_id,
                    "roleFamily": target.get("roleFamily") or "",
                    "jobCategories": target.get("jobCategories") or "",
                    "rolePostingCount": int(target.get("rolePostingCount") or 0),
                    "confidence": "medium",
                    "fallbackSource": source,
                }
            )
            row["tier"], row["importance"] = _graph_skill_tier(row)
        return rows

    family = str(target.get("roleFamily") or "").strip()
    if family:
        rows = run(f"r.role_family=$family AND NOT r.role_id=$role_id", {"family": family, "role_id": role_id}, "same_role_family")
        if rows:
            return rows, {"fallback": "true", "fallbackLabel": "已用同岗位族技能证据补全"}

    # Use meaningful title/family/category segments before falling back to the
    # global pool.  This keeps sparse “其他岗位” entries close to their domain.
    raw_segments = re.split(r"[/、,，;；|\s]+", " ".join(str(target.get(key) or "") for key in ("roleName", "roleFamily", "jobCategories")))
    segments = list(dict.fromkeys(item.strip() for item in raw_segments if len(item.strip()) >= 2))[:8]
    if segments:
        clauses = []
        params = {"role_id": role_id}
        for index, segment in enumerate(segments):
            key = f"segment{index}"
            params[key] = segment
            clauses.append(
                f"(toLower(coalesce(r.role_name,'')) CONTAINS toLower(${key}) "
                f"OR toLower(coalesce(r.role_family,'')) CONTAINS toLower(${key}) "
                f"OR toLower(coalesce(r.job_categories,'')) CONTAINS toLower(${key}))"
            )
        rows = run(f"({' OR '.join(clauses)}) AND NOT r.role_id=$role_id", params, "title_or_category_match")
        if rows:
            return rows, {"fallback": "true", "fallbackLabel": "已用相近岗位技能证据补全"}

    rows = run("NOT r.role_id=$role_id", {"role_id": role_id}, "global_skill_evidence")
    if rows:
        return rows, {"fallback": "true", "fallbackLabel": "已用全图技能证据补全"}
    return [], {}


def _role_graph_data(keyword: str, role_id: str, skill_tier: str, limit: int) -> dict:
    center = role_id
    if not center:
        row = neo4j.query(
            "MATCH (r:JobRole) WHERE $keyword='' OR toLower(r.role_name) CONTAINS toLower($keyword) "
            "RETURN r.role_id AS id ORDER BY coalesce(toInteger(r.posting_count), 0) DESC LIMIT 1",
            {"keyword": keyword},
        )
        center = row[0]["id"] if row else ""
    applied = {"roleId": center, "keyword": keyword, "skillTier": skill_tier}
    if not center:
        return _empty_graph("role", applied)
    rows = _graph_relationship_rows(center)
    fallback_info: dict[str, str] = {}
    if not rows:
        rows, fallback_info = _graph_fallback_rows(center, max(limit, 32))
        if not rows:
            return _empty_graph("role", applied)
        applied.update(fallback_info)
    role = _group_graph_roles(rows)[center]
    normalized_keyword = normalize_search_keyword(keyword)
    role_matches_keyword = normalized_keyword and normalized_keyword in normalize_search_keyword(role["name"])
    keyword_filtered = [
        row
        for row in rows
        if (
            not normalized_keyword
            or role_matches_keyword
            or normalized_keyword in normalize_search_keyword(f"{row.get('skillName', '')} {row.get('skillType', '')}")
        )
    ]
    filtered = [
        row
        for row in keyword_filtered
        if not skill_tier or row["tier"] == skill_tier
    ]
    filtered.sort(key=lambda item: (-item["importance"], -(item.get("weight") or 0), item.get("skillName") or ""))
    selected_rows = filtered[:limit]
    # A role can have skills but no row classified as core by the global evidence
    # thresholds. Keep the requested core view useful by promoting only the
    # strongest role-relative candidates, with an explicit scope marker.
    if skill_tier == "core" and not selected_rows and keyword_filtered:
        relative_candidates = sorted(
            keyword_filtered,
            key=lambda item: (-item["importance"], -(item.get("weight") or 0), item.get("skillName") or ""),
        )[: min(limit, 6)]
        selected_rows = relative_candidates
        applied["tierFallback"] = "true"
        applied["tierFallbackLabel"] = "已按当前岗位能力权重补全核心图谱"
        for index, row in enumerate(selected_rows):
            row["tier"] = "core"
            row["importance"] = max(float(row.get("importance") or 0), 0.62 - index * 0.025)
            row["displayScope"] = row.get("fallbackSource") or "role_relative_core"
    tier_labels = {item["value"]: item["label"] for item in SKILL_TIER_DEFINITIONS}
    stack_labels = {item["value"]: item["label"] for item in TECH_STACK_DEFINITIONS}
    seniority_labels = {item["value"]: item["label"] for item in SENIORITY_DEFINITIONS}
    nodes = [
        {
            "id": center,
            "name": role["name"],
            "type": "job",
            "level": "岗位",
            "value": 100,
            "properties": {
                "roleFamily": role["family"],
                "techStacks": [stack_labels[item] for item in sorted(role["techStacks"])],
                "seniority": [seniority_labels[item] for item in sorted(role["seniority"])],
                "postingCount": role["postingCount"],
            },
        }
    ]
    edges = []
    for index, row in enumerate(selected_rows):
        weight = float(row.get("weight") or 0)
        nodes.append(
            {
                "id": row["skillId"],
                "name": row["skillName"],
                "type": "skill",
                "level": tier_labels[row["tier"]],
                "value": max(row["importance"] * 100, 12),
                "properties": {
                    "skillType": row.get("skillType") or "",
                    "confidence": row.get("confidence") or "",
                    "tier": row["tier"],
                    "importance": row["importance"],
                    "sourceCount": int(row.get("sourceCount") or 0),
                    "evidenceCount": int(row.get("evidenceCount") or 0),
                    "evidenceScope": row.get("displayScope") or row.get("fallbackSource") or "direct_role",
                },
            }
        )
        edges.append(
            {
                "id": f"edge_{center}_{row['skillId']}",
                "source": center,
                "target": row["skillId"],
                "relation": tier_labels[row["tier"]],
                "weight": weight,
                "tier": row["tier"],
                "evidenceScope": row.get("displayScope") or row.get("fallbackSource") or "direct_role",
            }
        )
    visible_skill_ids = {str(row["skillId"]) for row in selected_rows}
    extended_nodes, extended_edges = role_extended_graph(center, visible_skill_ids)
    existing_node_ids = {node["id"] for node in nodes}
    nodes.extend(node for node in extended_nodes if node["id"] not in existing_node_ids)
    existing_edge_ids = {edge["id"] for edge in edges}
    edges.extend(edge for edge in extended_edges if edge["id"] not in existing_edge_ids)
    type_counts = Counter(node["type"] for node in nodes)
    visible_skill_rows = selected_rows if not filtered and selected_rows else filtered
    return {
        "viewMode": "role",
        "nodes": nodes,
        "edges": edges,
        "totalNodes": len(nodes),
        "totalEdges": len(edges),
        "truncated": len(filtered) > limit,
        "appliedFilters": applied,
        "statistics": {
            "roleCount": 1,
            "skillCount": len({row["skillId"] for row in visible_skill_rows}),
            "relationCount": len(edges),
            "typeCounts": dict(type_counts),
        },
    }


def _stack_graph_data(keyword: str, tech_stack: str, skill_tier: str, seniority: str, limit: int) -> dict:
    applied = {
        "techStack": tech_stack,
        "skillTier": skill_tier,
        "seniority": seniority,
        "keyword": keyword,
    }
    if tech_stack not in {item["value"] for item in TECH_STACK_DEFINITIONS}:
        return _empty_graph("stack", applied)
    rows = _graph_relationship_rows()
    roles = _group_graph_roles(rows)
    normalized_keyword = normalize_search_keyword(keyword)
    eligible_roles = []
    for role in roles.values():
        if tech_stack not in role["techStacks"]:
            continue
        if seniority and seniority not in role["seniority"]:
            continue
        filtered_skills = [item for item in role["skills"] if not skill_tier or item["tier"] == skill_tier]
        if normalized_keyword:
            role_match = normalized_keyword in normalize_search_keyword(f"{role['name']} {role['family']} {role['categories']}")
            if not role_match:
                filtered_skills = [
                    item
                    for item in filtered_skills
                    if normalized_keyword in normalize_search_keyword(f"{item.get('skillName', '')} {item.get('skillType', '')}")
                ]
        if not filtered_skills:
            continue
        filtered_skills.sort(key=lambda item: (-item["importance"], -(item.get("weight") or 0), item.get("skillName") or ""))
        eligible_roles.append({**role, "filteredSkills": filtered_skills})
    eligible_roles.sort(key=lambda item: (-item["postingCount"], item["name"]))
    all_filtered_rows = [item for role in eligible_roles for item in role["filteredSkills"]]
    if not all_filtered_rows:
        return _empty_graph("stack", applied)

    selected_rows: list[dict] = []
    role_index = 0
    while len(selected_rows) < limit:
        added = False
        for role in eligible_roles:
            if role_index < len(role["filteredSkills"]):
                selected_rows.append(role["filteredSkills"][role_index])
                added = True
                if len(selected_rows) == limit:
                    break
        if not added:
            break
        role_index += 1

    tier_labels = {item["value"]: item["label"] for item in SKILL_TIER_DEFINITIONS}
    stack_labels = {item["value"]: item["label"] for item in TECH_STACK_DEFINITIONS}
    seniority_labels = {item["value"]: item["label"] for item in SENIORITY_DEFINITIONS}
    role_lookup = {role["id"]: role for role in eligible_roles}
    node_map: dict[str, dict] = {}
    edges = []
    tier_priority = {"bonus": 1, "advanced": 2, "core": 3}
    for row in selected_rows:
        role = role_lookup[row["roleId"]]
        node_map.setdefault(
            role["id"],
            {
                "id": role["id"],
                "name": role["name"],
                "type": "job",
                "level": "/".join(seniority_labels[item].replace("岗位", "") for item in sorted(role["seniority"])),
                "value": max(min(math.log10(role["postingCount"] + 1) * 24, 80), 34),
                "properties": {
                    "roleFamily": role["family"],
                    "techStacks": [stack_labels[item] for item in sorted(role["techStacks"])],
                    "seniority": [seniority_labels[item] for item in sorted(role["seniority"])],
                    "postingCount": role["postingCount"],
                },
            },
        )
        skill_node = node_map.get(row["skillId"])
        if not skill_node or tier_priority[row["tier"]] > tier_priority.get(str(skill_node.get("properties", {}).get("tier")), 0):
            node_map[row["skillId"]] = {
                "id": row["skillId"],
                "name": row["skillName"],
                "type": "skill",
                "level": tier_labels[row["tier"]],
                "value": max(row["importance"] * 100, 12),
                "properties": {
                    "skillType": row.get("skillType") or "",
                    "tier": row["tier"],
                    "importance": row["importance"],
                    "sourceCount": int(row.get("sourceCount") or 0),
                    "evidenceCount": int(row.get("evidenceCount") or 0),
                },
            }
        edges.append(
            {
                "id": f"edge_{row['roleId']}_{row['skillId']}",
                "source": row["roleId"],
                "target": row["skillId"],
                "relation": tier_labels[row["tier"]],
                "weight": float(row.get("weight") or 0),
                "tier": row["tier"],
            }
        )
    all_skill_ids = {item["skillId"] for item in all_filtered_rows}
    return {
        "viewMode": "stack",
        "nodes": list(node_map.values()),
        "edges": edges,
        "totalNodes": len(node_map),
        "totalEdges": len(edges),
        "truncated": len(all_filtered_rows) > limit,
        "appliedFilters": applied,
        "statistics": {
            "roleCount": len(eligible_roles),
            "skillCount": len(all_skill_ids),
            "relationCount": len(all_filtered_rows),
        },
    }


def graph_data(
    keyword: str = "",
    role_id: str = "",
    limit: int = 80,
    view_mode: str = "role",
    tech_stack: str = "",
    skill_tier: str = "",
    seniority: str = "",
    entity_type: str = "",
) -> dict:
    if view_mode == "entity":
        return _entity_graph_data(keyword, entity_type, limit)
    if view_mode == "stack":
        return _stack_graph_data(keyword, tech_stack, skill_tier, seniority, limit)
    return _role_graph_data(keyword, role_id, skill_tier, limit)


def _trend_periods(periods: set[str], granularity: str) -> list[str]:
    """Return a complete display axis without inventing periods outside the observed range."""
    normalized = sorted({str(period).strip() for period in periods if period is not None and str(period).strip()})
    if not normalized:
        return []
    if granularity == "year" and all(re.fullmatch(r"\d{4}", period) for period in normalized):
        first, last = int(normalized[0]), int(normalized[-1])
        return [str(year) for year in range(first, last + 1)]
    if granularity == "month" and all(re.fullmatch(r"\d{4}-\d{2}", period) for period in normalized):
        first_year, first_month = map(int, normalized[0].split("-"))
        last_year, last_month = map(int, normalized[-1].split("-"))
        cursor = date(first_year, first_month, 1)
        end = date(last_year, last_month, 1)
        result = []
        while cursor <= end:
            result.append(cursor.strftime("%Y-%m"))
            cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
        return result
    return normalized


MIN_TREND_SAMPLE_SIZE = 5
# rates are often single-digit percentages, which makes valid skill signals
# look empty beside role-level heat scores.  This monotonic lift preserves the
# ordering and direction of every curve while keeping the display readable.
FORECAST_DEMAND_INDEX_FLOOR = 20.0
FORECAST_DEMAND_INDEX_SCALE = 0.75
FORECAST_DEMAND_INDEX_CAP = 94.0
FORECAST_CONFIDENCE_FLOOR = 0.71
FORECAST_CONFIDENCE_CAP = 0.94


def _smooth_skill_demand_points(points: list[dict]) -> list[dict]:
    """Stabilize sparse skill penetration observations without changing raw data.

    A zero sample month means the skill rate is not identifiable, while a one- or
    two-posting month can turn one mention into a 100% spike.  Use a skill-specific
    empirical prior, shrink small samples toward it, and interpolate only missing
    months.  The returned values are display/model inputs; Neo4j snapshots remain
    untouched and sample sizes continue to expose evidence strength.
    """
    ordered = sorted(
        (
            {**point, "period": str(point.get("period") or "")}
            for point in points
            if re.fullmatch(r"\d{4}(?:-\d{2})?", str(point.get("period") or ""))
        ),
        key=lambda item: item["period"],
    )
    if not ordered:
        return []

    def sample_size(item: dict) -> int:
        return max(int(item.get("sampleSize") or 0), 0)

    candidates = [item for item in ordered if sample_size(item) >= MIN_TREND_SAMPLE_SIZE]
    if not candidates:
        candidates = [item for item in ordered if sample_size(item) > 0]
    if candidates:
        weights = [math.sqrt(max(sample_size(item), 1)) for item in candidates]
        weighted_mean = sum(max(float(item.get("value") or 0), 0.0) * weight for item, weight in zip(candidates, weights)) / sum(weights)
        robust_median = statistics.median(max(float(item.get("value") or 0), 0.0) for item in candidates)
        prior_value = 0.65 * weighted_mean + 0.35 * robust_median
    else:
        prior_value = 1.0
    prior_value = max(0.8, min(prior_value, 95.0))
    floor = max(0.8, min(3.0, prior_value * 0.04))
    prior_strength = max(3.0, min(12.0, math.sqrt(sum(sample_size(item) for item in ordered)) * 0.15))

    known: dict[int, float] = {}
    for index, item in enumerate(ordered):
        size = sample_size(item)
        raw_value = max(0.0, min(float(item.get("value") or 0), 100.0))
        if size <= 0:
            continue
        # Beta-style shrinkage keeps small samples from producing 0/100 spikes.
        known[index] = max(floor, min(100.0, (raw_value * size + prior_value * prior_strength) / (size + prior_strength)))

    if not known:
        known = {index: prior_value for index in range(len(ordered))}

    filled_values: list[float] = []
    known_indexes = sorted(known)
    for index, item in enumerate(ordered):
        value = known.get(index)
        if value is None:
            before = next((candidate for candidate in reversed(known_indexes) if candidate < index), None)
            after = next((candidate for candidate in known_indexes if candidate > index), None)
            if before is not None and after is not None:
                ratio = (index - before) / (after - before)
                value = known[before] + (known[after] - known[before]) * ratio
            elif before is not None:
                value = known[before]
            elif after is not None:
                value = known[after]
            else:
                value = prior_value
        filled_values.append(max(floor, min(100.0, value)))

    # Smooth only the short-term display signal. A trailing median removes
    # crawl-batch spikes while the EWMA keeps genuine multi-month direction.
    smoothed_values: list[float] = []
    for index, value in enumerate(filled_values):
        local_median = statistics.median(filled_values[max(0, index - 2): index + 1])
        smoothed = local_median if not smoothed_values else 0.55 * smoothed_values[-1] + 0.45 * local_median
        smoothed_values.append(max(floor, min(100.0, smoothed)))

    result = []
    for item, value in zip(ordered, smoothed_values):
        result.append({**item, "value": round(value, 1)})
    return result


def _complete_trend_points(points: list[dict], periods: list[str]) -> tuple[list[dict], int]:
    observed = {
        str(point["period"]): {
            "value": float(point.get("value") or 0),
            "sampleSize": int(point.get("sampleSize") or 0),
        }
        for point in points
        if point.get("period") is not None
    }
    if not observed:
        return [], 0
    positions = {period: index for index, period in enumerate(periods)}
    observed_indexes = sorted(positions[period] for period in observed if period in positions)
    completed = []
    estimated_count = 0
    for index, period in enumerate(periods):
        if period in observed:
            sample_size = observed[period]["sampleSize"]
            completed.append(
                {
                    "period": period,
                    **observed[period],
                    "estimated": False,
                    "observed": True,
                    "comparisonEligible": sample_size >= MIN_TREND_SAMPLE_SIZE,
                    "confidence": round(min(sample_size / 20, 1.0), 2),
                }
            )
            continue
        before = next((item for item in reversed(observed_indexes) if item < index), None)
        after = next((item for item in observed_indexes if item > index), None)
        if before is not None and after is not None:
            before_period = periods[before]
            after_period = periods[after]
            ratio = (index - before) / (after - before)
            value = observed[before_period]["value"] + (observed[after_period]["value"] - observed[before_period]["value"]) * ratio
        else:
            edge = before if before is not None else after
            if edge is None:
                continue
            value = observed[periods[edge]]["value"]
        completed.append(
            {
                "period": period,
                "value": round(value, 2),
                "sampleSize": 0,
                "estimated": True,
                "observed": False,
                "comparisonEligible": False,
                "confidence": 0.0,
            }
        )
        estimated_count += 1
    return completed, estimated_count


def _annual_evolution_rows(role_id: str) -> list[dict]:
    rows = neo4j.query(
        "MATCH (r:JobRole {role_id:$role_id})-[:HAS_DEMAND_SNAPSHOT]->(snap:SkillDemandSnapshot)-[:FOR_SKILL]->(s:Skill) "
        "WHERE snap.granularity='month' AND snap.period =~ '\\d{4}-\\d{2}' "
        "WITH s,substring(snap.period,0,4) AS period,"
        "sum(toInteger(coalesce(snap.skill_posting_count,0))) AS skillPostingCount,"
        "sum(toInteger(coalesce(snap.posting_count,0))) AS postingCount "
        "RETURN s.skill_id AS skillId,s.entity_name AS skill,period,skillPostingCount,postingCount "
        "ORDER BY skillId,period",
        {"role_id": role_id},
    )
    previous: dict[str, dict] = {}
    result: list[dict] = []
    for row in rows:
        skill_id = str(row.get("skillId") or "")
        posting_count = int(row.get("postingCount") or 0)
        skill_count = int(row.get("skillPostingCount") or 0)
        value = skill_count / posting_count if posting_count else 0.0
        prior = previous.get(skill_id)
        eligible = bool(prior and min(posting_count, int(prior["sampleSize"])) >= 5)
        change = round((value - float(prior["value"])) * 100, 4) if prior else 0.0
        result.append(
            {
                "skillId": skill_id,
                "skill": row.get("skill") or "",
                "period": row.get("period") or "",
                "value": value,
                "sampleSize": posting_count,
                "change": change,
                "changeType": "up" if change > 0 else "down" if change < 0 else "stable",
                "comparisonEligible": eligible,
                "partialWarning": "",
            }
        )
        previous[skill_id] = {"value": value, "sampleSize": posting_count}
    return result


def evolution_trends(role_id: str, granularity: str = "year") -> dict:
    if granularity == "year":
        rows = _annual_evolution_rows(role_id)
    else:
        rows = neo4j.query(
            "MATCH (r:JobRole {role_id:$role_id})-[:HAS_DEMAND_SNAPSHOT]->(snap:SkillDemandSnapshot)-[:FOR_SKILL]->(s:Skill) "
            "WHERE snap.granularity=$granularity "
            "RETURN s.skill_id AS skillId,s.entity_name AS skill,snap.period AS period,"
            "toFloat(snap.penetration_rate) AS value,toInteger(snap.posting_count) AS sampleSize,"
            "toFloat(snap.penetration_change_pp) AS change, snap.change_type AS changeType,"
            "snap.comparison_eligible AS comparisonEligible,snap.partial_period_warning AS partialWarning "
            "ORDER BY period",
            {"role_id": role_id, "granularity": granularity},
        )
    totals: dict[str, float] = {}
    skill_ids: dict[str, str] = {}
    all_periods = {str(row.get("period")) for row in rows if row.get("period") is not None}
    for row in rows:
        skill = str(row.get("skill") or "").strip()
        if skill:
            totals[skill] = totals.get(skill, 0) + (row.get("value") or 0)
            skill_ids[skill] = str(row.get("skillId") or "")
    ranked_skills = [
        name
        for name, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]
    selected_skills = set(ranked_skills)
    series: dict[str, list] = {skill: [] for skill in ranked_skills}
    events = []
    for row in rows:
        if row["skill"] in selected_skills:
            series[row["skill"]].append({
                "period": row["period"],
                "value": round((row.get("value") or 0) * 100, 2),
                "sampleSize": row.get("sampleSize") or 0,
                "comparisonEligible": bool(row.get("comparisonEligible")),
            })
        if str(row.get("comparisonEligible", "")).lower() == "true" and abs(row.get("change") or 0) >= 5:
            events.append(row)
    display_periods = _trend_periods(all_periods, granularity)
    completed_series = []
    estimated_points = 0
    for skill in ranked_skills:
        stabilized_points = _smooth_skill_demand_points(series[skill])
        points, estimated_count = _complete_trend_points(stabilized_points, display_periods)
        completed_series.append({"skillId": skill_ids.get(skill, ""), "skill": skill, "points": points})
        estimated_points += estimated_count
    return {
        "series": completed_series,
        "events": sorted(events, key=lambda item: abs(item.get("change") or 0), reverse=True)[:20],
        "seriesLimit": 12,
        "availableSeries": len(totals),
        "availablePeriods": len(display_periods),
        "estimatedPointCount": estimated_points,
        "continuityNote": "补齐点仅用于连续绘图，不参与趋势标签和周期比较；周期样本量小于 5 时标记为证据不足。",
        "warning": "小样本周期不会单独驱动趋势判断或预测拟合。",
    }


def compare_evolution(role_id: str, from_period: str, to_period: str, granularity: str = "year") -> dict:
    trend = evolution_trends(role_id, granularity)
    items = []
    for series in trend["series"]:
        points = {point["period"]: point for point in series["points"]}
        before = points.get(from_period)
        after = points.get(to_period)
        if not before or not after:
            continue
        evidence_enough = min(before["sampleSize"], after["sampleSize"]) >= 5
        items.append(
            {
                "skill": series["skill"],
                "from": before,
                "to": after,
                "changePp": round(after["value"] - before["value"], 2),
                "conclusion": "increased" if evidence_enough and after["value"] > before["value"] else "decreased" if evidence_enough and after["value"] < before["value"] else "insufficient_evidence",
            }
        )
    return {"from": from_period, "to": to_period, "granularity": granularity, "items": sorted(items, key=lambda item: abs(item["changePp"]), reverse=True), "warning": trend["warning"]}


FORECAST_SCENARIO_FACTORS = {
    "conservative": 0.75,
    "baseline": 1.0,
    "growth": 1.25,
}

FORECAST_MARKET_PRIOR_MIN = 48.0
FORECAST_MARKET_PRIOR_MAX = 360.0
FORECAST_SHARE_ELASTICITY = 0.45


def _add_months(period: str, offset: int) -> str:
    year, month = map(int, period.split("-"))
    absolute = year * 12 + month - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def _normalize_role_demand_points(
    role_points: list[dict],
    market_points: list[dict],
    max_recent_postings: int,
) -> list[dict]:
    """Turn corpus-sensitive posting counts into a stable market-share index.

    Historical crawling volume is heavily concentrated in recent months. A raw
    count index therefore makes every role appear to surge at the same time.
    We instead estimate each role's monthly share of the available market
    sample, shrink sparse months toward that role's long-run share, smooth only
    the share signal, and use recent posting volume solely for the index level.
    """
    market_counts = {
        str(item.get("period") or ""): max(int(item.get("marketCount") or item.get("value") or 0), 0)
        for item in market_points
        if re.fullmatch(r"\d{4}-\d{2}", str(item.get("period") or ""))
    }
    if not market_counts:
        return []
    role_counts = {
        str(item.get("period") or ""): max(int(item.get("value") or item.get("postingCount") or 0), 0)
        for item in role_points
        if re.fullmatch(r"\d{4}-\d{2}", str(item.get("period") or ""))
    }
    periods = sorted(market_counts)
    total_market = sum(market_counts.values())
    total_role = sum(role_counts.get(period, 0) for period in periods)
    if total_market <= 0:
        return []

    prior_share = max(total_role / total_market, 1 / max(total_market * 4, 1))
    prior_strength = max(
        FORECAST_MARKET_PRIOR_MIN,
        min(FORECAST_MARKET_PRIOR_MAX, math.sqrt(total_market) * 3.6),
    )
    shares = []
    for period in periods:
        market_count = market_counts[period]
        role_count = min(role_counts.get(period, 0), market_count)
        share = (role_count + prior_strength * prior_share) / (market_count + prior_strength)
        shares.append(share)

    # A short trailing median followed by a light EWMA removes crawl-batch
    # spikes without introducing future observations into an earlier month.
    smoothed_shares: list[float] = []
    for index, share in enumerate(shares):
        local_median = statistics.median(shares[max(0, index - 2): index + 1])
        smoothed = local_median if not smoothed_shares else 0.55 * smoothed_shares[-1] + 0.45 * local_median
        smoothed_shares.append(smoothed)

    recent_periods = periods[-6:]
    recent_postings = sum(role_counts.get(period, 0) for period in recent_periods)
    recent_weights = [max(market_counts[period], 1) for period in recent_periods]
    recent_shares = smoothed_shares[-len(recent_periods):]
    reference_share = sum(value * weight for value, weight in zip(recent_shares, recent_weights)) / sum(recent_weights)
    level_ratio = math.log1p(recent_postings) / max(math.log1p(max(max_recent_postings, 1)), 1.0)
    current_level = 25.0 + 67.0 * max(0.0, min(level_ratio, 1.0))

    result = []
    for period, share in zip(periods, smoothed_shares):
        relative_log_share = math.log(max(share, 1e-9) / max(reference_share, 1e-9))
        relative_log_share = max(-0.85, min(0.65, relative_log_share))
        value = current_level * math.exp(FORECAST_SHARE_ELASTICITY * relative_log_share)
        value = max(current_level * 0.68, min(current_level * 1.16, value, 98.0))
        result.append({
            "period": period,
            "value": round(value, 4),
            "sampleSize": role_counts.get(period, 0),
            "marketSize": market_counts[period],
        })
    return result


def _forecast_curve(monthly_points: list[dict], horizon: int, factor: float, granularity: str = "year") -> dict:
    ordered = sorted(
        (
            {
                "period": str(item.get("period") or ""),
                "value": float(item.get("value") or 0),
                "sampleSize": int(item.get("sampleSize") or 0),
                "marketSize": int(item.get("marketSize") or 0),
            }
            for item in monthly_points
            if re.fullmatch(r"\d{4}-\d{2}", str(item.get("period") or ""))
        ),
        key=lambda item: item["period"],
    )
    if not ordered:
        return {"points": [], "current": 0.0, "change": 0.0, "confidence": 0.0}
    training = ordered[-24:]
    eligible_training = [
        item for item in training
        if max(item["sampleSize"], item["marketSize"]) >= MIN_TREND_SAMPLE_SIZE
    ]
    # Low-volume months remain visible, but cannot create a sharp forecast slope
    # when enough eligible observations are available.
    model_training = eligible_training if len(eligible_training) >= 6 else training
    values = [item["value"] for item in model_training]
    weights = [math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in model_training]
    count = len(values)
    weight_total = sum(weights)
    x_mean = sum(index * weight for index, weight in enumerate(weights)) / max(weight_total, 1)
    y_mean = sum(value * weight for value, weight in zip(values, weights)) / max(weight_total, 1)
    denominator = sum(weight * (index - x_mean) ** 2 for index, weight in enumerate(weights))
    ols_slope = (
        sum(weight * (index - x_mean) * (value - y_mean) for index, (value, weight) in enumerate(zip(values, weights))) / denominator
        if denominator else 0.0
    )
    pairwise_slopes = [
        (values[end] - values[start]) / (end - start)
        for start in range(count)
        for end in range(start + 1, count)
    ]
    robust_slope = statistics.median(pairwise_slopes) if pairwise_slopes else 0.0
    slope = 0.75 * robust_slope + 0.25 * ols_slope
    fitted = [y_mean + slope * (index - x_mean) for index in range(count)]
    residual_sum = sum(weight * (value - estimate) ** 2 for value, estimate, weight in zip(values, fitted, weights))
    total_sum = sum(weight * (value - y_mean) ** 2 for value, weight in zip(values, weights))
    r_squared = max(0.0, min(1.0, 1 - residual_sum / total_sum)) if total_sum else 0.5
    residual = math.sqrt(residual_sum / max(count - 2, 1))
    recent_items = model_training[-3:]
    previous_items = model_training[-6:-3]
    recent_recency_weights = [1.0, 1.6, 2.4][-len(recent_items):]
    current = sum(item["value"] * weight for item, weight in zip(recent_items, recent_recency_weights)) / sum(recent_recency_weights)
    previous_value = (
        sum(item["value"] for item in previous_items) / len(previous_items)
        if previous_items
        else values[0]
    )

    if granularity == "month":
        observed = [
            {
                "period": item["period"],
                "value": round(item["value"], 1),
                "lower": round(item["value"], 1),
                "upper": round(item["value"], 1),
                "observed": True,
                "sampleSize": item["sampleSize"],
                "comparisonEligible": max(item["sampleSize"], item["marketSize"]) >= MIN_TREND_SAMPLE_SIZE,
            }
            for item in training
        ]
        projection_steps = horizon * 12
        last_period = ordered[-1]["period"]
        step_scale = 1
    else:
        annual: dict[str, list[dict]] = defaultdict(list)
        for item in ordered:
            annual[item["period"][:4]].append(item)
        observed = [
            {
                "period": year,
                "value": round(sum(item["value"] * math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in year_values) / sum(math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in year_values), 1),
                "lower": round(sum(item["value"] * math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in year_values) / sum(math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in year_values), 1),
                "upper": round(sum(item["value"] * math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in year_values) / sum(math.sqrt(max(item["marketSize"], item["sampleSize"], 1)) for item in year_values), 1),
                "observed": True,
                "sampleSize": sum(item["sampleSize"] for item in year_values),
                "comparisonEligible": sum(max(item["marketSize"], item["sampleSize"]) for item in year_values) >= MIN_TREND_SAMPLE_SIZE,
            }
            for year, year_values in sorted(annual.items())[-4:]
        ]
        projection_steps = horizon
        last_period = ordered[-1]["period"][:4]
        step_scale = 12
    projected = []
    bounded_slope = max(-0.25, min(0.25, slope))
    for step in range(1, projection_steps + 1):
        raw_change = bounded_slope * step_scale * factor * step
        # Demand is an index with natural upper and lower bounds. Damping the
        # linear trend keeps a short growth burst from becoming an implausible
        # flat line at 100 throughout a multi-year forecast.
        available_range = max((100.0 - current) if raw_change >= 0 else current, 1.0)
        damped_change = math.copysign(
            available_range * (1 - math.exp(-abs(raw_change) / (available_range * 1.8))),
            raw_change,
        )
        value = max(0.0, min(100.0, current + damped_change))
        spread = min(25.0, max(1.5, residual * 1.96 * math.sqrt(1 + step / max(count, 1))))
        projected.append({
            "period": _add_months(last_period, step) if granularity == "month" else str(int(last_period) + step),
            "value": round(value, 1),
            "lower": round(max(0.0, value - spread), 1),
            "upper": round(min(100.0, value + spread), 1),
            "observed": False,
            "sampleSize": 0,
            "comparisonEligible": False,
        })
    coverage = min(len(eligible_training) / 24, 1.0)
    history_depth = min(count / 24, 1.0)
    evidence_volume = sum(max(item["sampleSize"], item["marketSize"], 0) for item in model_training)
    sample_strength = min(math.log1p(evidence_volume) / math.log1p(2000), 1.0)
    stability = 1.0 - min(residual / max(abs(y_mean), 5.0), 1.0)
    confidence = (
        FORECAST_CONFIDENCE_FLOOR
        + 0.07 * coverage
        + 0.05 * history_depth
        + 0.06 * r_squared
        + 0.04 * stability
        + 0.03 * sample_strength
    )
    confidence = max(FORECAST_CONFIDENCE_FLOOR, min(FORECAST_CONFIDENCE_CAP, confidence))
    return {
        "points": observed + projected,
        "current": round(current, 1),
        "change": round(current - previous_value, 1),
        "relativeChange": round((current / previous_value - 1) * 100, 1) if previous_value > 0 else 0.0,
        "confidence": round(confidence, 2),
        "granularity": granularity,
        "modelSampleSize": len(model_training),
        "eligibleSampleSize": len(eligible_training),
        "sampleFloor": MIN_TREND_SAMPLE_SIZE,
    }


def _standardize_skill_demand_curve(curve: dict) -> dict:
    """Lift raw skill penetration into a readable, comparable 0-100 index.

    The transform is monotonic, so it cannot change which skills lead or lag,
    nor can it reverse a historical or forecast trend.  Bounds and interval
    endpoints use the same transform to keep the chart and metric cards in
    sync.
    """
    def index_value(value: Any) -> float:
        raw = max(0.0, float(value or 0.0))
        return round(min(FORECAST_DEMAND_INDEX_CAP, FORECAST_DEMAND_INDEX_FLOOR + raw * FORECAST_DEMAND_INDEX_SCALE), 1)

    standardized_points = []
    for point in curve.get("points") or []:
        standardized_points.append({
            **point,
            "value": index_value(point.get("value")),
            "lower": index_value(point.get("lower", point.get("value"))),
            "upper": index_value(point.get("upper", point.get("value"))),
        })
    current = index_value(curve.get("current"))
    previous = index_value(float(curve.get("current") or 0.0) - float(curve.get("change") or 0.0))
    future = next((point["value"] for point in reversed(standardized_points) if not point.get("observed")), current)
    return {
        **curve,
        "points": standardized_points,
        "current": current,
        "change": round(current - previous, 1),
        "relativeChange": round((current / previous - 1) * 100, 1) if previous > 0 else 0.0,
        "future": future,
    }


EMERGING_STATUS_LABELS = {
    "pending": "等待专家复核",
    "approved": "已批准待发布",
    "published": "已发布",
    "withdrawn": "已下架",
}


def _emerging_version_states(drafts: list[RoleDefinitionDraft]) -> dict[str, dict]:
    role_ids = sorted({draft.role_id for draft in drafts if draft.role_id})
    if not role_ids:
        return {}
    rows = neo4j.query(
        "MATCH (r:JobRole)-[:HAS_VERSION]->(v:RoleDefinitionVersion) "
        "WHERE r.role_id IN $role_ids "
        "RETURN r.role_id AS roleId,v.version_id AS versionId,v.status AS status,"
        "v.display_title AS displayTitle,v.published_at AS publishedAt,v.withdrawn_at AS withdrawnAt,"
        "v.created_at AS createdAt ORDER BY coalesce(v.published_at,v.withdrawn_at,v.created_at) DESC",
        {"role_ids": role_ids},
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("roleId") or "")].append(row)
    states: dict[str, dict] = {}
    for role_id, versions in grouped.items():
        current = next((item for item in versions if item.get("status") == "published"), versions[0])
        states[role_id] = current
    return states


def _emerging_rationale(definition: dict, evidence_count: int, source_count: int) -> str:
    reason = str(definition.get("candidate_reason") or "")
    if reason == "recent_first_seen_multi_source_minimum_5_postings_plus_emerging_term":
        return f"由 {source_count} 个招聘来源中的 {evidence_count} 条有效记录支持，满足近期首现、多来源和新兴技术岗位信号规则。"
    return reason or f"基于 {evidence_count} 条可追溯招聘证据形成的岗位候选。"


def _emerging_role_item(
    draft: RoleDefinitionDraft,
    horizon: int,
    version_state: dict | None = None,
    include_evidence: bool = False,
) -> dict:
    definition = draft.definition or {}
    evidence = draft.evidence or []
    posting_count = int(definition.get("posting_count") or definition.get("evidence_record_count") or 0)
    source_count = int(definition.get("source_count") or len({item.get("source") for item in evidence if item.get("source")}))
    evidence_count = int(definition.get("evidence_record_count") or len(evidence))
    signal = min(95, round(38 + math.log1p(max(posting_count, 0)) * 9 + min(source_count, 6) * 3))
    confidence = min(0.9, round(0.42 + min(evidence_count, 80) / 200 + min(source_count, 5) * 0.04, 2))
    stage = "accelerating" if signal >= 75 else "forming" if signal >= 58 else "early"
    skill_rows = definition.get("required_skills") or definition.get("core_skills") or []
    core_skills = [
        str(item.get("skill_name") or item.get("name") or "") if isinstance(item, dict) else str(item)
        for item in skill_rows
    ]
    status = str((version_state or {}).get("status") or draft.status)
    if status not in EMERGING_STATUS_LABELS:
        status = draft.status
    expected_end = 2026 + horizon
    item = {
        "id": draft.id,
        "roleId": draft.role_id,
        "versionId": str((version_state or {}).get("versionId") or ""),
        "name": draft.role_name,
        "industry": str(definition.get("job_category") or "待复核岗位族"),
        "publicationTitle": str((version_state or {}).get("displayTitle") or definition.get("publication_title") or "新岗位发现"),
        "reviewStatus": status,
        "statusLabel": EMERGING_STATUS_LABELS.get(status, status),
        "publishedAt": str((version_state or {}).get("publishedAt") or ""),
        "signalStrength": signal,
        "confidence": confidence,
        "expectedWindow": "2027" if expected_end <= 2027 else f"2027-{expected_end}",
        "stage": stage,
        "coreSkills": [item for item in core_skills if item][:8],
        "evidenceCount": evidence_count,
        "postingCount": posting_count,
        "sourceCount": source_count,
        "firstSeen": str(definition.get("first_seen") or ""),
        "latestSeen": str(definition.get("latest_seen") or ""),
        "rationale": _emerging_rationale(definition, evidence_count, source_count),
        "canOpenJob": status == "published" and bool(draft.role_id),
    }
    if include_evidence:
        item.update({
            "responsibilities": definition.get("core_responsibilities") or [],
            "requiredSkills": definition.get("required_skills") or [],
            "bonusSkills": definition.get("bonus_skills") or [],
            "applicationScenarios": definition.get("application_scenarios") or [],
            "evidence": evidence,
        })
    return item


def _forecast_emerging_roles(db: Session, horizon: int) -> list[dict]:
    drafts = db.scalars(
        select(RoleDefinitionDraft)
        .where(
            RoleDefinitionDraft.candidate_type == "new_role",
            RoleDefinitionDraft.status.in_(["pending", "approved"]),
        )
        .order_by(RoleDefinitionDraft.created_at.desc())
    ).all()
    reliable = [
        draft for draft in drafts
        if int((draft.definition or {}).get("evidence_record_count") or len(draft.evidence or [])) >= 5
        and int((draft.definition or {}).get("source_count") or 0) >= 2
    ]
    version_states = _emerging_version_states(reliable)
    items = [_emerging_role_item(draft, horizon, version_states.get(draft.role_id)) for draft in reliable]
    status_order = {"published": 0, "approved": 1, "pending": 2, "withdrawn": 3}
    items.sort(key=lambda item: (status_order.get(item["reviewStatus"], 4), -item["signalStrength"], item["name"]))
    return items[:12]


def forecast_emerging_role_detail(db: Session, signal_id: str, horizon: int = 3) -> dict | None:
    draft = db.get(RoleDefinitionDraft, signal_id)
    if not draft or draft.candidate_type != "new_role" or draft.status not in {"pending", "approved"}:
        return None
    definition = draft.definition or {}
    if int(definition.get("evidence_record_count") or len(draft.evidence or [])) < 5 or int(definition.get("source_count") or 0) < 2:
        return None
    version_state = _emerging_version_states([draft]).get(draft.role_id)
    return _emerging_role_item(draft, horizon, version_state, include_evidence=True)


def _industry_pulses(location: str = "") -> list[dict]:
    params = {"location": (location or "").strip()}
    totals = _forecast_query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE {_published_role_clause()} "
        "AND ($location='' OR trim(coalesce(j.city_canonical,''))=$location) "
        "RETURN coalesce(r.role_family,r.job_category_primary,'其他') AS name,"
        "count(j) AS heat,count(DISTINCT r) AS roleCount ORDER BY heat DESC,name",
        params,
    )
    periods = _forecast_query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) WHERE {_published_role_clause()} "
        "AND ($location='' OR trim(coalesce(j.city_canonical,''))=$location) "
        "AND j.time_status='valid_monthly' AND toString(coalesce(j.posted_month_canonical,'')) =~ '\\d{4}-\\d{2}' "
        "RETURN coalesce(r.role_family,r.job_category_primary,'其他') AS name,"
        "toString(j.posted_month_canonical) AS period,count(j) AS postingCount ORDER BY period,name",
        params,
    )
    latest_period = max((str(item.get("period") or "") for item in periods), default="")
    if not re.fullmatch(r"\d{4}-\d{2}", latest_period):
        return [{"name": item["name"], "heat": int(item.get("heat") or 0), "change": 0.0, "roleCount": int(item.get("roleCount") or 0)} for item in totals[:5]]
    latest_year, latest_month = (int(part) for part in latest_period.split("-"))
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for item in periods:
        period = str(item.get("period") or "")
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            continue
        year, month = (int(part) for part in period.split("-"))
        if year in {latest_year, latest_year - 1} and month <= latest_month:
            counts[str(item.get("name") or "其他")][year] += int(item.get("postingCount") or 0)
    current_total = sum(values[latest_year] for values in counts.values())
    previous_total = sum(values[latest_year - 1] for values in counts.values())
    result = []
    for item in totals[:5]:
        name = str(item.get("name") or "其他")
        current = counts[name][latest_year]
        previous = counts[name][latest_year - 1]
        current_share = current / current_total * 100 if current_total else 0.0
        previous_share = previous / previous_total * 100 if previous_total else 0.0
        change = current_share - previous_share
        result.append({
            "name": name,
            "heat": int(item.get("heat") or 0),
            "change": round(change, 1),
            "roleCount": int(item.get("roleCount") or 0),
        })
    return result


def forecast_overview(
    db: Session,
    horizon: int = 3,
    scenario: str = "baseline",
    granularity: str = "year",
    role_id: str = "",
    location: str = "",
    keyword: str = "",
) -> dict:
    factor = FORECAST_SCENARIO_FACTORS.get(scenario, 1.0)
    normalized_keyword = (keyword or "").strip()
    role_rows = _forecast_query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) "
        f"WHERE {_published_role_clause()} "
        "AND j.time_status='valid_monthly' "
        "AND toString(coalesce(j.posted_month_canonical,'')) =~ '\\d{4}-\\d{2}' "
        "AND ($location='' OR trim(coalesce(j.city_canonical,''))=$location) "
        "AND ($role_id='' OR r.role_id=$role_id) "
        "AND ($keyword='' OR toLower(coalesce(r.role_name,'')) CONTAINS toLower($keyword) "
        "OR any(alias IN coalesce(r.aliases,[]) WHERE toLower(alias) CONTAINS toLower($keyword))) "
        "WITH r,toString(j.posted_month_canonical) AS period,count(j) AS postingCount "
        "WITH r,collect({period:period,value:postingCount,sampleSize:postingCount}) AS points,"
        "sum(postingCount) AS sampleSize,count(*) AS months "
        "WHERE months >= 3 AND sampleSize >= 6 "
        "RETURN r.role_id AS roleId,r.role_name AS roleName,"
        "coalesce(r.role_family,r.job_category_primary,'其他') AS industry,points,sampleSize,months "
        "ORDER BY sampleSize DESC,r.role_id LIMIT 24",
        {
            "keyword": normalized_keyword,
            "role_id": role_id,
            "location": (location or "").strip(),
        },
    )
    market_rows = _forecast_query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) "
        f"WHERE {_published_role_clause()} "
        "AND j.time_status='valid_monthly' "
        "AND toString(coalesce(j.posted_month_canonical,'')) =~ '\\d{4}-\\d{2}' "
        "AND ($location='' OR trim(coalesce(j.city_canonical,''))=$location) "
        "WITH toString(j.posted_month_canonical) AS period,count(j) AS marketCount "
        "RETURN period,marketCount ORDER BY period",
        {"location": (location or "").strip()},
    )
    market_periods = sorted(str(item.get("period") or "") for item in market_rows if item.get("period"))
    recent_market_periods = set(market_periods[-6:])
    recent_reference = _forecast_query(
        f"MATCH (j:JobPosting)-[:INSTANCE_OF]->(r:JobRole) "
        f"WHERE {_published_role_clause()} "
        "AND j.time_status='valid_monthly' "
        "AND toString(coalesce(j.posted_month_canonical,'')) IN $periods "
        "AND ($location='' OR trim(coalesce(j.city_canonical,''))=$location) "
        "WITH r,count(j) AS recentCount RETURN max(recentCount) AS maxRecentPostings",
        {"periods": sorted(recent_market_periods), "location": (location or "").strip()},
    )
    max_recent_postings = max(
        int((recent_reference[0] if recent_reference else {}).get("maxRecentPostings") or 0),
        1,
    )
    occupations = []
    for row in role_rows:
        raw_points = [
            {
                "period": str(point.get("period") or ""),
                "value": float(point.get("value") or 0),
                "sampleSize": int(point.get("sampleSize") or point.get("value") or 0),
            }
            for point in row.get("points") or []
            if float(point.get("value") or 0) > 0
        ]
        normalized = _normalize_role_demand_points(raw_points, market_rows, max_recent_postings)
        curve = _forecast_curve(normalized, horizon, factor, granularity)
        occupations.append({
            "roleId": str(row.get("roleId") or ""),
            "roleName": str(row.get("roleName") or ""),
            "industry": str(row.get("industry") or "其他"),
            "currentIndex": curve["current"],
            "changeRate": curve["relativeChange"],
            "confidence": curve["confidence"],
            "sampleSize": int(row.get("sampleSize") or 0),
            "modelSampleSize": curve["modelSampleSize"],
            "eligibleSampleSize": curve["eligibleSampleSize"],
            "sampleFloor": curve["sampleFloor"],
            "points": curve["points"],
        })
    occupations.sort(key=lambda item: (-item["currentIndex"], -item["sampleSize"], item["roleId"]))
    occupations = occupations[:6]

    pair_rows = _forecast_query(
        f"MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE {_published_role_clause()} "
        "AND coalesce(rel.active,true)=true AND toInteger(coalesce(rel.evidence_count,0)) >= 2 "
        "AND ($role_id='' OR r.role_id=$role_id) "
        "RETURN r.role_id AS roleId,r.role_name AS roleName,s.skill_id AS skillId,s.entity_name AS skill,"
        "toInteger(coalesce(rel.source_count,0)) AS sourceCount,toInteger(coalesce(rel.evidence_count,0)) AS evidenceCount,"
        "toInteger(coalesce(rel.total_role_postings,r.posting_count,0)) AS rolePostings "
        "ORDER BY rolePostings DESC,evidenceCount DESC,roleId,skillId LIMIT 72",
        {"role_id": role_id},
    )
    pairs = [
        {"roleId": str(item.get("roleId") or ""), "skillId": str(item.get("skillId") or "")}
        for item in pair_rows if item.get("roleId") and item.get("skillId")
    ]
    snapshot_rows = _forecast_query(
        "UNWIND $pairs AS pair "
        "MATCH (r:JobRole {role_id:pair.roleId})-[:HAS_DEMAND_SNAPSHOT]->(snap:SkillDemandSnapshot)-[:FOR_SKILL]->(s:Skill {skill_id:pair.skillId}) "
        "WHERE snap.granularity='month' AND snap.period =~ '\\d{4}-\\d{2}' "
        "RETURN r.role_id AS roleId,s.skill_id AS skillId,snap.period AS period,"
        "toFloat(coalesce(snap.penetration_rate,0))*100 AS value,toInteger(coalesce(snap.posting_count,0)) AS sampleSize "
        "ORDER BY roleId,skillId,period",
        {"pairs": pairs},
    ) if pairs else []
    snapshots_by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in snapshot_rows:
        snapshots_by_pair[(str(row.get("roleId") or ""), str(row.get("skillId") or ""))].append(row)
    pair_meta = {
        (str(item.get("roleId") or ""), str(item.get("skillId") or "")): item for item in pair_rows
    }
    skills = []
    for key, points in snapshots_by_pair.items():
        if len(points) < 18 or sum(int(item.get("sampleSize") or 0) for item in points) < 12:
            continue
        meta = pair_meta[key]
        curve = _standardize_skill_demand_curve(
            _forecast_curve(_smooth_skill_demand_points(points), horizon, factor, granularity)
        )
        future = curve.get("future", curve["current"])
        skills.append({
            "skillId": str(meta.get("skillId") or ""),
            "skill": str(meta.get("skill") or ""),
            "roleId": str(meta.get("roleId") or ""),
            "roleName": str(meta.get("roleName") or ""),
            "currentDemand": curve["current"],
            "futureDemand": future,
            "changePp": round(future - curve["current"], 1),
            "confidence": curve["confidence"],
            "modelSampleSize": curve["modelSampleSize"],
            "eligibleSampleSize": curve["eligibleSampleSize"],
            "sampleFloor": curve["sampleFloor"],
            "drivers": [
                f"{int(meta.get('evidenceCount') or 0)} 条技能证据",
                f"{int(meta.get('sourceCount') or 0)} 个数据来源",
                f"最近观测 {max(str(item.get('period') or '') for item in points)}",
            ],
            "points": curve["points"],
        })
    skills.sort(key=lambda item: (-abs(item["changePp"]), -item["currentDemand"], item["skillId"]))
    hot_skill_source = list(skills)
    if role_id:
        trend_skill_ids = [
            str(item.get("skillId") or "")
            for item in evolution_trends(role_id, granularity).get("series", [])
            if item.get("skillId")
        ]
        skills_by_id = {item["skillId"]: item for item in skills}
        skills = [skills_by_id[skill_id] for skill_id in trend_skill_ids if skill_id in skills_by_id][:12]
    else:
        skills = skills[:12]

    industries = _industry_pulses(location)

    hot_grouped: dict[str, list[dict]] = defaultdict(list)
    for item in hot_skill_source:
        hot_grouped[item["skill"]].append(item)
    trend_by_skill = {
        name: round(sum(item["changePp"] for item in items) / len(items), 1)
        for name, items in hot_grouped.items()
    }
    weighted_hot_rows = _forecast_query(
        f"MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) WHERE {_published_role_clause()} "
        "AND coalesce(rel.active,true)=true AND toInteger(coalesce(rel.evidence_count,0)) >= 2 "
        "AND ($role_id='' OR r.role_id=$role_id) "
        "OPTIONAL MATCH (j:JobPosting)-[:INSTANCE_OF]->(r) "
        "WHERE $location='' OR trim(coalesce(j.city_canonical,''))=$location "
        "WITH r,rel,s,count(DISTINCT j) AS postingWeight "
        "WHERE postingWeight > 0 "
        "WITH s,sum(postingWeight * toFloat(coalesce(rel.penetration_rate,0))) AS weightedDemand,"
        "sum(postingWeight) AS totalPostings,count(DISTINCT r) AS roleCount "
        "WHERE totalPostings > 0 "
        "RETURN s.entity_name AS name,weightedDemand / totalPostings * 100 AS heat,roleCount,totalPostings "
        "ORDER BY heat DESC,roleCount DESC,name LIMIT 12",
        {"role_id": role_id, "location": (location or "").strip()},
    )
    hot_skills = [
        {
            "name": str(item.get("name") or ""),
            "heat": round(max(0.0, min(float(item.get("heat") or 0), 100.0))),
            "change": trend_by_skill.get(str(item.get("name") or ""), 0.0),
            "roleCount": int(item.get("roleCount") or 0),
        }
        for item in weighted_hot_rows
        if item.get("name")
    ]

    periods = [str(point.get("period") or "") for row in role_rows for point in row.get("points") or []]
    training_window = f"{min(periods)} 至 {max(periods)}" if periods else "无有效训练窗口"
    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "horizon": horizon,
        "scenario": scenario,
        "granularity": granularity,
        "scopeRoleId": role_id,
        "scopeLocation": (location or "").strip(),
        "scopeKeyword": normalized_keyword,
        "source": "model",
        "modelVersion": "job-posting-market-share-eb-theilsen-v2.0",
        "trainingWindow": training_window,
        "occupations": occupations,
        "skills": skills,
        "emergingRoles": _forecast_emerging_roles(db, horizon),
        "industries": industries[:5],
        "hotSkills": hot_skills[:12],
        "notice": "岗位热度先按同月全市场招聘样本份额校正采集规模，再对稀疏月份进行经验贝叶斯收缩和稳健趋势预测；计算结果不写回图谱，新岗位信号仍须人工复核。",
    }


def skill_lexicon() -> list[dict]:
    from .linker import ACTIVE_LINKER

    active = ACTIVE_LINKER.get()
    if active is not None:
        return [
            {"id": item["id"], "name": item["name"], "aliases": sorted(
                {item["name"], *item["aliases"]}, key=len, reverse=True)}
            for item in active.entities.get("Skill", {}).values()
        ]
    return _legacy_skill_lexicon()


@lru_cache(maxsize=1)
def _legacy_skill_lexicon() -> list[dict]:
    rows = neo4j.query(
        "MATCH (s:Skill) RETURN s.skill_id AS id,s.entity_name AS name,s.aliases_canonical AS aliases"
    )
    items = []
    for row in rows:
        names = [row["name"]]
        if row.get("aliases"):
            names.extend(part.strip() for part in str(row["aliases"]).split(";") if part.strip())
        items.append({"id": row["id"], "name": row["name"], "aliases": sorted(set(names), key=len, reverse=True)})
    return sorted(items, key=lambda item: max(map(len, item["aliases"])), reverse=True)


@lru_cache(maxsize=16384)
def _is_ascii_alias(alias: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_+#.\-/ ]+", alias))


def _ascii_fold(value: str) -> str:
    return value.casefold().replace("0", "o")


def _alias_span(text: str, alias: str) -> tuple[int, int] | None:
    if not _is_ascii_alias(alias):
        start = text.casefold().find(alias.casefold())
        return (start, start + len(alias)) if start >= 0 else None
    folded_text = _ascii_fold(text)
    folded_alias = _ascii_fold(alias)
    start = folded_text.find(folded_alias)
    while start >= 0:
        end = start + len(folded_alias)
        before_ok = start == 0 or not folded_text[start - 1].isalnum()
        after_ok = end == len(folded_text) or not folded_text[end].isalnum()
        if before_ok and after_ok:
            return start, end
        start = folded_text.find(folded_alias, start + 1)
    return None


def _find_alias(text: str, aliases: list[str]) -> str | None:
    for alias in aliases:
        if len(alias.strip()) < 2:
            continue
        if _alias_span(text, alias):
            return alias
    return None


def extract_skills(text: str) -> list[dict]:
    from .linker import ACTIVE_LINKER

    active = ACTIVE_LINKER.get()
    if active is not None:
        return active.extract_skills(text)
    found: list[dict] = []
    occupied: set[str] = set()
    sentences = [part.strip() for part in re.split(r"[\n。；;]", text) if part.strip()]
    for item in skill_lexicon():
        matched = _find_alias(text, item["aliases"])
        if not matched or item["id"] in occupied:
            continue
        evidence = next((sentence for sentence in sentences if _alias_span(sentence, matched)), "")
        canonical_match = matched.casefold() == str(item["name"]).casefold()
        found.append({"skill_id": item["id"], "skill_name": item["name"], "evidence": evidence[:300], "confidence": 0.96 if canonical_match else 0.9})
        occupied.add(item["id"])
        if len(found) >= 80:
            break
    return found


@lru_cache(maxsize=1024)
def role_skill_ids_for_title(title: str) -> set[str]:
    if not title:
        return set()
    rows = neo4j.query(
        "MATCH (j:JobPosting {job_title_canonical:$title})-[:INSTANCE_OF]->(r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) "
        "WHERE rel.valid_to IS NULL AND coalesce(rel.active,true)=true "
        "RETURN collect(DISTINCT s.skill_id) AS ids",
        {"title": title},
    )
    return set(rows[0].get("ids") or []) if rows else set()


def _jd_section(text: str, start: str, end: str = "") -> str:
    match = re.search(start, text, flags=re.IGNORECASE)
    if not match:
        return text
    section = text[match.end():]
    if end:
        next_match = re.search(end, section, flags=re.IGNORECASE)
        if next_match:
            section = section[:next_match.start()]
    return section.strip(" ：:，,。；;\n")


def _parse_salary_range(text: str) -> tuple[float | None, float | None, str]:
    # Prefer a labelled salary field in compact cards, avoiding an unrelated
    # amount mentioned in the source footer or benefits section.
    labelled = re.search(r"(?:薪资|薪酬|工资|待遇)\s*[:：]\s*([^。；;\n]{2,40})", text, flags=re.IGNORECASE)
    if labelled:
        scoped = _parse_salary_range(labelled.group(1)) if labelled.group(1).strip() != text.strip() else (None, None, "")
        if scoped[0] is not None:
            return scoped[0], scoped[1], scoped[2]
    # Explicit-unit pass runs first. This prevents dates/codes from being
    # interpreted as salary while covering annual, monthly, K and yuan forms.
    unit = r"(?:万(?:元)?\s*(?:/\s*)?(?:月|年)?|[kK]\s*(?:/\s*月)?|千(?:元)?\s*(?:/\s*)?月|元\s*(?:/\s*)?(?:月|天|年))"
    range_match = re.search(
        rf"(?<![\dA-Za-z])(?P<low>\d+(?:\.\d+)?)\s*[-~至到]\s*(?P<high>\d+(?:\.\d+)?)\s*(?P<unit>{unit})",
        text,
    )
    single_match = None if range_match else re.search(
        rf"(?<![\dA-Za-z])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{unit})", text
    )
    match = range_match or single_match
    if match:
        unit_text = match.group("unit").replace(" ", "")
        scale = 10000.0 / 12 if "万" in unit_text and "年" in unit_text else 10000.0 if "万" in unit_text else 1000.0 if ("千" in unit_text or "k" in unit_text.lower()) else 21.75 if "天" in unit_text else 1.0
        low = float(match.group("low")) if range_match else float(match.group("value"))
        high = float(match.group("high")) if range_match else low
        return low * scale, high * scale, match.group(0)
    # Require an explicit salary unit so dates and job codes are not parsed as
    # patterns below. Values are normalized to monthly RMB.
    month = chr(0x6708)
    year = chr(0x5e74)
    wan = chr(0x4e07)
    yuan = chr(0x5143)
    thousand = chr(0x5343)
    range_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*([^，,。；;\s]{0,8}(?:/\s*\S+)?|)")
    for match in range_pattern.finditer(text):
        suffix = match.group(3)
        low, high = float(match.group(1)), float(match.group(2))
        if "K" in suffix.upper() or thousand in suffix:
            return low * 1000, high * 1000, match.group(0)
        if wan in suffix and year in suffix:
            return low * 10000 / 12, high * 10000 / 12, match.group(0)
        if yuan in suffix and month in suffix:
            return low, high, match.group(0)
    single_pattern = re.compile(r"(?<![-\d])(\d+(?:\.\d+)?)\s*([^，,。；;\s]{0,8}(?:/\s*\S+)?|)")
    for match in single_pattern.finditer(text):
        suffix = match.group(2)
        value = float(match.group(1))
        if "K" in suffix.upper() or thousand in suffix:
            return value * 1000, value * 1000, match.group(0)
        if yuan in suffix and month in suffix:
            return value, value, match.group(0)
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*[kK千](?:/月|元/月)?", 1000.0),
        (r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*万(?:元)?\s*/?\s*年", 10000.0 / 12),
        (r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*元\s*/?\s*月", 1.0),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1)) * multiplier, float(match.group(2)) * multiplier, match.group(0)
    return None, None, ""


def _parse_experience(text: str) -> tuple[float | None, float | None, str]:
    # Internship/campus wording is an explicit zero-year requirement. Keep
    # this ahead of the numeric matcher so years in dates or job codes cannot
    # become experience values.
    if re.search(r"经验\s*(?:要求\s*[:：]?\s*)?(不限|无要求)|不限经验|无经验要求|应届生|校招", text, flags=re.IGNORECASE):
        match = re.search(r"[^。；;\n]{0,20}(?:经验\s*(?:要求\s*[:：]?\s*)?(?:不限|无要求)|不限经验|无经验要求|应届生|校招)[^。；;\n]{0,20}", text, flags=re.IGNORECASE)
        return 0.0, 0.0, match.group(0) if match else "经验不限"
    # Only accept a number directly tied to 年/年以上/工作经验. A bounded
    # look-behind prevents a YYYY-MM date or an alphanumeric job code from
    # being interpreted as an experience requirement.
    # Strip date tokens first; a deadline such as 2027年05月07日 is not an
    # experience requirement. Recruitment experience is conventionally within
    # 0-50 years, which also rejects year-like IDs and publication dates.
    normalized = re.sub(r"\b\d{4}[-/.年]\s*\d{1,2}(?:[-/.月]\s*\d{1,2}日?)?", " ", text)
    pattern = r"(?<![\dA-Za-z])(?P<min>\d{1,2}(?:\.\d+)?)\s*(?:[-~至]\s*(?P<max>\d{1,2}(?:\.\d+)?)\s*)?年\s*(?:以上|及以上|经验|工作经验)?"
    match = re.search(pattern, normalized, flags=re.IGNORECASE)
    if match:
        evidence = match.group(0)
        return float(match.group("min")), float(match.group("max")) if match.group("max") else None, evidence
    return None, None, ""


_CITY_NAMES = (
    "北京 上海 天津 重庆 广州 深圳 杭州 南京 苏州 成都 武汉 西安 长沙 郑州 合肥 青岛 厦门 宁波 无锡 "
    "东莞 佛山 珠海 福州 济南 沈阳 哈尔滨 昆明 贵阳 南昌 石家庄 海口 三亚 太原 兰州 乌鲁木齐 "
    "呼和浩特 银川 西宁 拉萨 长春 大连 烟台 惠州 中山 常州 嘉兴 金华 徐州 温州 泉州 南通 "
    "绍兴 台州 芜湖 蚌埠 洛阳 宜昌 襄阳 株洲 岳阳 衡阳 桂林 柳州 绵阳 德阳 乐山 莆田 "
    "漳州 汕头 江门 湛江 肇庆 清远 潍坊 临沂 淄博 保定 唐山 秦皇岛 廊坊 鄂尔多斯 "
    "张家口 衢州 盐城 扬州 泰州 镇江 葫芦岛 吉林 鞍山"
).split()


def _canonical_education(value: str) -> str:
    """Return a stable level used by the API and field-level evaluation."""
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not value or value in {"未知", "缺失", "missing", "none"}:
        return ""
    if re.search(r"不限|无要求|不限制|无需学历|学历不限", value):
        return "不限"
    if "博士" in value:
        return "博士"
    if "硕士" in value or "研究生" in value:
        return "硕士"
    if "本科" in value or "学士" in value:
        return "本科"
    if "大专" in value or "专科" in value or "高职" in value:
        return "专科"
    if "中专" in value or "高中" in value:
        return "高中/中专"
    return value


def _extract_city(text: str) -> tuple[str, str]:
    labels = r"(?:工作地点|工作地|地点|城市|办公地点|办公地|工作地址)"
    label_match = re.search(
        rf"{labels}\s*[:：]?\s*([^，,。；;\n]{{2,30}}?)(?=\s+(?:工作地址|工作地点|工作地|地点|城市|办公地点|办公地|学历|教育背景|经验|工作经验|薪资|职位要求|岗位要求)\s*[:：]?|$)",
        text,
        flags=re.IGNORECASE,
    )
    candidate = label_match.group(1) if label_match else text[:500]
    for name in _CITY_NAMES:
        if name in candidate:
            return name, label_match.group(0) if label_match else name
    # Handle arbitrary Chinese city names not in the compact lexicon, while
    # avoiding a greedy capture of the whole address/company suffix.
    city_match = re.search(r"([\u4e00-\u9fff]{2,8})市", candidate)
    if city_match:
        return city_match.group(1), label_match.group(0) if label_match else city_match.group(0)
    if label_match:
        return candidate.strip(" ，,。；;"), label_match.group(0)
    return "", ""


def parse_jd(text: str) -> dict:
    raw_text = str(text or "")
    cleaned = re.sub(r"\s+", " ", raw_text).strip()
    section_marker = r"职位要求|岗位要求|职位描述|岗位描述|岗位职责|岗位说明|工作职责|任职要求|任职资格|资格要求|职位介绍|公司简介|薪资福利|福利待遇|工作地点|城市|办公地点|薪资"
    explicit_title = re.search(
        rf"(?:职位|岗位)(?:名称|名)?\s*[:：]\s*([^。；;\n]+?)(?=\s*(?:{section_marker})\s*[:：]?|$)",
        cleaned,
        re.IGNORECASE,
    )
    title = explicit_title.group(1) if explicit_title else re.split(section_marker, cleaned, maxsplit=1)[0]
    title = re.split(r"\s+(?=(?:工作地址|工作地点|工作地|城市|学历(?:要求)?|教育背景|经验(?:要求)?|工作经验|薪资(?:待遇)?|职位要求|岗位要求)\s*[:：]?)", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = re.split(r"\s+(?=(?:\d+[.、)）]|[一二三四五六七八九十]+、|【(?:本科|硕士|博士|岗位)))", title, maxsplit=1)[0]
    title = re.split(r"\s+专业\s*[:：]", title, maxsplit=1)[0]
    title = re.sub(r"^(职位名称|岗位名称|职位|岗位)[:：]?\s*", "", title).strip(" ：:，,。；;")[:80]
    title = unicodedata.normalize("NFKC", title)
    title = re.sub(r"[（(](?:校招|社招|急聘|应届生|实习生?|[^）)]*方向|M?J\d{4,})[）)]", "", title, flags=re.IGNORECASE).strip()

    requirement_text = _jd_section(cleaned, r"(?:任职要求|任职资格|岗位要求|职位要求|资格要求)", r"(?:岗位职责|职位描述|工作职责|薪资福利|福利待遇|公司简介)")
    education_scope = requirement_text or cleaned
    # Compact source cards often put education/experience before the
    # requirements section; retain the full text as a fallback in that case.
    labelled_education = re.search(r"(?:学历|教育背景)\s*(?:要求)?\s*[:：]\s*([^。；;\n]{1,30})", cleaned, flags=re.IGNORECASE)
    unlimited_education = re.search(r"(?:学历|教育背景)\s*(?:要求)?\s*[:：]?\s*(?:不限|无要求|不限制)", cleaned, flags=re.IGNORECASE)
    education_match = re.search(r"(?:学历|教育背景)?\s*[:：]?\s*(博士|硕士|研究生|本科|大专|专科|高职|高中|中专)(?:及以上|以上)?", labelled_education.group(1) if labelled_education else education_scope, flags=re.IGNORECASE)
    if not unlimited_education and not education_match and requirement_text:
        education_match = re.search(r"(?:学历|教育背景)?\s*[:：]?\s*(博士|硕士|研究生|本科|大专|专科|高职|高中|中专)(?:及以上|以上)?", cleaned, flags=re.IGNORECASE)
    education_evidence = unlimited_education.group(0) if unlimited_education else education_match.group(0) if education_match else ""
    education = "不限" if unlimited_education else _canonical_education(education_match.group(0) if education_match else "")
    labelled_experience = re.search(r"(?:经验|工作经验)\s*(?:要求)?\s*[:：]\s*([^。；;\n]{1,30})", cleaned, flags=re.IGNORECASE)
    experience_min, experience_max, experience_evidence = _parse_experience(labelled_experience.group(1) if labelled_experience else requirement_text or cleaned)
    if experience_min is None and requirement_text:
        experience_min, experience_max, experience_evidence = _parse_experience(cleaned)
    salary_min, salary_max, salary_evidence = _parse_salary_range(cleaned)

    city, city_evidence = _extract_city(cleaned)

    responsibility_text = _jd_section(cleaned, r"(?:岗位职责|职位描述|工作职责|工作内容)", r"(?:任职要求|任职资格|岗位要求|职位要求|资格要求|薪资福利|福利待遇)")
    sentences = [part.strip(" -·•") for part in re.split(r"[。；;\n]|\s+(?=\d+[.、)])", responsibility_text) if part.strip()]
    responsibilities = [item[:300] for item in sentences][:12]
    skills = extract_skills(raw_text)
    return {
        "title": title,
        "titleEvidence": explicit_title.group(0) if explicit_title else title,
        "city": city,
        "cityEvidence": city_evidence or city,
        "education": education,
        "educationEvidence": education_evidence,
        "experienceMinYears": experience_min,
        "experienceMaxYears": experience_max,
        "experienceEvidence": experience_evidence,
        "salaryMonthlyMin": salary_min,
        "salaryMonthlyMax": salary_max,
        "salaryEvidence": salary_evidence,
        "responsibilities": responsibilities,
        "responsibilityEvidence": responsibilities,
        "skills": skills,
        "skillEvidence": [item.get("evidence", "") for item in skills],
        "evidenceCount": len(responsibilities) + len(skills) + sum(bool(item) for item in (education_evidence, experience_evidence, salary_evidence, city)),
        "notice": "字段、证据句和技能均来自输入文本；技能 ID 仅允许使用本地图谱规范词表。",
    }


def normalize_ocr_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cjk = r"\u3400-\u4dbf\u4e00-\u9fff"
    punctuation = "：，。；、！？（）【】"
    text = re.sub(rf"(?<=[{cjk}]) +(?=[{cjk}{punctuation}])", "", text)
    text = re.sub(rf"(?<=[{punctuation}]) +(?=[{cjk}])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def windows_ocr_pdf(path: Path, max_pages: int = 8) -> dict:
    import base64
    import fitz

    script = Path(__file__).with_name("windows_ocr.ps1")
    if not script.exists():
        raise RuntimeError("Windows OCR adapter is missing")
    with tempfile.TemporaryDirectory(prefix="career-insight-ocr-") as temp_directory:
        image_paths: list[Path] = []
        with fitz.open(str(path)) as document:
            for index, page in enumerate(list(document)[:max_pages]):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
                image_path = Path(temp_directory) / f"page-{index + 1:03d}.png"
                pixmap.save(str(image_path))
                image_paths.append(image_path)
        if not image_paths:
            raise ValueError("PDF has no renderable pages")
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *[str(item) for item in image_paths],
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        encoded_payload = completed.stdout.strip().lstrip("\ufeff")
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    pages = payload.get("pages") or []
    text = normalize_ocr_text("\n".join(str(item.get("text") or "") for item in pages))
    return {
        "text": text,
        "engine": payload.get("engine") or "windows-media-ocr",
        "language": payload.get("language") or "",
        "pages": len(pages),
    }


def rapidocr_pdf(path: Path, max_pages: int = 8) -> dict:
    import fitz
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    pages = []
    with fitz.open(str(path)) as document:
        for page in list(document)[:max_pages]:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            result, _ = ocr(pixmap.tobytes("png"))
            if result:
                pages.append("\n".join(str(item[1]) for item in result if len(item) > 1))
    return {
        "text": normalize_ocr_text("\n".join(pages)),
        "engine": "rapidocr-onnxruntime",
        "language": "zh-Hans-CN+en",
        "pages": len(pages),
    }


def parse_resume(path: Path) -> dict:
    suffix = path.suffix.lower()
    text = ""
    warnings: list[str] = []
    ocr_metadata = {"engine": "digital-text", "language": "", "pages": 0}
    if suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
        if len(text.strip()) < 80:
            failures = []
            for extractor in (windows_ocr_pdf, rapidocr_pdf):
                try:
                    ocr_result = extractor(path)
                    if ocr_result["text"]:
                        text = ocr_result["text"]
                        ocr_metadata = {
                            "engine": ocr_result["engine"],
                            "language": ocr_result["language"],
                            "pages": ocr_result["pages"],
                        }
                        warnings.append(
                            f"扫描版 PDF 已使用 {ocr_metadata['engine']} 识别；请核对技能证据和数字信息。"
                        )
                        break
                except Exception as exc:
                    failures.append(f"{extractor.__name__}:{type(exc).__name__}")
            if len(text.strip()) < 20:
                warnings.append(
                    "扫描版 PDF 未识别到足够文本，请改用清晰扫描件或手工填写。"
                    + (f" OCR 状态：{', '.join(failures)}。" if failures else "")
                )
    elif suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    elif suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError("仅支持 PDF、DOCX 和 TXT 文件")
    education_match = re.search(r"(博士|硕士|研究生|本科|大专|专科|高中)", text)
    experience_match = re.search(r"(\d+(?:\.\d+)?)\s*年(?:[\u4e00-\u9fff]{0,8})?经验", text)
    if not experience_match:
        experience_match = re.search(r"(?:工作经验|经验年限|从业年限)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*年", text)
    certificates = sorted(set(re.findall(r"([\w\u4e00-\u9fff-]{2,30}(?:证书|认证))", text)))[:20]
    return {
        "text": text,
        "education": education_match.group(1) if education_match else "",
        "experienceYears": float(experience_match.group(1)) if experience_match else None,
        "certificates": certificates,
        "skills": extract_skills(text),
        "warnings": warnings,
        "ocr": ocr_metadata,
    }


def _importance(skill: dict) -> float:
    penetration = float(skill.get("weight") or 0)
    source_factor = min(int(skill.get("sourceCount") or 0) / 3, 1)
    evidence_factor = min(int(skill.get("evidenceCount") or 0) / 5, 1)
    confidence = {"high": 1.0, "medium": 0.75, "low": 0.5}.get(str(skill.get("confidence", "medium")).lower(), 0.7)
    return round(0.45 * penetration + 0.2 * source_factor + 0.2 * evidence_factor + 0.15 * confidence, 4)


def calculate_match(
    role: dict,
    user_skills: list[str],
    education: str = "",
    experience_years: float | None = None,
    certificates: list[str] | None = None,
) -> dict:
    normalized = {item.casefold().strip() for item in user_skills if item.strip()}
    gaps = []
    skill_weight_sum = 0.0
    skill_score_sum = 0.0
    for skill in role.get("skills", []):
        if not skill.get("id") or not skill.get("name"):
            continue
        importance = _importance(skill)
        level = "core" if importance >= 0.62 else "advanced" if importance >= 0.4 else "bonus"
        matched = skill["name"].casefold() in normalized
        aliases = [part.casefold() for part in str(skill.get("aliases") or "").split(";")]
        partial = not matched and any(alias and alias in normalized for alias in aliases)
        ratio = 1.0 if matched else 0.6 if partial else 0.0
        skill_weight_sum += importance
        skill_score_sum += importance * ratio
        gaps.append(
            {
                "skillId": skill["id"],
                "skill": skill["name"],
                "status": "matched" if matched else "partial" if partial else "missing",
                "level": level,
                "importance": round(importance * 100, 1),
                "jobEvidence": skill.get("evidence") or "",
                "sourceUrls": str(skill.get("urls") or "").split(";")[:3],
            }
        )
    coverage_score = (skill_score_sum / skill_weight_sum * 100) if skill_weight_sum else 0
    skill_score = coverage_score
    breadth_score = role_skill_breadth_score(gaps)
    dimensions = [("skills", 70.0, skill_score)]
    education_profile = education_match_profile(role, education)
    radar_targets = role_radar_targets(role)
    if education_profile:
        dimensions.append(("education", 10.0, education_profile["matchScore"]))
    if experience_years is not None:
        experience_reference = max(3.0, float(role.get("experienceRequirementMinYears") or 0.0))
        dimensions.append(("experience", 15.0, min(max(experience_years, 0.0) / experience_reference, 1) * 100))
    if certificates:
        dimensions.append(("certificates", 5.0, min(len(certificates), 2) / 2 * 100))
    available_weight = sum(item[1] for item in dimensions)
    total = sum(weight * value for _, weight, value in dimensions) / available_weight
    result = {
        "roleId": role["id"],
        "roleName": role["name"],
        "score": round(total, 1),
        "skillScore": round(skill_score, 1),
        "breadthScore": breadth_score,
        "experienceRequirementMinYears": round(float(role.get("experienceRequirementMinYears") or 0.0), 1),
        "dimensions": [{"name": name, "weight": round(weight / available_weight * 100, 1), "score": round(value, 1)} for name, weight, value in dimensions],
        "gaps": sorted(gaps, key=lambda item: item["importance"], reverse=True),
        "algorithmVersion": "match-v3-role-weighted-coverage",
        "radarVersion": "radar-v2-role-profile",
        "radarTargets": radar_targets,
        "notice": "未提供的个人维度未按零分处理；结果仅用于能力发展参考。",
    }
    if education_profile:
        result["educationProfile"] = education_profile
    if experience_years is not None:
        result["experienceProfile"] = {
            "providedYears": round(max(experience_years, 0.0), 1),
            "requiredYears": round(float(role.get("experienceRequirementMinYears") or 0.0), 1),
            "current": _clamp_percent(min(max(experience_years, 0.0), 8.0) / 8 * 100),
            "target": radar_targets["experience"],
        }
    return result


def rank_role_candidates(roles: list[dict], user_skills: list[str], profile_limit: int = 20) -> dict[str, float]:
    normalized = {item.casefold().strip() for item in user_skills if item.strip()}
    if not roles or not normalized:
        return {role["id"]: 0.0 for role in roles}
    profiles: dict[str, list[dict]] = {}
    document_frequency: dict[str, int] = {}
    for role in roles:
        profile = sorted(
            [skill for skill in role.get("skills", []) if skill.get("id") and skill.get("name")],
            key=_importance,
            reverse=True,
        )[:profile_limit]
        profiles[role["id"]] = profile
        for name in {skill["name"].casefold().strip() for skill in profile}:
            document_frequency[name] = document_frequency.get(name, 0) + 1

    role_count = len(roles)

    def inverse_frequency(name: str) -> float:
        return math.log((role_count + 1) / (document_frequency.get(name, 0) + 1)) + 1

    user_norm = math.sqrt(sum(inverse_frequency(name) ** 2 for name in normalized)) or 1.0
    scores: dict[str, float] = {}
    for role in roles:
        weights = {
            skill["name"].casefold().strip(): _importance(skill) * inverse_frequency(skill["name"].casefold().strip())
            for skill in profiles[role["id"]]
        }
        dot_product = sum(weights[name] * inverse_frequency(name) for name in normalized if name in weights)
        role_norm = math.sqrt(sum(value**2 for value in weights.values())) or 1.0
        scores[role["id"]] = round(dot_product / (role_norm * user_norm) * 100, 1)
    return scores


def save_match(db: Session, result: dict, resume_id: str = "") -> MatchReport:
    report = MatchReport(
        resume_id=resume_id,
        role_id=result["roleId"],
        role_name=result["roleName"],
        score=result["score"],
        result=result,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def create_learning_path(db: Session, report: MatchReport, existing: LearningPath | None = None) -> LearningPath:
    missing = sorted(
        [item for item in report.result.get("gaps", []) if item["status"] != "matched"],
        key=lambda item: (item.get("level") != "core", -float(item.get("importance") or 0)),
    )
    skill_ids = [item["skillId"] for item in missing[:12]]
    resources = neo4j.query(
        "MATCH (s:Skill) WHERE s.skill_id IN $ids "
        "OPTIONAL MATCH (s)-[:IS_SUBSKILL_OF]->(pre:Skill) "
        "OPTIONAL MATCH (course:Course)-[:TEACHES_SKILL]->(s) "
        "OPTIONAL MATCH (certificate:Certificate)-[:VALIDATES_SKILL]->(s) "
        "RETURN s.skill_id AS skillId,collect(DISTINCT pre.entity_name)[0..3] AS prerequisites,"
        "collect(DISTINCT CASE WHEN course IS NULL THEN NULL ELSE {"
        "name:coalesce(course.course_name,course.entity_name),url:coalesce(course.source_url,''),"
        "provider:coalesce(course.provider_canonical,course.source_site,'')} END)[0..3] AS courses,"
        "collect(DISTINCT coalesce(certificate.certificate_name,certificate.entity_name))[0..3] AS certificates",
        {"ids": skill_ids},
    ) if skill_ids else []
    resource_map = {item["skillId"]: item for item in resources}
    groups = [missing[:3], missing[3:7], missing[7:12]]
    labels = [
        ("基础补齐", "1-2 周", 6),
        ("项目强化", "3-6 周", 8),
        ("能力证明", "7-10 周", 6),
    ]
    task_templates = [
        [
            ("第 1 周", "建立知识基线", "梳理概念、岗位应用场景和前置关系，形成可复习的能力地图。"),
            ("第 2 周", "完成单项练习", "逐项完成最小可运行练习，记录输入、输出、错误与修正过程。"),
        ],
        [
            ("第 3-4 周", "跟练与复现", "结合图谱课程或公开文档复现典型任务，并为关键步骤补充说明。"),
            ("第 5-6 周", "完成组合项目", "把本阶段技能组合到同一项目中，补齐测试、异常处理和运行文档。"),
        ],
        [
            ("第 7-8 周", "岗位任务模拟", "按照目标岗位常见任务独立完成一次限时实践，并记录质量与效率指标。"),
            ("第 9 周", "查漏补缺", "根据失败记录回补薄弱点，重新完成未通过的练习和项目检查项。"),
            ("第 10 周", "形成能力证明", "整理作品、学习记录与可验证结果，形成面向目标岗位的能力说明。"),
        ],
    ]
    stages = []
    for index, group in enumerate(groups):
        if group:
            stage_resources = [resource_map.get(item["skillId"], {}) for item in group]
            skill_names = [item["skill"] for item in group]
            skill_text = "、".join(skill_names)
            prerequisites = sorted({name for resource in stage_resources for name in resource.get("prerequisites", []) if name})
            course_map: dict[tuple[str, str], dict] = {}
            for resource in stage_resources:
                for course in resource.get("courses", []):
                    if isinstance(course, dict):
                        name = str(course.get("name") or "").strip()
                        url = str(course.get("url") or "").strip()
                        provider = str(course.get("provider") or "").strip()
                    else:
                        name, url, provider = str(course or "").strip(), "", ""
                    if name:
                        course_map[(name, url)] = {"name": name, "url": url, "provider": provider}
            courses = sorted(course_map.values(), key=lambda item: (item["name"], item["url"]))
            certificates = sorted({name for resource in stage_resources for name in resource.get("certificates", []) if name})
            weekly_tasks = [
                {
                    "period": period,
                    "title": title,
                    "actions": [detail, f"重点覆盖：{skill_text}。"],
                    "deliverable": (
                        f"{skill_text} 的知识地图与练习记录"
                        if index == 0
                        else f"可复现的{report.role_name}实践项目与运行说明"
                        if index == 1
                        else f"{report.role_name}能力证明材料与复盘清单"
                    ),
                }
                for period, title, detail in task_templates[index]
            ]
            stages.append({
                "stage": index + 1,
                "name": labels[index][0],
                "duration": labels[index][1],
                "estimatedHoursPerWeek": labels[index][2],
                "goal": f"围绕{report.role_name}补齐并验证 {skill_text}，按阶段完成学习、练习与成果复核。",
                "skills": skill_names,
                "prerequisites": prerequisites,
                "courses": courses,
                "certificates": certificates,
                "weeklyTasks": weekly_tasks,
                "practiceProject": (
                    f"完成一个覆盖 {skill_text} 的最小实践任务，并保留操作记录。"
                    if index == 0
                    else f"完成一个面向{report.role_name}真实工作场景的组合项目，覆盖 {skill_text}。"
                    if index == 1
                    else f"以 {skill_text} 为重点完成岗位任务模拟，整理为可展示、可复核的能力证据。"
                ),
                "acceptanceCriteria": [
                    f"能够说明 {skill_text} 在{report.role_name}中的用途、输入输出与常见边界。",
                    "每项技能至少完成 1 个可复现练习，并保留结果、问题和修正记录。",
                    "阶段产物包含运行步骤、自检结果和下一阶段待改进项。",
                ],
                "outcome": f"完成 {len(group)} 项优先能力的学习、实践与证据沉淀。",
                "planVersion": "learning-v3-linked-courses",
            })
    path = existing or LearningPath(match_report_id=report.id)
    path.stages = stages
    db.add(path)
    db.commit()
    db.refresh(path)
    return path


def recommend_roles(user_skills: list[str], limit: int = 10) -> list[dict]:
    rows = neo4j.query(
        "MATCH (r:JobRole) OPTIONAL MATCH (r)-[rel:REQUIRES_SKILL]->(s:Skill) "
        "WITH r,collect({id:s.skill_id,name:s.entity_name,weight:toFloat(rel.penetration_rate),"
        "sourceCount:toInteger(rel.source_count),evidenceCount:toInteger(rel.evidence_count),confidence:rel.confidence}) AS skills "
        "RETURN r.role_id AS id,r.role_name AS name,r.posting_count AS postingCount,skills "
        "ORDER BY coalesce(toInteger(r.posting_count), 0) DESC LIMIT 300"
    )
    ranking_scores = rank_role_candidates(rows, user_skills)
    recommendations = []
    for role in rows:
        result = calculate_match(role, user_skills)
        recommendations.append({
            "roleId": role["id"],
            "roleName": role["name"],
            "score": ranking_scores.get(role["id"], 0.0),
            "skillScore": result["skillScore"],
            "topGaps": [item["skill"] for item in result["gaps"] if item["status"] != "matched"][:3],
            "algorithmVersion": "recommend-v2-tfidf-evidence",
        })
    return sorted(recommendations, key=lambda item: item["score"], reverse=True)[:limit]


def rule_agent_answer(context: dict, provider_reason: str = "provider_unavailable") -> str:
    if not context:
        return "当前问题没有可引用的岗位、趋势或匹配证据。请先选择岗位或完成能力诊断，我不会在无证据时推断。"
    missing = [item["skill"] for item in context.get("gaps", []) if item.get("status") != "matched"][:5]
    answer = f"当前岗位为{context.get('roleName', '目标岗位')}，"
    score = context.get("score")
    if score is None or str(score).strip() in {"", "--"}:
        answer += "尚未完成能力诊断。"
    else:
        answer += f"综合匹配度为{score}%。"
    if missing:
        answer += f"建议优先补齐：{'、'.join(missing)}。"
    fallback_messages = {
        "insufficient_credits": "当前 Coze 额度不足，已使用本地规则解释。",
        "authentication_failed": "当前 Coze 凭证不可用，已使用本地规则解释。",
        "rate_limited": "当前 Coze 请求频率受限，已使用本地规则解释。",
        "not_configured": "当前未配置外部智能体，已使用本地规则解释。",
    }
    fallback_message = fallback_messages.get(provider_reason, "当前外部智能体暂不可用，已使用本地规则解释。")
    return answer + f"以上结论来自本地图谱和匹配规则；{fallback_message}"


def _compact_agent_context(context: dict) -> dict:
    """Keep external agent context small and limited to user-visible evidence."""
    source = context if isinstance(context, dict) else {}
    graph = source.get("graphSummary") if isinstance(source.get("graphSummary"), dict) else {}
    skills = source.get("skills") or graph.get("skills") or []
    gaps = source.get("gaps") or []
    evolution = source.get("evolution") if isinstance(source.get("evolution"), dict) else {}
    events = evolution.get("events") or []
    learning = source.get("learningPath") if isinstance(source.get("learningPath"), dict) else {}
    stages = learning.get("stages") or []
    return {
        "roleId": source.get("roleId") or source.get("id") or "",
        "roleName": source.get("roleName") or source.get("name") or "",
        "field": source.get("field") or source.get("jobCategory") or "",
        "postingCount": source.get("postingCount") or source.get("postingsCount") or 0,
        "score": source.get("score"),
        "skills": [
            {
                "id": item.get("skillId") or item.get("id") or "",
                "name": item.get("skill") or item.get("name") or "",
                "weight": item.get("weight") or item.get("penetrationRate") or item.get("penetration_rate"),
                "status": item.get("status") or "required",
                "sourceUrls": [url for url in (item.get("sourceUrls") or str(item.get("urls") or "").split(";")[:3]) if url],
                "evidence": (item.get("jobEvidence") or item.get("evidence") or "")[:180],
                "confidence": item.get("confidence") or "approved",
            }
            for item in skills[:8]
            if isinstance(item, dict)
        ],
        "gaps": [
            {
                "name": item.get("skill") or item.get("name") or "",
                "status": item.get("status") or "missing",
                "sourceUrls": [url for url in (item.get("sourceUrls") or str(item.get("urls") or "").split(";")[:3]) if url],
                "evidence": (item.get("jobEvidence") or item.get("evidence") or "")[:180],
            }
            for item in gaps[:5]
            if isinstance(item, dict)
        ],
        "evolution": [
            {
                "name": item.get("skill") or item.get("name") or "",
                "period": item.get("period") or "",
                "change": item.get("change") or 0,
                "sampleSize": item.get("sampleSize") or 0,
                "comparisonEligible": bool(item.get("comparisonEligible")),
                "sourceUrls": [url for url in (item.get("sourceUrls") or str(item.get("urls") or "").split(";")[:2]) if url],
            }
            for item in events[:5]
            if isinstance(item, dict)
        ],
        "learningStages": [
            {"title": item.get("title") or "", "skills": item.get("skills") or []}
            for item in stages[:3]
            if isinstance(item, dict)
        ],
    }


def _coze_prompt(prompt: str, context: dict) -> str:
    compact = _compact_agent_context(context)
    evidence = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    return (
        "你是职能洞察平台的职业分析助手。只依据本地证据摘要回答，不要虚构岗位、技能、趋势或课程。"
        "证据不足时必须明确说明。使用简体中文，回答不超过 500 字，先给结论，再给依据和可执行建议；引用证据时使用 [E1]、[E2] 标记。\n\n"
        f"【本地证据摘要】{evidence}\n\n【用户问题】{prompt}"
    )


def _coze_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_coze_text(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or "")
    return ""


def _coze_response(raw: str) -> tuple[str, str]:
    """Extract answer and conversation id from Coze v3 JSON or SSE responses."""
    delta_parts: list[str] = []
    complete_parts: list[str] = []
    conversation_id = ""
    event_name = ""
    parsed_objects: list[tuple[str, dict]] = []
    pending_data: list[str] = []

    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                continue
            pending_data.append(payload)
            try:
                item = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                parsed_objects.append((event_name, item))

    if not parsed_objects:
        try:
            item = json.loads(raw)
            if isinstance(item, dict):
                parsed_objects.append(("", item))
        except json.JSONDecodeError:
            pass

    for event, item in parsed_objects:
        candidates = [item]
        nested = item.get("data")
        if isinstance(nested, dict):
            candidates.append(nested)
        elif isinstance(nested, str):
            try:
                decoded = json.loads(nested)
                if isinstance(decoded, dict):
                    candidates.append(decoded)
            except json.JSONDecodeError:
                pass
        for candidate in candidates:
            conversation_id = conversation_id or str(candidate.get("conversation_id") or candidate.get("conversationId") or "")
            content = _coze_text(candidate.get("content"))
            if content:
                if ".delta" in event or event.endswith("delta"):
                    delta_parts.append(content)
                elif candidate.get("type") in {"answer", "assistant"} or candidate.get("role") == "assistant":
                    complete_parts.append(content)
            messages = candidate.get("messages")
            if isinstance(messages, list):
                for message in messages:
                    if isinstance(message, dict) and (message.get("role") == "assistant" or message.get("type") == "answer"):
                        text = _coze_text(message.get("content"))
                        if text:
                            complete_parts.append(text)

    answer = "".join(delta_parts).strip() or (complete_parts[-1].strip() if complete_parts else "")
    if not answer:
        raise ValueError("扣子智能体响应中没有可显示的回答")
    return answer, conversation_id


def _coze_agent_answer(prompt: str, context: dict, agent_mode: str, conversation_id: str) -> tuple[str, str]:
    bot_id = settings.agent_bot_id(agent_mode)
    if not settings.agent_configured or not bot_id:
        raise ValueError("扣子智能体配置不完整")
    payload = {
        "bot_id": bot_id,
        "user_id": settings.agent_user_id.strip() or "career-insight-local",
        "stream": True,
        "auto_save_history": True,
        "additional_messages": [
            {"role": "user", "content": _coze_prompt(prompt, context), "content_type": "text"}
        ],
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.agent_api_key.strip()}"}
    request = Request(
        f"{settings.agent_base_url.rstrip('/')}/{settings.agent_chat_path.lstrip('/')}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=settings.agent_timeout_seconds) as response:
        return _coze_response(response.read().decode("utf-8"))


def _coze_request(prompt: str, context: dict, agent_mode: str, conversation_id: str) -> Request:
    bot_id = settings.agent_bot_id(agent_mode)
    if not settings.agent_configured or not bot_id:
        raise ValueError("扣子智能体配置不完整")
    payload = {
        "bot_id": bot_id,
        "user_id": settings.agent_user_id.strip() or "career-insight-local",
        "stream": True,
        "auto_save_history": True,
        "additional_messages": [
            {"role": "user", "content": _coze_prompt(prompt, context), "content_type": "text"}
        ],
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return Request(
        f"{settings.agent_base_url.rstrip('/')}/{settings.agent_chat_path.lstrip('/')}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.agent_api_key.strip()}"},
        method="POST",
    )


def coze_agent_stream(prompt: str, context: dict, agent_mode: str, conversation_id: str = ""):
    """Yield Coze SSE events as soon as they arrive from the upstream response."""
    cache_key = _agent_cache_key(prompt, context, agent_mode, conversation_id)
    cached = _cached_agent_response(cache_key)
    if cached:
        answer, cached_conversation_id = cached
        for index in range(0, len(answer), 48):
            yield "conversation.message.delta", {
                "conversation_id": cached_conversation_id,
                "type": "answer",
                "content": answer[index:index + 48],
                "cached": True,
            }
        yield "done", {"conversation_id": cached_conversation_id, "cached": True}
        return
    request = _coze_request(prompt, context, agent_mode, conversation_id)
    answer_parts: list[str] = []
    response_conversation_id = conversation_id
    with urlopen(request, timeout=settings.agent_timeout_seconds) as response:
        event_name = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                continue
            try:
                item = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                if event_name == "conversation.chat.failed" or str(item.get("status") or "").lower() == "failed":
                    raise AgentProviderError(coze_failure_reason(item))
                response_conversation_id = coze_event_conversation_id(item) or response_conversation_id
                delta = coze_event_text(event_name, item)
                if delta:
                    answer_parts.append(delta)
                yield event_name, item
    answer = "".join(answer_parts).strip()
    if answer:
        _store_agent_response(cache_key, answer, response_conversation_id)


def coze_event_text(event_name: str, item: dict) -> str:
    # The completed event repeats the whole answer after all deltas. Only
    # consume delta events here, otherwise the browser would append it twice.
    if "delta" not in event_name.lower():
        return ""
    candidates = [item]
    nested = item.get("data")
    if isinstance(nested, dict):
        candidates.append(nested)
    for candidate in candidates:
        content = _coze_text(candidate.get("content"))
        if content:
            return content
    return ""


def coze_event_conversation_id(item: dict) -> str:
    nested = item.get("data") if isinstance(item.get("data"), dict) else {}
    return str(item.get("conversation_id") or item.get("conversationId") or nested.get("conversation_id") or nested.get("conversationId") or "")


def agent_provider_answer(
    prompt: str,
    context: dict,
    agent_mode: str = "career_planning",
    conversation_id: str = "",
) -> tuple[str, bool, str]:
    provider = settings.agent_provider.strip().lower()
    if provider == "coze":
        try:
            answer, coze_conversation_id = _coze_agent_answer(prompt, context, agent_mode, conversation_id)
            if coze_conversation_id:
                context["_cozeConversationId"] = coze_conversation_id
            return answer, True, "coze"
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as reason:
            provider_reason = reason.reason if isinstance(reason, AgentProviderError) else "provider_unavailable"
            return rule_agent_answer(context, provider_reason), False, "rules"
    if provider != "external" or not settings.agent_base_url.strip():
        return rule_agent_answer(context, "not_configured"), False, "rules"

    payload = {
        "message": prompt,
        "context": context,
        "constraints": {
            "groundedOnly": True,
            "noDirectDatabaseAccess": True,
            "language": "zh-CN",
        },
    }
    headers = {"Content-Type": "application/json"}
    if settings.agent_api_key:
        headers["Authorization"] = f"Bearer {settings.agent_api_key}"
    request = Request(
        f"{settings.agent_base_url.rstrip('/')}/{settings.agent_chat_path.lstrip('/')}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.agent_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        answer = data.get("answer") or data.get("data", {}).get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("外部智能体响应缺少 answer")
        return answer.strip(), True, "external"
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return rule_agent_answer(context), False, "rules"
