from app.services import calculate_match, rank_role_candidates


def test_missing_dimensions_are_renormalized():
    role = {
        "id": "role-1",
        "name": "Java 开发工程师",
        "skills": [
            {"id": "s1", "name": "Java", "weight": 0.8, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
            {"id": "s2", "name": "MySQL", "weight": 0.4, "sourceCount": 2, "evidenceCount": 3, "confidence": "medium"},
        ],
    }
    result = calculate_match(role, ["Java"])
    assert result["score"] == result["skillScore"]
    assert result["dimensions"][0]["weight"] == 100
    assert result["gaps"][0]["status"] == "matched"


def test_skill_score_only_uses_current_role_requirements_and_weights():
    role = {
        "id": "role-weighted",
        "name": "数据工程师",
        "skills": [
            {"id": "s1", "name": "Python", "weight": 0.9, "sourceCount": 3, "evidenceCount": 8, "confidence": "high"},
            {"id": "s2", "name": "Spark", "weight": 0.4, "sourceCount": 2, "evidenceCount": 4, "confidence": "medium"},
        ],
    }
    focused = calculate_match(role, ["Python"])
    with_unrelated_skill = calculate_match(role, ["Python", "摄影"])

    assert focused["skillScore"] == with_unrelated_skill["skillScore"]
    assert focused["algorithmVersion"] == "match-v3-role-weighted-coverage"


def test_sensitive_attributes_are_not_inputs():
    role = {"id": "role-1", "name": "测试", "skills": []}
    result = calculate_match(role, [], education="本科", experience_years=3)
    assert {item["name"] for item in result["dimensions"]} == {"skills", "education", "experience"}


def test_education_scores_follow_role_requirement_and_radar_level():
    role = {
        "id": "role-education",
        "name": "数据工程师",
        "skills": [],
        "educationRequirement": "本科",
        "educationRequirementRank": 4,
        "educationEvidenceCount": 18,
    }
    results = {level: calculate_match(role, [], education=level) for level in ("大专", "本科", "硕士", "博士")}
    education_scores = {
        level: next(item["score"] for item in result["dimensions"] if item["name"] == "education")
        for level, result in results.items()
    }

    assert education_scores == {"大专": 75.0, "本科": 100.0, "硕士": 100.0, "博士": 100.0}
    assert [results[level]["educationProfile"]["current"] for level in ("大专", "本科", "硕士", "博士")] == [50.0, 66.7, 83.3, 100.0]
    assert all(result["educationProfile"]["target"] == 66.7 for result in results.values())
    assert all(result["educationProfile"]["evidenceCount"] == 18 for result in results.values())


def test_experience_score_updates_with_years_and_caps_at_three_years():
    role = {"id": "role-experience", "name": "测试岗位", "skills": []}
    results = {years: calculate_match(role, [], experience_years=years) for years in (0, 1, 2, 3, 5)}
    scores = {
        years: next(item["score"] for item in result["dimensions"] if item["name"] == "experience")
        for years, result in results.items()
    }

    assert scores == {0: 0.0, 1: 33.3, 2: 66.7, 3: 100.0, 5: 100.0}


def test_radar_targets_follow_role_evidence_instead_of_universal_full_scale():
    role = {
        "id": "role-radar",
        "name": "evidence-backed role",
        "skills": [
            {"id": "s1", "name": "Core", "weight": 0.6, "sourceCount": 3, "evidenceCount": 8, "confidence": "high"},
            {"id": "s2", "name": "Support", "weight": 0.3, "sourceCount": 2, "evidenceCount": 4, "confidence": "medium"},
        ],
        "educationRequirementRank": 4,
        "experienceRequirementMinYears": 5,
    }
    result = calculate_match(role, ["Core"], education="本科", experience_years=3)
    targets = result["radarTargets"]

    assert 58 <= targets["skills"] < 100
    assert 50 < targets["education"] < 80
    assert 50 < targets["experience"] < 90
    assert result["dimensions"][-1]["score"] == 60.0
    assert 50 < targets["breadth"] < 95
    assert 50 < targets["workStyle"] < 95
    assert result["experienceProfile"]["current"] == 37.5


def test_radar_targets_change_with_role_profile():
    analyst = {
        "id": "analyst",
        "name": "数据分析师",
        "skills": [
            {"id": f"a{index}", "name": name, "weight": weight, "sourceCount": 3, "evidenceCount": 8, "confidence": "high"}
            for index, (name, weight) in enumerate((("SQL", .82), ("Python", .71), ("可视化", .62), ("统计", .55)))
        ],
        "educationRequirementRank": 4,
        "experienceRequirementMinYears": 2,
    }
    architect = {
        "id": "architect",
        "name": "数据架构师",
        "skills": [
            {"id": f"b{index}", "name": f"架构能力{index}", "weight": .88 - index * .035, "sourceCount": 4, "evidenceCount": 12, "confidence": "high"}
            for index in range(9)
        ],
        "educationRequirementRank": 5,
        "experienceRequirementMinYears": 6,
    }

    analyst_targets = calculate_match(analyst, ["SQL"], education="本科", experience_years=2)["radarTargets"]
    architect_targets = calculate_match(architect, ["架构能力0"], education="本科", experience_years=2)["radarTargets"]

    assert all(analyst_targets[key] != architect_targets[key] for key in ("skills", "experience", "education", "breadth", "workStyle"))
    assert architect_targets["experience"] > analyst_targets["experience"]
    assert architect_targets["education"] > analyst_targets["education"]
    assert architect_targets["breadth"] > analyst_targets["breadth"]


def test_candidate_ranking_uses_discriminative_core_skills():
    roles = [
        {
            "id": "data",
            "name": "数据工程师",
            "skills": [
                {"id": "python", "name": "Python", "weight": 0.8, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
                {"id": "spark", "name": "Spark", "weight": 0.7, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
                {"id": "hive", "name": "Hive", "weight": 0.6, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
            ],
        },
        {
            "id": "backend",
            "name": "后端工程师",
            "skills": [
                {"id": "python", "name": "Python", "weight": 0.8, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
                {"id": "redis", "name": "Redis", "weight": 0.7, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
                {"id": "mysql", "name": "MySQL", "weight": 0.6, "sourceCount": 3, "evidenceCount": 5, "confidence": "high"},
            ],
        },
    ]
    scores = rank_role_candidates(roles, ["Python", "Spark", "Hive"])
    assert scores["data"] > scores["backend"]
    assert 0 <= scores["backend"] <= 100
