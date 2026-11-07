"""M3 period features and signals.

The stage is deliberately MySQL-only. It reads the persisted raw, normalized,
and entity-link records and can be rerun without relying on process memory.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .models import EntityLink, FeatureSnapshot, NormalizedRecord, RawRecord, Signal, uid


FEATURE_VERSION = "feature-v1"
SIGNAL_VERSION = "signal-v1"
_MONTH_RE = re.compile(r"(?<!\d)(\d{4})[-/._年](\d{1,2})(?:[-/._月日]\d{1,2})?")
_QUARTER_RE = re.compile(r"(?<!\d)(\d{4})\s*(?:[-/._年]\s*)?[Qq第]?\s*([1-4])\s*(?:季|季度|quarter)?")


def normalize_period(value: object) -> tuple[str, str] | None:
    """Return (period_key, granularity), preserving quarters as quarters."""
    text = str(value or "").strip()
    if not text:
        return None
    quarter = _QUARTER_RE.search(text)
    if quarter and ("q" in text.lower() or "季" in text or "季度" in text or re.search(r"\d{4}[-/._年]?\s*[第]?[1-4]", text)):
        return f"{quarter.group(1)}-Q{quarter.group(2)}", "quarter"
    month = _MONTH_RE.search(text)
    if month:
        year, number = int(month.group(1)), int(month.group(2))
        if 1 <= number <= 12:
            return f"{year:04d}-{number:02d}", "month"
    compact = re.search(r"(?<!\d)(\d{4})(\d{2})(?!\d)", text)
    if compact and 1 <= int(compact.group(2)) <= 12:
        return f"{compact.group(1)}-{compact.group(2)}", "month"
    return None


def period_from_record(raw: RawRecord) -> tuple[str, str] | None:
    payload = raw.raw_payload or {}
    # This order is part of the M3 input contract.
    for key in ("published_date_clean", "published_date", "period", "time_id"):
        result = normalize_period(payload.get(key))
        if result:
            return result
    return None


def _norm_title(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    return re.sub(r"[\[\]【】()（）,，。:：/\\|]+", " ", text).strip()


def _period_parts(period: str, granularity: str) -> tuple[int, int]:
    if granularity == "quarter":
        year, quarter = period.split("-Q")
        return int(year), int(quarter)
    year, month = period.split("-")
    return int(year), int(month)


def _period_distance(start: str, end: str, granularity: str) -> int:
    a_year, a_part = _period_parts(start, granularity)
    b_year, b_part = _period_parts(end, granularity)
    width = 4 if granularity == "quarter" else 12
    return (b_year - a_year) * width + b_part - a_part


def _previous_period(periods: list[str], current: str, granularity: str) -> str | None:
    index = periods.index(current)
    if index == 0 or _period_distance(periods[index - 1], current, granularity) != 1:
        return None
    return periods[index - 1]


def _prior_contiguous(periods: list[str], current: str, count: int, granularity: str) -> list[str] | None:
    index = periods.index(current)
    if index < count:
        return None
    result = periods[index - count:index]
    if all(_period_distance(result[item], result[item + 1], granularity) == 1 for item in range(len(result) - 1)) and _period_distance(result[-1], current, granularity) == 1:
        return result
    return None


def _prior_offset(periods: list[str], current: str, offset: int, granularity: str) -> str | None:
    index = periods.index(current)
    if index < 1:
        return None
    for candidate in reversed(periods[:index]):
        if _period_distance(candidate, current, granularity) == offset:
            return candidate
    return None


def _safe_ratio(value: float, base: float) -> float | None:
    return None if not base else round((value - base) / base, 4)


def _severity(value: float) -> str:
    magnitude = abs(value)
    return "high" if magnitude >= 1 else "medium"


def _period_value(payload: dict, key: str) -> object:
    return payload.get(key)


def _load_inputs(db: Session) -> tuple[dict, dict, dict]:
    raws = db.scalars(select(RawRecord).order_by(RawRecord.created_at, RawRecord.id)).all()
    normalized = {
        item.raw_record_id: item
        for item in db.scalars(select(NormalizedRecord).order_by(NormalizedRecord.created_at)).all()
    }
    links_by_raw: dict[str, list[EntityLink]] = defaultdict(list)
    for link in db.scalars(select(EntityLink)).all():
        links_by_raw[link.raw_record_id].append(link)
    return {item.id: item for item in raws}, normalized, links_by_raw


def _build_cohorts(db: Session) -> tuple[dict, dict]:
    raws, normalized, links_by_raw = _load_inputs(db)
    cohorts: dict[tuple[str, str, str], dict] = {}
    input_summary = {"total_raw_records": len(raws), "unparsed_period": 0, "parsed_period": 0, "excluded_non_posting": 0}
    for raw in raws.values():
        if raw.node_type not in {"JobPosting", "", "JobRole"}:
            input_summary["excluded_non_posting"] += 1
            continue
        period_result = period_from_record(raw)
        if not period_result:
            input_summary["unparsed_period"] += 1
            continue
        period, granularity = period_result
        input_summary["parsed_period"] += 1
        links = links_by_raw.get(raw.id, [])
        role_link = next((item for item in links if item.entity_type == "JobRole" and item.status == "accepted" and item.entity_id), None)
        normalized_record = normalized.get(raw.id)
        parsed_title = (normalized_record.data or {}).get("title", "") if normalized_record else ""
        title = raw.title or parsed_title
        if role_link:
            cohort_key, cohort_basis = f"role:{role_link.entity_id}", "role"
        else:
            cohort_key, cohort_basis = f"title:{_norm_title(title)}", "title"
        if cohort_key == "title:":
            cohort_key = f"title:{raw.id}"
        key = (period, granularity, cohort_key)
        item = cohorts.setdefault(key, {
            "period": period, "granularity": granularity, "cohort_key": cohort_key, "cohort_basis": cohort_basis,
            "postings": {},
        })
        posting_key = raw.duplicate_of or raw.id
        posting = item["postings"].setdefault(posting_key, {
            "raw_ids": [], "sources": set(), "skills": set(), "covered": False,
        })
        posting["raw_ids"].append(raw.id)
        if raw.source_canonical:
            posting["sources"].add(raw.source_canonical)
        accepted_skills = {link.entity_id for link in links if link.entity_type == "Skill" and link.status == "accepted" and link.entity_id}
        parsed = normalized.get(raw.id)
        if not accepted_skills and parsed:
            accepted_skills = {str(skill.get("skill_id")) for skill in (parsed.data or {}).get("skills", []) if skill.get("skill_id") and skill.get("link_status", "accepted") == "accepted"}
        posting["skills"].update(accepted_skills)
        posting["covered"] = bool(parsed and parsed.data)
    return cohorts, input_summary


def _feature_metrics(item: dict, prior: dict | None, prior_three: list[dict] | None, prior_year: dict | None = None) -> dict:
    postings = item["postings"]
    posting_count = len(postings)
    source_count = len({source for posting in postings.values() for source in posting["sources"] if source})
    covered_count = sum(1 for posting in postings.values() if posting["covered"])
    skill_counts: dict[str, int] = defaultdict(int)
    skill_evidence: dict[str, list[str]] = defaultdict(list)
    evidence_ids = []
    for posting in postings.values():
        evidence_ids.extend(posting["raw_ids"])
        for skill_id in posting["skills"]:
            skill_counts[skill_id] += 1
            skill_evidence[skill_id].extend(posting["raw_ids"])
    skill_shares = {skill: round(count / posting_count, 4) for skill, count in skill_counts.items()} if posting_count else {}
    top5 = [skill for skill, _ in sorted(skill_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]]
    current = {"posting_count": posting_count, "source_count": source_count, "coverage": round(covered_count / posting_count, 4) if posting_count else 0,
               "skill_counts": dict(skill_counts), "skill_shares": skill_shares, "top5_skills": top5,
               "evidence_by_skill": {skill: ids[:100] for skill, ids in skill_evidence.items()}}
    if prior:
        previous_count = prior["posting_count"]
        current["prior_period"] = prior.get("period")
        current["mom_change"] = posting_count - previous_count
        current["mom_change_pct"] = _safe_ratio(posting_count, previous_count)
        current["skill_share_change"] = {
            skill: round(skill_shares.get(skill, 0) - prior.get("skill_shares", {}).get(skill, 0), 4)
            for skill in set(skill_shares) | set(prior.get("skill_shares", {}))
        }
    if prior_three:
        rolling_counts = [entry["posting_count"] for entry in prior_three]
        rolling_avg = sum(rolling_counts) / len(rolling_counts)
        current["rolling_3_avg"] = round(rolling_avg, 4)
        current["rolling_3_change_pct"] = _safe_ratio(posting_count, rolling_avg)
    current["yoy_change_pct"] = _safe_ratio(posting_count, prior_year["posting_count"]) if prior_year else None
    return current


def _upsert_signal(db: Session, payload: dict, preexisting: dict[tuple[str, str], list[Signal]], suppressed: set[tuple[str, str, str]]) -> str:
    signal_type, cohort_key, period_key, granularity = payload["signal_type"], payload["cohort_key"], payload["period_key"], payload["granularity"]
    existing = db.scalar(select(Signal).where(Signal.signal_type == signal_type, Signal.cohort_key == cohort_key,
                                               Signal.period_key == period_key, Signal.granularity == granularity))
    evidence = payload.get("evidence_ids") or []
    status = "active" if evidence else "draft"
    if not existing and status == "active":
        cutoff = datetime.utcnow() - timedelta(days=settings.signal_suppression_days)
        previous = [item for item in preexisting.get((signal_type, cohort_key), []) if item.created_at and item.created_at >= cutoff and item.period_key != period_key and item.status == "active"]
        if previous:
            suppressed.add((signal_type, cohort_key, period_key))
            return "suppressed"
    if not existing:
        existing = Signal(id=uid("sig"), signal_type=signal_type, cohort_key=cohort_key, period_key=period_key, granularity=granularity)
        db.add(existing)
    existing.severity = payload.get("severity", "medium")
    existing.status = status
    existing.metrics = payload.get("metrics", {})
    existing.evidence_ids = evidence
    existing.suppression_key = f"{signal_type}:{cohort_key}"
    existing.signal_version = SIGNAL_VERSION
    return "created" if existing.id else "updated"


def build_feature_stage(db: Session, *, batch_id: str | None = None) -> dict:
    """Recompute M3 snapshots from persisted records and upsert signals."""
    cohorts, input_summary = _build_cohorts(db)
    # Snapshots are the current materialization for the period/cohort key.
    db.execute(delete(FeatureSnapshot))
    db.flush()
    feature_rows: dict[tuple[str, str], dict] = {}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in cohorts.values():
        grouped[(item["cohort_key"], item["granularity"])].append(item)
    for key in grouped:
        grouped[key].sort(key=lambda item: item["period"])
    feature_count = 0
    for (cohort_key, granularity), items in grouped.items():
        periods = [item["period"] for item in items]
        for index, item in enumerate(items):
            posting_count = len(item["postings"])
            if posting_count < settings.feature_min_sample:
                continue
            prior_item = items[index - 1] if index and _period_distance(items[index - 1]["period"], item["period"], granularity) == 1 else None
            prior_three_items = _prior_contiguous(periods, item["period"], 3, granularity)
            prior_three = [items[periods.index(period)] for period in prior_three_items] if prior_three_items else None
            year_offset = 4 if granularity == "quarter" else 12
            prior_year_period = _prior_offset(periods, item["period"], year_offset, granularity)
            prior_year_item = items[periods.index(prior_year_period)] if prior_year_period else None
            metrics = _feature_metrics(item, _feature_metrics(prior_item, None, None) if prior_item else None,
                                        [_feature_metrics(entry, None, None) for entry in prior_three] if prior_three else None,
                                        _feature_metrics(prior_year_item, None, None) if prior_year_item else None)
            row = FeatureSnapshot(period_key=item["period"], granularity=granularity, cohort_key=cohort_key,
                                  cohort_basis=item["cohort_basis"], metrics=metrics,
                                  evidence_ids=[raw_id for posting in item["postings"].values() for raw_id in posting["raw_ids"]][:100],
                                  input_summary={**input_summary, "distinct_postings": posting_count}, feature_version=FEATURE_VERSION)
            db.add(row)
            feature_rows[(cohort_key, item["period"])] = {**item, "metrics": metrics}
            feature_count += 1
    db.flush()
    preexisting_rows = db.scalars(select(Signal)).all()
    preexisting: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for row in preexisting_rows:
        preexisting[(row.signal_type, row.cohort_key)].append(row)
    suppressed: set[tuple[str, str, str]] = set()
    signal_counts = defaultdict(int)
    for (cohort_key, granularity), items in grouped.items():
        periods = [item["period"] for item in items]
        feature_items = [feature_rows.get((cohort_key, period)) for period in periods]
        first_period = periods[0] if periods else ""
        for index, current in enumerate(feature_items):
            if not current:
                continue
            current_metrics = current["metrics"]
            prior = feature_items[index - 1] if index and _period_distance(periods[index - 1], periods[index], granularity) == 1 else None
            evidence = [raw_id for posting in current["postings"].values() for raw_id in posting["raw_ids"]][:100]
            age = _period_distance(first_period, current["period"], granularity) if first_period else 999
            mom = current_metrics.get("mom_change_pct")
            if age < settings.emerging_role_age_months and mom is not None and mom >= settings.emerging_role_mom_growth and current_metrics["source_count"] >= settings.emerging_role_min_sources and current_metrics["posting_count"] >= settings.emerging_role_min_observations:
                result = _upsert_signal(db, {"signal_type": "emerging_role", "cohort_key": cohort_key, "period_key": current["period"], "granularity": granularity, "severity": _severity(mom), "metrics": {"age_periods": age, "mom_change_pct": mom, "posting_count": current_metrics["posting_count"], "source_count": current_metrics["source_count"]}, "evidence_ids": evidence}, preexisting, suppressed)
                signal_counts[result] += 1
            if prior:
                prior_top = set(prior["metrics"].get("top5_skills", []))
                current_top = set(current_metrics.get("top5_skills", []))
                jaccard = len(prior_top & current_top) / len(prior_top | current_top) if prior_top | current_top else 1
                delta = len(prior_top ^ current_top)
                if current_metrics["posting_count"] >= settings.feature_min_sample and (delta >= settings.capability_shift_top5_delta or jaccard < settings.capability_shift_jaccard):
                    result = _upsert_signal(db, {"signal_type": "capability_shift", "cohort_key": cohort_key, "period_key": current["period"], "granularity": granularity, "severity": "high" if jaccard < 0.25 else "medium", "metrics": {"top5_delta": delta, "jaccard": round(jaccard, 4)}, "evidence_ids": evidence}, preexisting, suppressed)
                    signal_counts[result] += 1
                if mom is not None and mom <= settings.role_decline_mom_drop and prior["metrics"].get("mom_change_pct") is not None and prior["metrics"]["mom_change_pct"] <= settings.role_decline_mom_drop and prior["metrics"].get("posting_count", 0) >= settings.role_decline_base_sample:
                    result = _upsert_signal(db, {"signal_type": "role_decline", "cohort_key": cohort_key, "period_key": current["period"], "granularity": granularity, "severity": "high", "metrics": {"mom_change_pct": mom, "prior_mom_change_pct": prior["metrics"].get("mom_change_pct"), "base_sample": prior["metrics"].get("posting_count")}, "evidence_ids": evidence}, preexisting, suppressed)
                    signal_counts[result] += 1
                for skill_id, share in current_metrics.get("skill_shares", {}).items():
                    previous_share = prior["metrics"].get("skill_shares", {}).get(skill_id, 0)
                    relative = _safe_ratio(share, previous_share)
                    if current_metrics["posting_count"] >= settings.skill_surge_min_postings and current_metrics["source_count"] >= settings.skill_surge_min_sources and (share - previous_share >= settings.skill_surge_share_pp or (relative is not None and relative >= settings.skill_surge_relative_growth)):
                        result = _upsert_signal(db, {"signal_type": "skill_surge", "cohort_key": cohort_key, "period_key": current["period"], "granularity": granularity, "severity": _severity(share - previous_share), "metrics": {"skill_id": skill_id, "share": share, "prior_share": previous_share, "share_change": round(share - previous_share, 4), "relative_change": relative}, "evidence_ids": current_metrics.get("evidence_by_skill", {}).get(skill_id, evidence)}, preexisting, suppressed)
                        signal_counts[result] += 1
            prior_three = _prior_contiguous(periods, current["period"], settings.skill_obsolescence_months, granularity)
            if prior_three:
                base = feature_rows[(cohort_key, prior_three[0])]["metrics"]
                for skill_id, base_share in base.get("skill_shares", {}).items():
                    values = [feature_rows[(cohort_key, period)]["metrics"].get("skill_shares", {}).get(skill_id, 0) for period in prior_three] + [current_metrics.get("skill_shares", {}).get(skill_id, 0)]
                    if base_share >= settings.skill_obsolescence_base_share and all(values[pos] < values[pos - 1] for pos in range(1, len(values))) and base_share - values[-1] >= settings.skill_obsolescence_cumulative_drop:
                        result = _upsert_signal(db, {"signal_type": "skill_obsolescence", "cohort_key": cohort_key, "period_key": current["period"], "granularity": granularity, "severity": "high", "metrics": {"skill_id": skill_id, "base_share": base_share, "current_share": values[-1], "cumulative_drop": round(base_share - values[-1], 4)}, "evidence_ids": current_metrics.get("evidence_by_skill", evidence)}, preexisting, suppressed)
                        signal_counts[result] += 1
    if batch_id:
        input_summary["batch_id"] = batch_id
    return {"feature_count": feature_count, "signal_counts": dict(signal_counts), "input_summary": input_summary, "suppressed": len(suppressed), "feature_version": FEATURE_VERSION, "signal_version": SIGNAL_VERSION}


def serialize_feature(row: FeatureSnapshot) -> dict:
    return {"id": row.id, "periodKey": row.period_key, "granularity": row.granularity, "cohortKey": row.cohort_key,
            "cohortBasis": row.cohort_basis, "metrics": row.metrics, "evidenceIds": row.evidence_ids,
            "inputSummary": row.input_summary, "featureVersion": row.feature_version}


def serialize_signal(row: Signal) -> dict:
    return {"id": row.id, "signalType": row.signal_type, "cohortKey": row.cohort_key, "periodKey": row.period_key,
            "granularity": row.granularity, "severity": row.severity, "status": row.status, "metrics": row.metrics,
            "evidenceIds": row.evidence_ids, "signalVersion": row.signal_version}
