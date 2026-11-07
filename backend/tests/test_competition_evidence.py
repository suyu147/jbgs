from scripts.build_competition_evidence import (
    build_data_backed_candidates,
    governance_metrics,
    select_submission_examples,
)


def posting(index: int, source: str, month: str, title: str = "AI数据工程师") -> dict:
    return {
        "record_id": f"r{index}",
        "source": source,
        "source_canonical_final": source,
        "source_url": f"https://example.test/{index}",
        "posted_month_canonical": month,
        "job_title_canonical": title,
        "job_category_canonical": "人工智能/大数据/云计算",
        "eligible_for_graph": "true",
        "eligible_monthly_final": "true",
        "eligible_annual_final": "true",
        "description_clean": "负责AI数据管道设计、开发和质量治理",
        "requirements_clean": "熟悉Python与SQL",
        "content_hash": f"hash-{index}",
    }


def test_new_role_candidates_require_cross_source_recent_evidence():
    rows = [
        posting(1, "source-a", "2026-01"),
        posting(2, "source-a", "2026-02"),
        posting(3, "source-b", "2026-02"),
        posting(4, "source-b", "2026-03"),
        posting(5, "source-b", "2026-03"),
    ]
    rows.extend(posting(index, "source-a", "2026-04", "AI单源岗位") for index in range(6, 11))
    skills = [
        {
            "record_id": item["record_id"],
            "skill_id": "skill-python",
            "skill_name": "Python",
            "eligible_for_graph_final": "true",
            "evidence_text_final": "熟悉Python",
        }
        for item in rows[:5]
    ]

    candidates, evidence = build_data_backed_candidates(rows, skills)

    assert [item["role_name"] for item in candidates] == ["AI数据工程师"]
    definition = candidates[0]["definition"]
    assert definition["posting_count"] == 5
    assert definition["source_count"] == 2
    assert definition["source_type"] == "governed_job_postings"
    assert definition["validation_boundary"] == "newly_observed_market_role_candidate_not_official_occupation"
    assert len(evidence) == 5 and all(item["source_url"] for item in evidence)


def test_governance_metrics_expose_dedup_time_and_evidence_boundaries():
    rows = [posting(1, "source-a", "2026-01"), posting(2, "source-b", "2026-02")]
    rows[1]["content_hash"] = rows[0]["content_hash"]
    candidates = [
        {
            "definition": {"source_count": 2, "evidence_record_count": 5},
            "evidence": [{"recordId": "r1", "url": "https://example.test/1", "excerpt": "evidence"}],
        }
    ]
    changes = [{"definition": {"changes": [{"comparison_eligible": True}]}}]

    result = governance_metrics(rows, candidates, changes)

    assert result["sourceCoverage"]["sourceCount"] == 2
    assert result["deduplication"]["exactDuplicateGroups"] == 1
    assert result["deduplication"]["crossSourceDuplicateGroups"] == 1
    assert result["newRoleValidation"]["allCrossSource"] is True
    assert result["hallucinationGuard"]["candidateFactsWithSourceRecord"] == 100


def test_submission_examples_prefer_cross_source_evidence_and_preserve_boundaries():
    new_candidates = [
        {
            "role_name": "单来源候选",
            "definition": {"source_count": 1, "posting_count": 50, "signal_score": 90},
            "evidence": [],
        },
        {
            "role_name": "跨来源候选",
            "definition": {"source_count": 3, "posting_count": 8, "signal_score": 75},
            "evidence": [{"url": "https://example.test/evidence"}],
        },
    ]
    change_candidates = [
        {
            "role_name": "单来源变化",
            "definition": {"source_count": 1, "changes": [{"change_pp": 30}]},
            "evidence": [],
        },
        {
            "role_name": "跨来源变化",
            "definition": {"source_count": 2, "changes": [{"change_pp": 5}]},
            "evidence": [{"url": "https://example.test/change"}],
        },
    ]

    result = select_submission_examples(new_candidates, change_candidates)

    assert result["newRole"]["role_name"] == "跨来源候选"
    assert result["existingRoleUpdate"]["role_name"] == "跨来源变化"
    assert "pending human review" in result["boundary"]["newRole"]
