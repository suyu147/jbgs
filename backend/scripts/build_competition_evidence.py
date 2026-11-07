"""Build reproducible competition evidence from governed recruitment data.

The script is read-only with respect to source CSV and Neo4j. It writes a
versioned evidence package under application data for review seeding and
competition verification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import APP_DATA_ROOT, EXAMPLE_ROOT  # noqa: E402
from app.services import build_new_role_definition  # noqa: E402


SUITE = "competition-evidence-20260825-v01"
EMERGING_TERMS = (
    "AI",
    "人工智能",
    "大模型",
    "机器学习",
    "深度学习",
    "算法",
    "数据",
    "智能",
    "物联网",
    "芯片",
    "半导体",
    "安全",
    "云",
    "自动驾驶",
    "数字孪生",
    "机器人",
    "区块链",
    "工业互联网",
    "视觉",
    "嵌入式",
    "新能源",
)


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "approved"}


def source_of(row: dict) -> str:
    return str(row.get("source_canonical_final") or row.get("source") or "").strip()


def month_of(row: dict) -> str:
    value = str(row.get("posted_month_canonical") or "").strip()
    return value if re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", value) else ""


def title_has_emerging_term(title: str) -> bool:
    folded = title.casefold()
    return any(term.casefold() in folded for term in EMERGING_TERMS)


def candidate_signal(postings: list[dict]) -> tuple[float, str]:
    sources = {source_of(item) for item in postings if source_of(item)}
    months = {month_of(item) for item in postings if month_of(item)}
    count_score = min(math.log1p(len(postings)) / math.log1p(20), 1.0) * 30
    source_score = min(len(sources) / 4, 1.0) * 25
    month_score = min(len(months) / 4, 1.0) * 15
    novelty_score = 20 if title_has_emerging_term(postings[0].get("job_title_canonical", "")) else 0
    evidence_score = 10 if all(item.get("record_id") and item.get("source_url") for item in postings) else 5
    score = round(count_score + source_score + month_score + novelty_score + evidence_score, 1)
    grade = "A" if len(postings) >= 10 and len(sources) >= 3 and len(months) >= 2 else "B" if len(months) >= 2 else "B-"
    return score, grade


def build_data_backed_candidates(postings: list[dict], skills: list[dict]) -> tuple[list[dict], list[dict]]:
    eligible = [
        item
        for item in postings
        if truthy(item.get("eligible_for_graph")) and month_of(item) and item.get("job_title_canonical")
    ]
    by_title: dict[str, list[dict]] = defaultdict(list)
    for item in eligible:
        by_title[str(item["job_title_canonical"]).strip()].append(item)

    selected: list[tuple[str, list[dict]]] = []
    for title, rows in by_title.items():
        sources = {source_of(item) for item in rows if source_of(item)}
        months = sorted({month_of(item) for item in rows if month_of(item)})
        if (
            len(rows) >= 5
            and len(sources) >= 2
            and months
            and months[0] >= "2026-01"
            and title_has_emerging_term(title)
        ):
            selected.append((title, rows))
    selected.sort(key=lambda item: (-len(item[1]), item[0]))

    record_ids = {row.get("record_id", "") for _, rows in selected for row in rows}
    skill_rows = [
        item
        for item in skills
        if item.get("record_id") in record_ids and truthy(item.get("eligible_for_graph_final"))
    ]
    candidates: list[dict] = []
    evidence_rows: list[dict] = []
    for title, rows in selected:
        sources = {source_of(item) for item in rows if source_of(item)}
        months = sorted({month_of(item) for item in rows if month_of(item)})
        family = Counter(
            str(item.get("job_category_canonical") or item.get("job_family_standard") or "").strip()
            for item in rows
        ).most_common(1)[0][0]
        signal_score, evidence_grade = candidate_signal(rows)
        candidate = {
            "job_title_canonical": title,
            "job_category": family,
            "first_seen_month": months[0],
            "latest_seen_month": months[-1],
            "posting_count": len(rows),
            "source_count": len(sources),
            "active_month_count": len(months),
            "novelty_keywords": ";".join(term for term in EMERGING_TERMS if term.casefold() in title.casefold()),
            "candidate_reason": "recent_first_seen_cross_source_skill_supported",
            "signal_score": signal_score,
            "evidence_grade": evidence_grade,
            "source_type": "governed_job_postings",
            "human_review_required": True,
            "candidate_only": True,
            "algorithm_version": "new-role-signal-v2",
        }
        definition, evidence = build_new_role_definition(candidate, rows, skill_rows)
        definition.update(
            {
                "active_month_count": len(months),
                "signal_score": signal_score,
                "evidence_grade": evidence_grade,
                "source_type": "governed_job_postings",
                "algorithm_version": "new-role-signal-v2",
                "validation_boundary": "newly_observed_market_role_candidate_not_official_occupation",
            }
        )
        candidates.append(
            {
                "role_name": title,
                "candidate_type": "new_role",
                "definition": definition,
                "evidence": evidence,
            }
        )
        for item in rows:
            evidence_rows.append(
                {
                    "role_name": title,
                    "record_id": item.get("record_id", ""),
                    "source": source_of(item),
                    "source_url": item.get("source_url", ""),
                    "period": month_of(item),
                    "job_family": family,
                    "description_excerpt": (item.get("description_clean") or item.get("requirements_clean") or "")[:500],
                    "content_hash": item.get("content_hash", ""),
                    "duplicate_status": item.get("duplicate_status", ""),
                }
            )
    return candidates, evidence_rows


def build_skill_change_candidates(
    change_rows: list[dict], postings: list[dict], skills: list[dict]
) -> tuple[list[dict], list[dict]]:
    postings_by_id = {item.get("record_id", ""): item for item in postings}
    evidence_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in skills:
        if not truthy(item.get("eligible_for_graph_final")):
            continue
        evidence_by_key[(str(item.get("standard_job_title") or item.get("job_title") or "").strip(), item.get("skill_id", ""))].append(item)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in change_rows:
        if truthy(row.get("comparison_eligible")):
            grouped[str(row.get("job_title_canonical") or "").strip()].append(row)

    candidates: list[dict] = []
    evidence_export: list[dict] = []
    for role_name, rows in sorted(grouped.items()):
        changes = []
        evidence = []
        role_sources: set[str] = set()
        for row in sorted(rows, key=lambda item: -abs(float(item.get("penetration_change_pp") or 0))):
            skill_id = row.get("skill_id", "")
            related = evidence_by_key.get((role_name, skill_id), [])
            sampled: list[dict] = []
            for year in ("2025", "2026"):
                year_rows = [item for item in related if str(item.get("year")) == year]
                year_rows.sort(key=lambda item: (item.get("source", ""), item.get("record_id", "")))
                sampled.extend(year_rows[:3])
            source_count = len({str(item.get("source") or "").strip() for item in related if item.get("source")})
            role_sources.update(str(item.get("source") or "").strip() for item in related if item.get("source"))
            change = {
                "skill_id": skill_id,
                "skill_name": row.get("skill_name", ""),
                "change_type": row.get("change_type", ""),
                "change_pp": float(row.get("penetration_change_pp") or 0),
                "baseline_penetration": float(row.get("penetration_2025") or 0),
                "current_penetration": float(row.get("penetration_2026") or 0),
                "baseline_postings": int(float(row.get("postings_2025") or 0)),
                "current_postings": int(float(row.get("postings_2026") or 0)),
                "baseline_skill_postings": int(float(row.get("skill_postings_2025") or 0)),
                "current_skill_postings": int(float(row.get("skill_postings_2026") or 0)),
                "source_count": source_count,
                "comparison_eligible": True,
                "analysis_note": row.get("analysis_note", ""),
            }
            changes.append(change)
            for item in sampled:
                posting = postings_by_id.get(item.get("record_id", ""), {})
                evidence_item = {
                    "type": "job_posting_skill_evidence",
                    "recordId": item.get("record_id", ""),
                    "source": item.get("source", ""),
                    "url": item.get("source_url", ""),
                    "period": f"{item.get('year', '')}-{str(item.get('month', '')).zfill(2)}",
                    "skillId": skill_id,
                    "skillName": row.get("skill_name", ""),
                    "excerpt": (item.get("evidence_text_final") or item.get("evidence_text") or "")[:300],
                    "jobTitle": posting.get("job_title_canonical", role_name),
                    "confidence": item.get("confidence", ""),
                }
                evidence.append(evidence_item)
                evidence_export.append({"role_name": role_name, **evidence_item})
        candidates.append(
            {
                "role_name": role_name,
                "candidate_type": "skill_change",
                "definition": {
                    "changes": changes,
                    "first_seen": "2025-01",
                    "latest_seen": "2026-07",
                    "source_count": len(role_sources),
                    "source_type": "governed_job_postings",
                    "algorithm_version": "skill-penetration-change-v2",
                    "comparison_rule": "both_years_role_postings_ge_30_and_skill_mentions_ge_3",
                    "definition_status": "human_review_required",
                },
                "evidence": evidence[:24],
            }
        )
    return candidates, evidence_export


def governance_metrics(postings: list[dict], candidates: list[dict], change_candidates: list[dict]) -> dict:
    source_counts = Counter(source_of(item) for item in postings if source_of(item))
    duplicate_statuses = Counter(str(item.get("duplicate_status") or "unknown") for item in postings)
    hash_groups: dict[str, list[dict]] = defaultdict(list)
    for item in postings:
        content_hash = str(item.get("content_hash") or "").strip()
        if content_hash:
            hash_groups[content_hash].append(item)
    duplicate_groups = [rows for rows in hash_groups.values() if len(rows) > 1]
    cross_source_groups = [rows for rows in duplicate_groups if len({source_of(item) for item in rows}) > 1]
    monthly_eligible = sum(truthy(item.get("eligible_monthly_final")) for item in postings)
    annual_eligible = sum(truthy(item.get("eligible_annual_final")) for item in postings)
    graph_eligible = sum(truthy(item.get("eligible_for_graph")) for item in postings)
    candidate_evidence = [item for candidate in candidates for item in candidate.get("evidence", [])]
    evidence_with_url = sum(bool(item.get("url")) for item in candidate_evidence)
    grouped_titles: dict[str, list[dict]] = defaultdict(list)
    for item in postings:
        if truthy(item.get("eligible_for_graph")) and month_of(item) and item.get("job_title_canonical"):
            grouped_titles[str(item["job_title_canonical"]).strip()].append(item)
    single_source_candidates = [
        rows
        for title, rows in grouped_titles.items()
        if len(rows) >= 5
        and min(month_of(item) for item in rows if month_of(item)) >= "2026-01"
        and title_has_emerging_term(title)
    ]
    return {
        "suite": SUITE,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sourceCoverage": {"sourceCount": len(source_counts), "recordsBySource": dict(source_counts)},
        "deduplication": {
            "recordCount": len(postings),
            "uniqueContentHashes": len(hash_groups),
            "exactDuplicateGroups": len(duplicate_groups),
            "crossSourceDuplicateGroups": len(cross_source_groups),
            "duplicateRecords": sum(count for status, count in duplicate_statuses.items() if status != "unique"),
            "crossSourceDuplicateRecords": int(duplicate_statuses.get("exact_content_cross_source", 0)),
            "recordsByGovernedStatus": dict(duplicate_statuses),
            "method": "content_hash plus governed posting_dedup_key",
        },
        "timeLagAndNoise": {
            "graphEligible": graph_eligible,
            "monthlyEligible": monthly_eligible,
            "annualEligible": annual_eligible,
            "monthlyQuarantined": graph_eligible - monthly_eligible,
            "method": "date precision quarantine, minimum sample gate, empirical Bayes smoothing and robust weighted forecast",
        },
        "newRoleValidation": {
            "candidateCount": len(candidates),
            "singleSourceRuleCandidateCount": len(single_source_candidates),
            "crossSourceRuleCandidateCount": len(candidates),
            "crossSourceNoiseReduction": round(
                (len(single_source_candidates) - len(candidates)) / max(len(single_source_candidates), 1) * 100,
                2,
            ),
            "allCrossSource": all(int(item["definition"].get("source_count") or 0) >= 2 for item in candidates),
            "allHavePostingEvidence": all(int(item["definition"].get("evidence_record_count") or 0) >= 5 for item in candidates),
            "evidenceUrlCoverage": round(evidence_with_url / max(len(candidate_evidence), 1) * 100, 2),
            "boundary": "candidate discovery, not official occupation recognition",
        },
        "abilityChangeValidation": {
            "roleCount": len(change_candidates),
            "changeItemCount": sum(len(item["definition"].get("changes") or []) for item in change_candidates),
            "allComparisonEligible": all(
                change.get("comparison_eligible") is True
                for item in change_candidates
                for change in item["definition"].get("changes") or []
            ),
        },
        "hallucinationGuard": {
            "candidateFactsWithSourceRecord": round(
                sum(bool(item.get("recordId") and item.get("excerpt")) for item in candidate_evidence)
                / max(len(candidate_evidence), 1)
                * 100,
                2,
            ),
            "policy": "unsupported facts remain pending; only human-reviewed versions can be published",
        },
    }


def select_submission_examples(new_candidates: list[dict], change_candidates: list[dict]) -> dict:
    new_role = max(
        new_candidates,
        key=lambda item: (
            int(item["definition"].get("source_count") or 0),
            int(item["definition"].get("posting_count") or 0),
            float(item["definition"].get("signal_score") or 0),
            item["role_name"],
        ),
    )
    existing_role = max(
        change_candidates,
        key=lambda item: (
            int(item["definition"].get("source_count") or 0),
            len(item["definition"].get("changes") or []),
            sum(abs(float(change.get("change_pp") or 0)) for change in item["definition"].get("changes") or []),
            item["role_name"],
        ),
    )
    return {
        "suite": "competition-submission-examples-20260825-v01",
        "selectionRule": "cross-source count, evidence/change count, signal magnitude, stable role name",
        "newRole": new_role,
        "existingRoleUpdate": existing_role,
        "boundary": {
            "newRole": "market candidate pending human review, not an officially recognized occupation",
            "existingRoleUpdate": "penetration change candidate pending human review; partial-year imbalance is disclosed",
        },
    }


def main() -> int:
    default_data_root = EXAMPLE_ROOT / "各类所需数据"
    if not default_data_root.exists():
        default_data_root = EXAMPLE_ROOT.parents[1] / "各类所需数据"
    parser = argparse.ArgumentParser()
    parser.add_argument("--postings", type=Path, default=default_data_root / "01_标准化" / "第一类招聘数据_标准化.csv")
    parser.add_argument("--skills", type=Path, default=default_data_root / "02_归一化" / "岗位技能关系_归一化.csv")
    parser.add_argument("--changes", type=Path, default=default_data_root / "03_动态演示" / "既有岗位技能变化候选_动态演示.csv")
    parser.add_argument("--output", type=Path, default=APP_DATA_ROOT / "quality" / SUITE)
    args = parser.parse_args()
    for path in (args.postings, args.skills, args.changes):
        if not path.exists():
            raise SystemExit(f"missing source file: {path}")

    postings = read_csv(args.postings)
    skills = read_csv(args.skills)
    changes = read_csv(args.changes)
    new_candidates, new_evidence = build_data_backed_candidates(postings, skills)
    change_candidates, change_evidence = build_skill_change_candidates(changes, postings, skills)
    metrics = governance_metrics(postings, new_candidates, change_candidates)
    payload = {
        "suite": SUITE,
        "sourceFiles": {
            "postings": str(args.postings),
            "skills": str(args.skills),
            "changes": str(args.changes),
        },
        "sourceDigests": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (args.postings, args.skills, args.changes)
        },
        "metrics": metrics,
        "newRoleCandidates": new_candidates,
        "skillChangeCandidates": change_candidates,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "competition_evidence.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "governance_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    submission_examples = select_submission_examples(new_candidates, change_candidates)
    (args.output / "submission_examples.json").write_text(
        json.dumps(submission_examples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(
        args.output / "new_role_candidates.csv",
        [
            {
                "role_name": item["role_name"],
                **{key: value for key, value in item["definition"].items() if not isinstance(value, (dict, list))},
            }
            for item in new_candidates
        ],
        [
            "role_name", "job_category", "first_seen", "latest_seen", "posting_count", "source_count",
            "active_month_count", "signal_score", "evidence_grade", "source_type", "algorithm_version",
            "candidate_reason", "evidence_record_count", "validation_boundary",
        ],
    )
    write_csv(
        args.output / "new_role_evidence.csv",
        new_evidence,
        [
            "role_name", "record_id", "source", "source_url", "period", "job_family",
            "description_excerpt", "content_hash", "duplicate_status",
        ],
    )
    write_csv(
        args.output / "skill_change_evidence.csv",
        change_evidence,
        [
            "role_name", "type", "recordId", "source", "url", "period", "skillId", "skillName",
            "excerpt", "jobTitle", "confidence",
        ],
    )
    candidate_titles = {item["role_name"] for item in new_candidates}
    candidate_postings = [
        item for item in postings if item.get("job_title_canonical") in candidate_titles
    ]
    candidate_record_ids = {item.get("record_id", "") for item in candidate_postings}
    candidate_skill_rows = [
        item for item in skills if item.get("record_id", "") in candidate_record_ids
    ]
    write_csv(
        args.output / "governed_posting_index.csv",
        [
            {
                "record_id": item.get("record_id", ""),
                "source": source_of(item),
                "source_url": item.get("source_url", ""),
                "posted_month": month_of(item),
                "job_title": item.get("job_title_canonical", ""),
                "job_family": item.get("job_category_canonical") or item.get("job_family_standard", ""),
                "eligible_for_graph": item.get("eligible_for_graph", ""),
                "eligible_monthly": item.get("eligible_monthly_final", ""),
                "eligible_annual": item.get("eligible_annual_final", ""),
                "content_hash": item.get("content_hash", ""),
                "posting_dedup_key": item.get("posting_dedup_key", ""),
                "duplicate_status": item.get("duplicate_status", ""),
            }
            for item in postings
        ],
        [
            "record_id", "source", "source_url", "posted_month", "job_title", "job_family",
            "eligible_for_graph", "eligible_monthly", "eligible_annual", "content_hash",
            "posting_dedup_key", "duplicate_status",
        ],
    )
    write_csv(
        args.output / "candidate_postings_subset.csv",
        candidate_postings,
        list(candidate_postings[0]) if candidate_postings else [],
    )
    write_csv(
        args.output / "candidate_skill_relations_subset.csv",
        candidate_skill_rows,
        list(candidate_skill_rows[0]) if candidate_skill_rows else [],
    )
    write_csv(
        args.output / "skill_change_candidates_input.csv",
        changes,
        list(changes[0]) if changes else [],
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
