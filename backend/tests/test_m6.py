from types import SimpleNamespace

import pytest

from app.services_graph import close_version_edges, edge_id_for, project_role_version, role_skill_view


class FakeNeo4j:
    def __init__(self):
        self.calls = []

    def query(self, statement, parameters=None):
        self.calls.append((statement, parameters or {}))
        if "RETURN size([old IN olds" in statement:
            return [{"closed": 1, "edgeId": parameters["edge_id"]}]
        if "RETURN count(rel) AS closed" in statement:
            return [{"closed": 2}]
        if "RETURN s.skill_id AS id" in statement and "REQUIRES_SKILL" not in statement:
            return [{"id": "skill:python"}]
        return []


def test_edge_id_contains_role_skill_tier_and_version():
    assert edge_id_for("role:data", "skill:python", "core", "version_1") == "role:data:skill:python:core:version_1"


def test_project_version_closes_previous_edges_and_projects_versioned_edges():
    graph = FakeNeo4j()
    version = SimpleNamespace(
        role_id="role:data", version_id="version_1", candidate_type="new_role",
        definition={"required_skills": [{"skill_id": "skill:python", "skill_name": "Python"}], "bonus_skills": []},
    )
    result = project_role_version(graph, version)
    assert result["projected"] == 1
    assert result["closed"] >= 1
    assert any("edge_id" in params and params["edge_id"] == "role:data:skill:python:core:version_1" for _, params in graph.calls)
    assert any("valid_to=datetime()" in statement for statement, _ in graph.calls)


def test_decrease_closes_open_edge_without_creating_replacement():
    graph = FakeNeo4j()
    version = SimpleNamespace(
        role_id="role:data", version_id="version_2", candidate_type="skill_change",
        definition={"changes": [{"skill_id": "skill:python", "change_type": "decrease"}]},
    )
    result = project_role_version(graph, version)
    assert result["projected"] == 0
    assert result["closed"] == 2
    assert len(graph.calls) == 2


def test_close_version_edges_is_scoped_to_role_and_version():
    graph = FakeNeo4j()
    result = close_version_edges(graph, "role:data", "version_1")
    assert result["closed"] == 2
    statement, params = graph.calls[0]
    assert "rel.version_id=$version_id" in statement
    assert params == {"role_id": "role:data", "version_id": "version_1"}


def test_role_skill_view_builds_current_as_of_and_version_predicates():
    graph = FakeNeo4j()
    for view, kwargs, expected in (
        ("current", {}, "rel.valid_to IS NULL"),
        ("as_of", {"as_of": "2026-11-01T00:00:00"}, "datetime($as_of)"),
        ("version", {"version_id": "version_1"}, "rel.version_id=$version_id"),
    ):
        result = role_skill_view(graph, "role:data", view=view, **kwargs)
        statement, params = next((item for item in reversed(graph.calls) if expected in item[0]), graph.calls[-1])
        assert expected in statement
        assert result["view"] == view
        assert params["role_id"] == "role:data"


def test_as_of_requires_iso_time():
    with pytest.raises(ValueError, match="ISO 8601"):
        role_skill_view(FakeNeo4j(), "role:data", view="as_of", as_of="not-a-date")

