"""Build the strengthened competition benchmark.

V04 keeps the 120 real JD field gold set, evaluates privacy-preserving resume
samples without target-title leakage, and ranks each sample against the full
governed role catalogue rather than a preselected same-family candidate list.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import APP_DATA_ROOT  # noqa: E402
from app.database import engine  # noqa: E402
from app.models import EvaluationRun  # noqa: E402
from app.neo4j_client import neo4j  # noqa: E402
from app.services import _importance, extract_skills, rank_role_candidates  # noqa: E402


SUITE = "acceptance-20260825-v04"
OUTPUT = APP_DATA_ROOT / "quality" / SUITE


def metric(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {
        "precision": round(precision * 100, 2),
        "recall": round(recall * 100, 2),
        "f1": round(f1 * 100, 2),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def role_pool() -> list[dict]:
    rows = neo4j.query(
        "MATCH (r:JobRole)-[rel:REQUIRES_SKILL]->(s:Skill) "
        "WHERE coalesce(rel.active,true)=true "
        "WITH r,collect({id:s.skill_id,name:s.entity_name,aliases:coalesce(s.aliases,''),"
        "weight:toFloat(rel.penetration_rate),sourceCount:toInteger(rel.source_count),"
        "evidenceCount:toInteger(rel.evidence_count),confidence:rel.confidence}) AS skills "
        "WHERE size(skills)>=6 RETURN r.role_id AS id,r.role_name AS name,r.role_family AS family,"
        "r.posting_count AS postingCount,skills ORDER BY toInteger(r.posting_count) DESC LIMIT 900"
    )
    distinct: dict[tuple[str, ...], dict] = {}
    for role in rows:
        role["skills"] = sorted(
            [
                skill
                for skill in role["skills"]
                if skill.get("id") and skill.get("name") and len(str(skill["name"]).strip()) >= 2
            ],
            key=_importance,
            reverse=True,
        )
        signature = tuple(sorted(skill["id"] for skill in role["skills"][:20]))
        if len(signature) >= 6:
            distinct.setdefault(signature, role)
    return list(distinct.values())


def balanced_targets(roles: list[dict], count: int = 120) -> list[dict]:
    by_family: dict[str, list[dict]] = defaultdict(list)
    for role in roles:
        by_family[str(role.get("family") or "未分类")].append(role)
    families = sorted(by_family, key=lambda name: (-len(by_family[name]), name))
    targets: list[dict] = []
    index = 0
    while len(targets) < count:
        added = False
        for family in families:
            if index < len(by_family[family]):
                targets.append(by_family[family][index])
                added = True
                if len(targets) == count:
                    break
        if not added:
            break
        index += 1
    if len(targets) < count:
        raise RuntimeError(f"only {len(targets)} balanced target roles are available")
    return targets


def profile_similarity(left: dict, right: dict) -> float:
    left_ids = {item["id"] for item in left["skills"][:20]}
    right_ids = {item["id"] for item in right["skills"][:20]}
    return len(left_ids & right_ids) / len(left_ids | right_ids) if left_ids | right_ids else 0.0


def build_samples(roles: list[dict]) -> tuple[list[dict], dict, dict, list[dict]]:
    targets = balanced_targets(roles)
    frequency = Counter(skill["id"] for role in roles for skill in role["skills"][:20])
    rows: list[dict] = []
    failures: list[dict] = []
    skill_tp = skill_fp = skill_fn = top1 = top3 = 0
    for index, target in enumerate(targets):
        target_profile = target["skills"][:20]
        selected = sorted(
            target_profile,
            key=lambda skill: (
                frequency[skill["id"]],
                -_importance(skill),
                str(skill["name"]),
            ),
        )[:4]
        selected_ids = {item["id"] for item in selected}
        for skill in target_profile:
            if skill["id"] not in selected_ids:
                selected.append(skill)
                selected_ids.add(skill["id"])
            if len(selected) >= 12:
                break

        peers = [role for role in roles if role["id"] != target["id"]]
        peers.sort(key=lambda role: (-profile_similarity(target, role), role["id"]))
        distractors: list[dict] = []
        for peer in peers[:8]:
            for skill in peer["skills"][:12]:
                if skill["id"] not in selected_ids and skill["id"] not in {item["id"] for item in distractors}:
                    distractors.append(skill)
                    break
            if len(distractors) == 2:
                break

        expected_items = selected + distractors
        expected = {item["id"] for item in expected_items}
        names = [str(item["name"]) for item in expected_items]
        split = max(5, len(names) // 2)
        text = (
            "脱敏能力档案。项目经历：负责需求分析、方案设计、开发验证与交付，参与跨团队协作。"
            f"专业能力：{' 、 '.join(names[:split])}。\n"
            f"工具与实践：{' / '.join(names[split:])}。\n"
            "教育背景：本科。工作经验：3年。"
        )
        parsed_items = extract_skills(text)
        predicted = {item["skill_id"] for item in parsed_items}
        predicted_names = [item["skill_name"] for item in parsed_items]
        skill_tp += len(expected & predicted)
        skill_fp += len(predicted - expected)
        skill_fn += len(expected - predicted)

        scores = rank_role_candidates(roles, predicted_names)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        ranked_ids = [item[0] for item in ranked]
        target_rank = ranked_ids.index(target["id"]) + 1
        top1 += int(target_rank == 1)
        top3 += int(target_rank <= 3)
        row = {
            "resume_id": f"privacy_v04_{index + 1:03d}",
            "synthetic": True,
            "contains_sensitive_attributes": False,
            "target_title_leakage": False,
            "target_role_id": target["id"],
            "target_role": target["name"],
            "job_family": target.get("family") or "未分类",
            "text": text,
            "gold_skill_ids": json.dumps(sorted(expected), ensure_ascii=False),
            "predicted_skill_ids": json.dumps(sorted(predicted), ensure_ascii=False),
            "predicted_skills_with_evidence": json.dumps(parsed_items, ensure_ascii=False),
            "catalog_candidate_count": len(roles),
            "target_rank": target_rank,
            "top1_role_id": ranked_ids[0],
            "top3_role_ids": json.dumps(ranked_ids[:3], ensure_ascii=False),
            "ranking_algorithm": "recommend-v2-tfidf-evidence",
        }
        rows.append(row)
        if target_rank > 1:
            failures.append(row)

    extraction = metric(skill_tp, skill_fp, skill_fn)
    extraction.update(
        {
            "samples": len(rows),
            "distinctTargetRoles": len({row["target_role_id"] for row in rows}),
            "synthetic": True,
            "privacyPreserving": True,
        }
    )
    matching = {
        "samples": len(rows),
        "distinctTargetRoles": len({row["target_role_id"] for row in rows}),
        "families": len({row["job_family"] for row in rows}),
        "catalogCandidateCount": len(roles),
        "top1Accuracy": round(top1 / len(rows) * 100, 2),
        "top3Accuracy": round(top3 / len(rows) * 100, 2),
        "meanReciprocalRank": round(
            sum(1 / int(row["target_rank"]) for row in rows) / len(rows) * 100, 2
        ),
        "candidateScope": "full_governed_catalog_distinct_skill_profiles",
        "targetTitleLeakage": False,
        "algorithmVersion": "recommend-v2-tfidf-evidence",
    }
    return rows, extraction, matching, failures


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    jd_path = APP_DATA_ROOT / "quality" / "jd-field-gold-20260822" / "jd_field_metrics.json"
    if not jd_path.exists():
        raise SystemExit(f"missing JD field benchmark: {jd_path}")
    jd_fields = json.loads(jd_path.read_text(encoding="utf-8"))
    roles = role_pool()
    rows, resume_metrics, matching_metrics, failures = build_samples(roles)
    summary = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "suite": SUITE,
        "jdFields": jd_fields,
        "resumeExtraction": resume_metrics,
        "matching": matching_metrics,
        "thresholds": {"jdFieldExact": 90, "resumeSkillF1": 90, "matchingTop1": 90},
        "passed": {
            "jdFieldExact": float(jd_fields.get("fieldExactAccuracy") or 0) >= 90,
            "resumeSkillF1": resume_metrics["f1"] >= 90,
            "matchingTop1": matching_metrics["top1Accuracy"] >= 90,
        },
        "method": [
            "JD uses the immutable-record-id 120 real JD supported-field gold evaluation.",
            "Resume texts contain no target title, target family, name, phone, address, gender or employer history.",
            "Every sample is ranked against the full governed catalogue of distinct skill profiles.",
            "Targets are selected by deterministic family-balanced traversal, not by post-result cherry-picking.",
        ],
        "limitations": [
            "Resume samples are synthetic and explicitly marked; a real anonymized double-blind resume set remains a separate external validation task.",
            "Matching accuracy measures role retrieval from declared skills and does not imply hiring suitability.",
            "JD exact accuracy is micro-averaged over fields with source evidence; unknown fields are reported separately.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "privacy_resume_global_matching_120.csv", rows)
    write_csv(args.output / "global_matching_failures.csv", failures)
    (args.output / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with Session(engine) as db:
        evaluation = db.scalar(select(EvaluationRun).where(EvaluationRun.suite == SUITE))
        if evaluation:
            evaluation.metrics = summary
            evaluation.passed = all(summary["passed"].values())
        else:
            db.add(
                EvaluationRun(
                    suite=SUITE,
                    metrics=summary,
                    passed=all(summary["passed"].values()),
                )
            )
        db.commit()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(summary["passed"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
