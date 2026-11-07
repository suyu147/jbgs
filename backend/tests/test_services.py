from pathlib import Path
import pytest

from app import services
from app.models import DatasetRegistry


def test_parse_jd_normalizes_education_city_experience_and_salary(monkeypatch):
    monkeypatch.setattr(services, "skill_lexicon", lambda: [])
    parsed = services.parse_jd(
        "岗位名称：数据安全解决方案咨询经理 工作地址：浙江省杭州市西湖区 "
        "学历要求：研究生 经验要求：3-5年 薪资：45-70k·14薪 "
        "岗位职责：负责产品规划。任职要求：熟悉数据安全。"
    )
    assert parsed["title"] == "数据安全解决方案咨询经理"
    assert parsed["city"] == "杭州"
    assert parsed["education"] == "硕士"
    assert parsed["experienceMinYears"] == 3.0
    assert parsed["experienceMaxYears"] == 5.0
    assert parsed["salaryMonthlyMin"] == 45000.0
    assert parsed["salaryMonthlyMax"] == 70000.0


def test_parse_jd_handles_unknown_education_and_campus_experience(monkeypatch):
    monkeypatch.setattr(services, "skill_lexicon", lambda: [])
    parsed = services.parse_jd("测试工程师 学历：学历不限 经验：应届生 薪资：2-3万/年")
    assert parsed["education"] == "不限"
    assert parsed["experienceMinYears"] == 0.0
    assert parsed["experienceMaxYears"] == 0.0
    assert round(parsed["salaryMonthlyMin"], 2) == round(20000 / 12, 2)
    assert round(parsed["salaryMonthlyMax"], 2) == round(30000 / 12, 2)


def test_parse_jd_does_not_read_date_as_experience(monkeypatch):
    monkeypatch.setattr(services, "skill_lexicon", lambda: [])
    parsed = services.parse_jd("数据分析师 发布日期：2026-07-20 工作地点：上海")
    assert parsed["experienceMinYears"] is None
    assert parsed["experienceMaxYears"] is None


def test_parse_jd_supports_daily_and_annual_salary_units(monkeypatch):
    monkeypatch.setattr(services, "skill_lexicon", lambda: [])
    daily = services.parse_jd("岗位名称：实习生 薪资：200-250元/天")
    annual = services.parse_jd("岗位名称：算法工程师 薪资：24-36万/年")
    assert daily["salaryMonthlyMin"] == 4350.0
    assert daily["salaryMonthlyMax"] == 5437.5
    assert annual["salaryMonthlyMin"] == 20000.0
    assert annual["salaryMonthlyMax"] == 30000.0


def test_list_jobs_normalizes_spaces_and_common_separators(monkeypatch):
    calls = []

    def fake_query(query, params):
        calls.append((query, params))
        return []

    monkeypatch.setattr(services.neo4j, "query", fake_query)

    result = services.list_jobs("  Java　开发-工程师  ")

    assert result["total"] == 0
    assert len(calls) == 1
    assert calls[0][1]["keyword"] == "Java　开发-工程师"
    assert calls[0][1]["normalized_keyword"] == "java开发工程师"
    assert "$normalized_keyword" in calls[0][0]


def test_list_jobs_applies_real_filters_and_trends_before_pagination(monkeypatch):
    captured = {}
    rows = [
        {"id": "r1", "name": "岗位甲", "field": "人工智能", "postingCount": 12, "sourceCount": 2, "lastSeen": "2026-06", "skills": []},
        {"id": "r2", "name": "岗位乙", "field": "人工智能", "postingCount": 8, "sourceCount": 2, "lastSeen": "2025-06", "skills": []},
        {"id": "r3", "name": "岗位丙", "field": "人工智能", "postingCount": 6, "sourceCount": 2, "lastSeen": "2026-05", "skills": []},
    ]

    def fake_query(query, params):
        if "MATCH (r:JobRole) WHERE" in query:
            captured["query"] = query
            captured["params"] = params
        return [dict(item) for item in rows]

    monkeypatch.setattr(services.neo4j, "query", fake_query)
    monkeypatch.setattr(
        services,
        "role_trend_map",
        lambda ids: {
            "r1": {"trendLabel": "需求量上升", "trendDirection": "up", "trendChangePp": 2.0, "trendSamples": 3},
            "r2": {"trendLabel": "需求稳定", "trendDirection": "stable", "trendChangePp": 0.4, "trendSamples": 3},
            "r3": {"trendLabel": "需求量上升", "trendDirection": "up", "trendChangePp": 4.0, "trendSamples": 3},
        },
    )

    result = services.list_jobs(
        fields="人工智能", skills="s1,s2", trends="up", posting_bucket="5_19",
        source_counts="2", last_seen_bucket="2026", sort="trend_change_desc", page_size=1,
    )

    assert result["total"] == 2
    assert result["items"][0]["id"] == "r3"
    assert captured["params"]["fields"] == ["人工智能"]
    assert captured["params"]["skills"] == ["s1", "s2"]
    assert captured["params"]["source_counts"] == [2]
    assert "all(skill_id IN $skills" in captured["query"]
    assert "coalesce(required.active,true)=true" in captured["query"]
    assert "SKIP" not in captured["query"] and "LIMIT" not in captured["query"]


def test_list_jobs_keeps_legacy_field_contains_semantics(monkeypatch):
    captured = {}

    def fake_query(query, params):
        captured["query"] = query
        captured["params"] = params
        return []

    monkeypatch.setattr(services.neo4j, "query", fake_query)
    services.list_jobs(field="人工智能")

    assert "CONTAINS toLower($field)" in captured["query"]
    assert captured["params"]["field"] == "人工智能"
    assert captured["params"]["fields"] == []


def test_job_filter_options_use_published_roles_and_real_counts(monkeypatch):
    def fake_query(query, params=None):
        if "r.role_family AS value" in query:
            return [{"value": "人工智能", "label": "人工智能", "count": 2}]
        if "s.skill_id AS value" in query:
            return [{"value": "s1", "label": "Python", "count": 2}]
        return [
            {"id": "r1", "postingCount": 3, "sourceCount": 1, "lastSeen": "2026-06"},
            {"id": "r2", "postingCount": 0, "sourceCount": 0, "lastSeen": ""},
        ]

    monkeypatch.setattr(services.neo4j, "query", fake_query)
    monkeypatch.setattr(
        services,
        "role_trend_map",
        lambda ids: {
            "r1": {"trendDirection": "up"},
            "r2": {"trendDirection": "insufficient"},
        },
    )

    result = services.job_filter_options()

    assert result["fields"][0] == {"value": "人工智能", "label": "人工智能", "count": 2}
    assert result["skills"][0]["label"] == "Python"
    assert next(item for item in result["postingBuckets"] if item["value"] == "none")["count"] == 1
    assert next(item for item in result["sourceCounts"] if item["value"] == "0")["label"] == "无来源"
    assert next(item for item in result["lastSeenBuckets"] if item["value"] == "unknown")["count"] == 1


def test_normalize_search_keyword_preserves_terms_and_removes_separators():
    assert services.normalize_search_keyword(" Java / Spring Boot ") == "java spring boot".replace(" ", "")
    assert services.normalize_search_keyword("数据—开发_工程师") == "数据开发工程师"


def test_role_trends_use_direct_market_share_then_family_evidence(monkeypatch):
    periods = [f"2026-{month:02d}" for month in range(2, 8)]

    def fake_query(query, params=None):
        if "RETURN r.role_id AS roleId,coalesce(r.role_family,'') AS family" in query:
            rows = []
            for period, count in zip(periods, [1, 1, 1, 10, 10, 10]):
                rows.append({"roleId": "r1", "family": "软件", "override": "", "period": period, "postingCount": count})
            rows.extend([
                {"roleId": "r2", "family": "软件", "override": "", "period": None, "postingCount": 0},
                {"roleId": "r3", "family": "无时间证据", "override": "", "period": None, "postingCount": 0},
                {"roleId": "r4", "family": "无时间证据", "override": "新岗位发现", "period": None, "postingCount": 0},
            ])
            return rows
        if "RETURN j.posted_month_canonical AS period,count(j) AS postingCount ORDER BY period" in query:
            return [{"period": period, "postingCount": 100} for period in periods]
        if "RETURN r.role_family AS family,j.posted_month_canonical AS period" in query:
            return [
                {"family": "软件", "period": period, "postingCount": count}
                for period, count in zip(periods, [10, 10, 10, 20, 20, 20])
            ]
        if "RETURN r.role_family AS family,count(r) AS roleCount" in query:
            return [{"family": "软件", "roleCount": 10}, {"family": "无时间证据", "roleCount": 2}]
        raise AssertionError(query)

    monkeypatch.setattr(services.neo4j, "query", fake_query)
    result = services.role_trend_map(["r1", "r2", "r3", "r4"])

    assert result["r1"]["trendDirection"] == "up" and result["r1"]["trendBasis"] == "role"
    assert result["r2"]["trendDirection"] == "up" and result["r2"]["trendBasis"] == "family"
    assert result["r3"]["trendDirection"] == "insufficient"
    assert result["r4"]["trendDirection"] == "new" and result["r4"]["trendBasis"] == "review"
    assert result["r1"]["trendWindow"] == "2026-02—2026-07"


def test_graph_filters_classify_stack_tier_and_seniority_from_evidence():
    role = {
        "name": "大数据平台开发工程师",
        "family": "人工智能/大数据/云计算",
        "categories": "数据工程",
        "experiences": {"3-5 年"},
        "skills": [
            {"skillName": "Spark", "skillType": "大数据"},
            {"skillName": "Hive", "skillType": "大数据"},
        ],
    }
    assert "big_data" in services._role_tech_stacks(role)
    assert services._role_seniority(role) == {"intermediate"}
    tier, importance = services._graph_skill_tier(
        {"weight": 0.8, "sourceCount": 3, "evidenceCount": 8, "confidence": "high"}
    )
    assert tier == "core"
    assert importance >= 0.62


def test_stack_graph_applies_real_filters_before_truncation(monkeypatch):
    rows = [
        {
            "roleId": "r1", "roleName": "大数据开发工程师", "roleFamily": "人工智能/大数据/云计算",
            "jobCategories": "数据工程", "rolePostingCount": 20, "experiences": ["3 年"],
            "skillId": "s1", "skillName": "Spark", "skillType": "大数据", "weight": 0.8,
            "sourceCount": 3, "evidenceCount": 8, "confidence": "high", "tier": "core", "importance": 0.91,
        },
        {
            "roleId": "r2", "roleName": "嵌入式工程师", "roleFamily": "工业互联网/物联网/集成电路",
            "jobCategories": "嵌入式", "rolePostingCount": 12, "experiences": ["5 年以上"],
            "skillId": "s2", "skillName": "STM32", "skillType": "芯片/硬件", "weight": 0.7,
            "sourceCount": 2, "evidenceCount": 5, "confidence": "high", "tier": "core", "importance": 0.82,
        },
    ]
    monkeypatch.setattr(services, "_graph_relationship_rows", lambda role_id="": rows)
    result = services.graph_data(view_mode="stack", tech_stack="big_data", skill_tier="core", seniority="intermediate", limit=10)
    assert result["viewMode"] == "stack"
    assert result["statistics"] == {"roleCount": 1, "skillCount": 1, "relationCount": 1}
    assert {node["id"] for node in result["nodes"]} == {"r1", "s1"}
    assert result["edges"][0]["tier"] == "core"


def test_sparse_role_graph_uses_explicit_family_fallback(monkeypatch):
    def fake_query(query, params=None):
        params = params or {}
        if query.startswith("MATCH (r:JobRole {role_id:$role_id})"):
            return [{
                "roleId": params["role_id"],
                "roleName": "人工智能与大数据其他岗位",
                "roleFamily": "人工智能/大数据/云计算",
                "jobCategories": "数据工程",
                "rolePostingCount": 36,
            }]
        if "r.role_family=$family" in query:
            return [{
                "skillId": "s-spark",
                "skillName": "Spark",
                "skillType": "大数据",
                "weight": 0.34,
                "sourceCount": 2,
                "evidenceCount": 6,
                "supportingRoleCount": 3,
            }]
        raise AssertionError(query)

    monkeypatch.setattr(services.neo4j, "query", fake_query)
    rows, info = services._graph_fallback_rows("r-sparse", 12)
    assert rows and rows[0]["skillId"] == "s-spark"
    assert rows[0]["fallbackSource"] == "same_role_family"
    assert info["fallback"] == "true"


def test_sparse_role_core_view_still_has_nodes_and_marks_scope(monkeypatch):
    monkeypatch.setattr(services, "_graph_relationship_rows", lambda role_id="": [])
    monkeypatch.setattr(services, "role_extended_graph", lambda role_id, visible_skill_ids: ([], []))

    def fake_query(query, params=None):
        params = params or {}
        if query.startswith("MATCH (r:JobRole {role_id:$role_id})"):
            return [{
                "roleId": params["role_id"],
                "roleName": "人工智能与大数据其他岗位",
                "roleFamily": "人工智能/大数据/云计算",
                "jobCategories": "数据工程",
                "rolePostingCount": 36,
            }]
        if "r.role_family=$family" in query:
            return [{
                "skillId": "s-spark",
                "skillName": "Spark",
                "skillType": "大数据",
                "weight": 0.34,
                "sourceCount": 2,
                "evidenceCount": 6,
                "supportingRoleCount": 3,
            }]
        raise AssertionError(query)

    monkeypatch.setattr(services.neo4j, "query", fake_query)
    result = services.graph_data(role_id="r-sparse", skill_tier="core", limit=10)
    assert result["nodes"]
    assert result["appliedFilters"]["fallback"] == "true"
    assert result["appliedFilters"]["fallbackLabel"] == "已用同岗位族技能证据补全"
    assert any(node["type"] == "skill" for node in result["nodes"])
    assert result["edges"][0]["evidenceScope"] == "same_role_family"


def test_role_core_filter_uses_role_relative_weights_when_global_core_is_empty(monkeypatch):
    rows = [{
        "roleId": "r-direct", "roleName": "测试工程师", "roleFamily": "软件工程",
        "jobCategories": "质量保障", "rolePostingCount": 20, "experiences": ["3 年"],
        "skillId": "s-test", "skillName": "自动化测试", "skillType": "测试工具",
        "weight": 0.28, "sourceCount": 1, "evidenceCount": 2, "confidence": "medium",
        "tier": "bonus", "importance": 0.31,
    }]
    monkeypatch.setattr(services, "_graph_relationship_rows", lambda role_id="": rows)
    monkeypatch.setattr(services, "role_extended_graph", lambda role_id, visible_skill_ids: ([], []))
    result = services.graph_data(role_id="r-direct", skill_tier="core", limit=10)
    assert result["appliedFilters"]["tierFallback"] == "true"
    assert any(node["type"] == "skill" for node in result["nodes"])
    assert result["edges"][0]["evidenceScope"] == "role_relative_core"


def test_extract_skills_uses_canonical_ids_and_evidence(monkeypatch):
    monkeypatch.setattr(
        services,
        "skill_lexicon",
        lambda: [
            {"id": "skill_python", "name": "Python", "aliases": ["Python", "python"]},
            {"id": "skill_sql", "name": "SQL", "aliases": ["SQL"]},
        ],
    )
    result = services.extract_skills("熟悉 Python 开发。使用 SQL 完成数据分析。")
    assert [item["skill_id"] for item in result] == ["skill_python", "skill_sql"]
    assert result[0]["evidence"] == "熟悉 Python 开发"


def test_extract_skills_uses_ascii_boundaries_and_ocr_confusables(monkeypatch):
    monkeypatch.setattr(
        services,
        "skill_lexicon",
        lambda: [
            {"id": "skill_js", "name": "JavaScript", "aliases": ["JavaScript", "JS"]},
            {"id": "skill_boot", "name": "Spring Boot", "aliases": ["Spring Boot"]},
        ],
    )
    result = services.extract_skills("熟悉 JSGF 规范，能够使用 Spring B00t 开发。")
    assert [item["skill_id"] for item in result] == ["skill_boot"]
    assert result[0]["evidence"] == "熟悉 JSGF 规范，能够使用 Spring B00t 开发"


def test_parse_text_resume_extracts_confirmable_fields(tmp_path: Path, monkeypatch):
    resume = tmp_path / "resume.txt"
    resume.write_text("本科学历，具备 3 年开发经验。熟悉 Python，并获得云计算认证。", encoding="utf-8")
    monkeypatch.setattr(services, "extract_skills", lambda text: [{"skill_id": "s1", "skill_name": "Python", "evidence": text, "confidence": 1.0}])
    result = services.parse_resume(resume)
    assert result["education"] == "本科"
    assert result["experienceYears"] == 3
    assert result["skills"][0]["skill_id"] == "s1"


def test_parse_text_resume_supports_labelled_experience(tmp_path: Path):
    resume = tmp_path / "labelled-experience.txt"
    resume.write_text("学历：本科\n工作经验：4年\n技能：Python、SQL、数据治理。", encoding="utf-8")

    result = services.parse_resume(resume)

    assert result["education"] == "本科"
    assert result["experienceYears"] == 4


def test_parse_jd_keeps_evidence_and_canonical_skill_ids(monkeypatch):
    monkeypatch.setattr(services, "extract_skills", lambda text: [{"skill_id": "s1", "skill_name": "Python", "evidence": "熟悉 Python", "confidence": 1.0}])
    monkeypatch.setattr(services, "role_skill_ids_for_title", lambda title: set())
    result = services.parse_jd("数据开发工程师 岗位职责：负责数据处理。任职要求：本科，3-5 年工作经验，熟悉 Python。")
    assert result["title"] == "数据开发工程师"
    assert result["education"] == "本科"
    assert result["experienceMinYears"] == 3
    assert result["experienceMaxYears"] == 5
    assert result["skills"][0]["skill_id"] == "s1"
    assert result["responsibilities"]


def test_parse_jd_prefers_explicit_title_and_normalizes_recruitment_suffix(monkeypatch):
    monkeypatch.setattr(services, "extract_skills", lambda text: [])
    monkeypatch.setattr(services, "role_skill_ids_for_title", lambda title: set())
    result = services.parse_jd("职位名称：软件运维（校招） 岗位职责：负责服务部署。任职要求：本科。")
    assert result["title"] == "软件运维"


def test_parse_jd_normalizes_title_code_direction_and_body_without_heading(monkeypatch):
    monkeypatch.setattr(services, "extract_skills", lambda text: [])
    monkeypatch.setattr(services, "role_skill_ids_for_title", lambda title: set())
    assert services.parse_jd("研发工程师（数据开发方向） 任职要求：本科")["title"] == "研发工程师"
    assert services.parse_jd("光芯片设计工程师 (MJ000313) 任职要求：硕士")["title"] == "光芯片设计工程师"
    assert services.parse_jd("硬件测试工程师 1、按时完成产品测试；2、提交报告")["title"] == "硬件测试工程师"


def test_parse_scanned_pdf_uses_windows_ocr(tmp_path: Path, monkeypatch):
    scanned_pdf = tmp_path / "scan.pdf"
    scanned_pdf.write_bytes(b"%PDF fake scanned resume")
    monkeypatch.setattr("pypdf.PdfReader", lambda path: type("Reader", (), {"pages": [type("Page", (), {"extract_text": lambda self: ""})()]})())
    monkeypatch.setattr(
        services,
        "windows_ocr_pdf",
        lambda path: {
            "text": "学历：本科\n项目经历：3 年后端开发经验\n技能：Java、Spring B00t、MySQL、Redis、Docker",
            "engine": "windows-media-ocr",
            "language": "zh-Hans-CN",
            "pages": 1,
        },
    )
    monkeypatch.setattr(
        services,
        "extract_skills",
        lambda text: [{"skill_id": "s1", "skill_name": "Spring Boot", "evidence": text, "confidence": 0.9}],
    )
    result = services.parse_resume(scanned_pdf)
    assert result["education"] == "本科"
    assert result["experienceYears"] == 3
    assert result["ocr"]["engine"] == "windows-media-ocr"
    assert result["warnings"]


def test_evolution_marks_small_samples_as_insufficient(monkeypatch):
    rows = [
        {"skillId": "s1", "skill": "Python", "period": "2024", "value": 0.2, "sampleSize": 3, "change": 0, "changeType": "", "comparisonEligible": "false", "partialWarning": ""},
        {"skillId": "s1", "skill": "Python", "period": "2025", "value": 0.4, "sampleSize": 3, "change": 20, "changeType": "up", "comparisonEligible": "false", "partialWarning": ""},
    ]
    monkeypatch.setattr(services, "_annual_evolution_rows", lambda role_id: rows)
    result = services.compare_evolution("role-1", "2024", "2025")
    assert result["items"][0]["conclusion"] == "insufficient_evidence"


def test_annual_evolution_aggregates_real_monthly_snapshots(monkeypatch):
    monkeypatch.setattr(
        services.neo4j,
        "query",
        lambda *args, **kwargs: [
            {"skillId": "s1", "skill": "Python", "period": "2024", "skillPostingCount": 20, "postingCount": 100},
            {"skillId": "s1", "skill": "Python", "period": "2025", "skillPostingCount": 36, "postingCount": 120},
        ],
    )

    rows = services._annual_evolution_rows("role-1")

    assert rows[0]["value"] == 0.2
    assert rows[1]["value"] == 0.3
    assert rows[1]["change"] == 10.0
    assert rows[1]["comparisonEligible"] is True


def test_agent_refuses_ungrounded_answer(monkeypatch):
    monkeypatch.setattr(services.settings, "agent_provider", "rules")
    answer, provider_available, provider = services.agent_provider_answer("预测未来岗位", {})
    assert provider_available is False
    assert provider == "rules"
    assert "没有可引用" in answer
    assert "不会在无证据时推断" in answer


def test_external_agent_uses_reserved_contract(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b'{"answer":"grounded answer"}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = services.json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(services.settings, "agent_provider", "external")
    monkeypatch.setattr(services.settings, "agent_base_url", "http://127.0.0.1:9900")
    monkeypatch.setattr(services.settings, "agent_chat_path", "/agent/respond")
    monkeypatch.setattr(services.settings, "agent_api_key", "test-key")
    monkeypatch.setattr(services, "urlopen", fake_urlopen)

    answer, available, provider = services.agent_provider_answer("岗位差距", {"roleName": "测试岗位"})

    assert answer == "grounded answer"
    assert available is True
    assert provider == "external"
    assert captured["url"] == "http://127.0.0.1:9900/agent/respond"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["constraints"]["noDirectDatabaseAccess"] is True
    assert captured["payload"]["context"]["roleName"] == "测试岗位"


def test_coze_agent_routes_mode_and_parses_sse(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return (
                b'event: conversation.message.delta\n'
                b'data: {"conversation_id":"conv-123","type":"answer","content":"skill "}\n\n'
                b'event: conversation.message.delta\n'
                b'data: {"conversation_id":"conv-123","type":"answer","content":"analysis complete"}\n\n'
                b'event: done\n'
                b'data: {"conversation_id":"conv-123"}\n\n'
            )

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = services.json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(services.settings, "agent_provider", "coze")
    monkeypatch.setattr(services.settings, "agent_base_url", "https://api.coze.cn")
    monkeypatch.setattr(services.settings, "agent_chat_path", "/v3/chat")
    monkeypatch.setattr(services.settings, "agent_api_key", "test-key")
    monkeypatch.setattr(services.settings, "agent_user_id", "test-user")
    monkeypatch.setattr(services.settings, "agent_career_planning_bot_id", "career-bot")
    monkeypatch.setattr(services.settings, "agent_ability_analysis_bot_id", "ability-bot")
    monkeypatch.setattr(services, "urlopen", fake_urlopen)

    context = {"roleName": "测试岗位", "skills": [{"skill": "Python"}]}
    answer, available, provider = services.agent_provider_answer(
        "解释技能差距", context, agent_mode="ability_analysis", conversation_id="conv-old"
    )

    assert answer == "skill analysis complete"
    assert available is True
    assert provider == "coze"
    assert context["_cozeConversationId"] == "conv-123"
    assert captured["url"] == "https://api.coze.cn/v3/chat"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["bot_id"] == "ability-bot"
    assert captured["payload"]["user_id"] == "test-user"
    assert captured["payload"]["conversation_id"] == "conv-old"
    assert captured["payload"]["stream"] is True


def test_coze_stream_ignores_completed_answer_duplicate():
    assert services.coze_event_text(
        "conversation.message.delta",
        {"type": "answer", "content": "增量"},
    ) == "增量"
    assert services.coze_event_text(
        "conversation.message.completed",
        {"type": "answer", "content": "完整回答"},
    ) == ""


def test_coze_stream_reports_insufficient_credits(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __iter__(self):
            return iter([
                b"event: conversation.chat.failed\n",
                b'data: {"status":"failed","last_error":{"code":4028,"msg":"quota unavailable"}}\n',
            ])

    monkeypatch.setattr(services, "_coze_request", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(services, "urlopen", lambda *_args, **_kwargs: Response())

    with pytest.raises(services.AgentProviderError) as caught:
        list(services.coze_agent_stream("quota-check-unique", {}, "ability_analysis"))

    assert caught.value.reason == "insufficient_credits"


def test_rule_agent_answer_describes_fallback_and_missing_diagnosis():
    answer = services.rule_agent_answer(
        {"roleName": "数据工程师", "score": "--", "gaps": []},
        "insufficient_credits",
    )

    assert "尚未完成能力诊断" in answer
    assert "--%" not in answer
    assert "Coze 额度不足" in answer
    assert "尚未接入" not in answer


def test_new_role_definition_contains_reviewable_sections():
    candidate = {
        "job_category": "人工智能/大数据/云计算",
        "first_seen_month": "2026-04",
        "latest_seen_month": "2026-07",
        "posting_count": "2",
        "source_count": "2",
        "candidate_reason": "multi_source_emerging_term",
    }
    postings = [
        {"record_id": "r1", "source": "来源甲", "source_url": "https://example/a", "description_clean": "负责模型训练与推理服务开发。", "industry": "软件与信息服务", "job_category_canonical": "人工智能", "posted_month_canonical": "2026-06"},
        {"record_id": "r2", "source": "来源乙", "source_url": "https://example/b", "description_clean": "主导模型评测并推动业务落地。", "industry": "智能制造", "job_category_canonical": "人工智能", "posted_month_canonical": "2026-07"},
    ]
    skill_rows = [
        {"record_id": "r1", "skill_id": "s1", "skill_name": "Python", "evidence_text": "熟悉 Python", "eligible_for_graph_final": "true"},
        {"record_id": "r2", "skill_id": "s1", "skill_name": "Python", "evidence_text": "使用 Python", "eligible_for_graph_final": "true"},
        {"record_id": "r2", "skill_id": "s2", "skill_name": "PyTorch", "evidence_text": "熟悉 PyTorch", "eligible_for_graph_final": "true"},
    ]
    definition, evidence = services.build_new_role_definition(candidate, postings, skill_rows)
    assert len(definition["core_responsibilities"]) == 2
    assert definition["required_skills"][0]["skill_id"] == "s1"
    assert definition["application_scenarios"]
    assert len(evidence) == 2 and evidence[0]["recordId"] == "r1"


def test_dataset_graph_sync_keeps_review_data_out_of_business_graph(tmp_path: Path, monkeypatch):
    path = tmp_path / "skills.csv"
    path.write_text("skill_id,entity_name,review_status_final\ns1,Python,approved\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(services.neo4j, "query", lambda query, params=None: calls.append((query, params)) or [])
    dataset = DatasetRegistry(
        id="dataset_review", name="复核技能", category="测试", path=str(path), record_count=1,
        version="v1", usage_boundary="review", sha256="abc",
    )

    result = services.sync_dataset_to_graph(dataset, path)

    assert result["mode"] == "metadata_only"
    assert "复核数据" in result["message"]
    assert len(calls) == 1 and "DatasetAsset" in calls[0][0]


def test_dataset_graph_sync_upserts_supported_formal_nodes(tmp_path: Path, monkeypatch):
    path = tmp_path / "skills.csv"
    path.write_text(
        "skill_id,entity_name,review_status_final,eligible_for_graph_final\n"
        "s1,Python,approved,true\ns2,待复核技能,pending,true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(services.neo4j, "query", lambda *args, **kwargs: [])
    monkeypatch.setattr(services.neo4j, "scalar", lambda query, params=None: len((params or {}).get("rows", [])))
    dataset = DatasetRegistry(
        id="dataset_formal", name="正式技能", category="节点", path=str(path), record_count=2,
        version="v2", usage_boundary="formal", sha256="def",
    )

    result = services.sync_dataset_to_graph(dataset, path)

    assert result["mode"] == "graph_upsert"
    assert result["schema"] == "Skill"
    assert result["rowsAccepted"] == 1
    assert result["nodesMerged"] == 1


def test_entity_graph_prefix_mapping_preserves_neighbor_identity():
    node = services._entity_node(
        {"toLabels": ["Certificate"], "toId": "cert_1", "toName": "云计算认证", "toSourceUrl": "https://example.test"},
        "to",
    )
    assert node["id"] == "cert_1"
    assert node["name"] == "云计算认证"
    assert node["type"] == "certificate"


def test_entity_graph_maps_time_period_nodes():
    node = services._entity_node(
        {"labels": ["TimePeriod"], "id": "month_2026_07", "name": "2026-07"},
    )
    assert node["id"] == "month_2026_07"
    assert node["type"] == "period"


def test_forecast_curve_supports_complete_monthly_projection():
    points = [
        {"period": f"2025-{month:02d}", "value": float(month)}
        for month in range(1, 13)
    ] + [
        {"period": f"2026-{month:02d}", "value": float(month + 12)}
        for month in range(1, 8)
    ]
    result = services._forecast_curve(points, horizon=1, factor=1.0, granularity="month")
    assert result["granularity"] == "month"
    assert len(result["points"]) == 31
    assert result["points"][0]["period"] == "2025-01"
    assert result["points"][-1]["period"] == "2027-07"
    assert all(point["observed"] for point in result["points"][:19])
    assert all(not point["observed"] for point in result["points"][19:])


def test_parse_jd_extracts_full_fields_and_normalizes_salary_units(monkeypatch):
    monkeypatch.setattr(services, "extract_skills", lambda text: [])
    monkeypatch.setattr(services, "role_skill_ids_for_title", lambda title: set())
    text = (
        "\u804c\u4f4d\u540d\u79f0\uff1a\u6570\u636e\u5206\u6790\u5e08\u3002\u5de5\u4f5c\u5730\u70b9\uff1a\u4e0a\u6d77\u3002"
        "\u5c97\u4f4d\u804c\u8d23\uff1a\u8d1f\u8d23\u6570\u636e\u5206\u6790\u3002"
        "\u4efb\u804c\u8981\u6c42\uff1a\u672c\u79d1\uff0c3-5\u5e74\u5de5\u4f5c\u7ecf\u9a8c\u3002"
        "\u85aa\u8d44\uff1a20-30K/\u6708\u3002"
    )
    result = services.parse_jd(text)
    assert result["title"] == "\u6570\u636e\u5206\u6790\u5e08"
    assert result["city"] == "\u4e0a\u6d77"
    assert result["education"] == "\u672c\u79d1"
    assert (result["experienceMinYears"], result["experienceMaxYears"]) == (3, 5)
    assert (result["salaryMonthlyMin"], result["salaryMonthlyMax"]) == (20000, 30000)
    assert result["responsibilities"]
    assert result["salaryEvidence"] and result["responsibilityEvidence"]


def test_parse_jd_supports_annual_salary_and_unlimited_experience(monkeypatch):
    monkeypatch.setattr(services, "extract_skills", lambda text: [])
    monkeypatch.setattr(services, "role_skill_ids_for_title", lambda title: set())
    annual = services.parse_jd("\u5c97\u4f4d\u540d\u79f0\uff1a\u4ea7\u54c1\u7ecf\u7406\u3002\u4efb\u804c\u8981\u6c42\uff1a\u7855\u58eb\uff0c3\u5e74\u4ee5\u4e0a\u7ecf\u9a8c\u3002\u85aa\u8d44\uff1a2-3\u4e07/\u5e74")
    unlimited = services.parse_jd("\u5c97\u4f4d\u540d\u79f0\uff1a\u6d4b\u8bd5\u5de5\u7a0b\u5e08\u3002\u4efb\u804c\u8981\u6c42\uff1a\u7ecf\u9a8c\u4e0d\u9650\u3002")
    assert annual["salaryMonthlyMin"] == 20000 / 12
    assert annual["salaryMonthlyMax"] == 30000 / 12
    assert annual["experienceMinYears"] == 3
    assert unlimited["experienceMinYears"] == unlimited["experienceMaxYears"] == 0


def test_parse_scanned_pdf_warns_when_optional_ocr_fails(tmp_path: Path, monkeypatch):
    scanned_pdf = tmp_path / "scan-failed.pdf"
    scanned_pdf.write_bytes(b"%PDF fake scanned resume")
    monkeypatch.setattr("pypdf.PdfReader", lambda path: type("Reader", (), {"pages": [type("Page", (), {"extract_text": lambda self: ""})()]})())
    monkeypatch.setattr(services, "windows_ocr_pdf", lambda path: {"text": "", "error": "OCR unavailable", "engine": "windows-media-ocr"})
    monkeypatch.setattr(services, "rapidocr_pdf", lambda path: {"text": "", "error": "RapidOCR unavailable", "engine": "rapidocr"})
    result = services.parse_resume(scanned_pdf)
    assert result["text"] == ""
    assert result["warnings"]
    assert result["ocr"]["engine"] == "digital-text"


def test_forecast_ignores_low_sample_points_when_eligible_training_exists():
    points = [
        {"period": f"2025-{month:02d}", "value": 0.1 if month % 2 else 0.9, "sampleSize": 1}
        for month in range(1, 7)
    ] + [
        {"period": f"2025-{month:02d}", "value": 0.2 + month * 0.01, "sampleSize": 20}
        for month in range(7, 13)
    ]
    result = services._forecast_curve(points, horizon=1, factor=1.0, granularity="month")
    assert result["sampleFloor"] == 5
    assert result["eligibleSampleSize"] == 6
    assert result["modelSampleSize"] == 6
    assert all(point["comparisonEligible"] is False for point in result["points"] if not point["observed"])


def test_skill_demand_smoothing_replaces_sparse_zeros_and_limits_spikes():
    points = [
        {"period": "2025-01", "value": 0.0, "sampleSize": 0},
        {"period": "2025-02", "value": 100.0, "sampleSize": 1},
        {"period": "2025-03", "value": 0.0, "sampleSize": 1},
        {"period": "2025-04", "value": 35.0, "sampleSize": 20},
        {"period": "2025-05", "value": 40.0, "sampleSize": 24},
    ]

    result = services._smooth_skill_demand_points(points)

    assert len(result) == len(points)
    assert all(point["value"] > 0 for point in result)
    assert result[1]["value"] < 80
    assert result[0]["value"] >= result[2]["value"]
    assert [point["sampleSize"] for point in result] == [0, 1, 1, 20, 24]


def test_role_demand_normalization_removes_common_corpus_volume_surge():
    market = [
        {"period": f"2025-{month:02d}", "marketCount": 20}
        for month in range(1, 13)
    ] + [
        {"period": f"2026-{month:02d}", "marketCount": 200}
        for month in range(1, 13)
    ]
    role = [
        {"period": f"2025-{month:02d}", "value": 2}
        for month in range(1, 13)
    ] + [
        {"period": f"2026-{month:02d}", "value": 20}
        for month in range(1, 13)
    ]

    normalized = services._normalize_role_demand_points(role, market, max_recent_postings=120)

    old_year = sum(point["value"] for point in normalized[:12]) / 12
    new_year = sum(point["value"] for point in normalized[12:]) / 12
    assert abs(new_year - old_year) < 3


def test_role_demand_normalization_preserves_role_specific_share_decline():
    market = [
        {"period": f"2025-{month:02d}", "marketCount": 100}
        for month in range(1, 13)
    ] + [
        {"period": f"2026-{month:02d}", "marketCount": 200}
        for month in range(1, 13)
    ]
    role = [
        {"period": f"2025-{month:02d}", "value": 15}
        for month in range(1, 13)
    ] + [
        {"period": f"2026-{month:02d}", "value": 10}
        for month in range(1, 13)
    ]

    normalized = services._normalize_role_demand_points(role, market, max_recent_postings=180)

    assert normalized[-1]["value"] < normalized[11]["value"]


def test_compact_agent_context_preserves_evidence_urls_and_confidence():
    result = services._compact_agent_context({
        "roleId": "r1",
        "roleName": "\u6570\u636e\u5f00\u53d1\u5de5\u7a0b\u5e08",
        "skills": [{"skillId": "s1", "skill": "Python", "sourceUrls": ["https://example.test/jd"], "evidence": "\u719f\u6089 Python", "confidence": "high"}],
    })
    assert result["skills"][0]["sourceUrls"] == ["https://example.test/jd"]
    assert result["skills"][0]["confidence"] == "high"
    assert result["skills"][0]["evidence"]


def test_agent_stream_cache_replays_completed_answer_without_upstream(monkeypatch):
    context = {"roleId": "role-cache", "roleName": "\u6d4b\u8bd5\u5c97\u4f4d"}
    key = services._agent_cache_key("\u8bf7\u603b\u7ed3", context, "career_planning", "")
    services._store_agent_response(key, "\u5feb\u901f\u56de\u7b54", "conv-cache")

    def fail_upstream(*args, **kwargs):
        raise AssertionError("cache should avoid upstream request")

    monkeypatch.setattr(services, "_coze_request", fail_upstream)
    events = list(services.coze_agent_stream("\u8bf7\u603b\u7ed3", context, "career_planning"))
    answer = "".join(item.get("content", "") for name, item in events if "delta" in name)
    assert answer == "\u5feb\u901f\u56de\u7b54"
    assert events[-1][0] == "done" and events[-1][1]["cached"] is True
