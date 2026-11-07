import json
import time
from pathlib import Path

import httpx


BASE_URL = "http://127.0.0.1:8010/api/v1"


def api(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, f"{BASE_URL}{path}", **kwargs)
    response.raise_for_status()
    payload = response.json()
    assert payload["code"] == 0, payload
    assert payload.get("requestId"), payload
    return payload["data"]


def main() -> None:
    results = []
    with httpx.Client(timeout=90) as client:
        health = api(client, "GET", "/health")
        assert health["neo4j"] and health["mysql"]
        results.append("health")

        overview = api(client, "GET", "/overview")
        assert overview["nodeCount"] >= 45471 and overview["relationCount"] >= 115256
        jobs = api(client, "GET", "/jobs", params={"pageSize": 5})
        role_id = jobs["items"][0]["id"]
        detail = api(client, "GET", f"/jobs/{role_id}")
        for suffix in ("aliases", "skills", "postings", "changes"):
            api(client, "GET", f"/jobs/{role_id}/{suffix}")
        results.append("jobs")

        graph = api(client, "GET", "/graph", params={"roleId": role_id})
        assert graph["nodes"] and graph["edges"]
        api(client, "GET", f"/graph/nodes/{role_id}")
        api(client, "GET", f"/graph/nodes/{role_id}/neighbors")
        results.append("graph")

        trends = api(client, "GET", "/evolution/trends", params={"roleId": role_id, "granularity": "year"})
        periods = sorted({point["period"] for series in trends["series"] for point in series["points"]})
        if len(periods) >= 2:
            api(client, "GET", "/evolution/compare", params={"roleId": role_id, "fromPeriod": periods[-2], "toPeriod": periods[-1]})
        api(client, "GET", "/evolution/candidates")
        results.append("evolution")

        sample = Path(__file__).resolve().parents[2] / "应用数据" / "derived" / "smoke-resume.txt"
        sample.write_text("本科学历，3 年开发经验，掌握 Python、SQL、Vue。", encoding="utf-8")
        with sample.open("rb") as stream:
            upload = api(client, "POST", "/resumes", files={"file": (sample.name, stream, "text/plain")})
        for _ in range(120):
            task = api(client, "GET", f"/tasks/{upload['taskId']}")
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.25)
        assert task["status"] == "completed", task
        parsed = task["result"]
        api(
            client,
            "PUT",
            f"/resumes/{parsed['resumeId']}/confirmation",
            json={
                "skills": [item["skill_name"] for item in parsed["skills"]] or ["Python", "SQL", "Vue"],
                "education": parsed["education"],
                "experienceYears": parsed["experienceYears"],
                "certificates": parsed["certificates"],
            },
        )
        results.append("resume")

        user_skills = [item["name"] for item in detail["skills"][:2]] or ["Python"]
        report = api(client, "POST", "/matching/manual", json={"targetRoleId": role_id, "skills": user_skills})
        api(client, "POST", "/matching/recommendations", json={"skills": user_skills, "limit": 3})
        path = api(client, "POST", "/learning-paths", params={"reportId": report["reportId"]})
        assert "stages" in path
        for report_format in ("json", "csv", "pdf"):
            response = client.get(f"{BASE_URL}/reports/{report['reportId']}", params={"format": report_format})
            response.raise_for_status()
            assert response.content
        results.append("matching_and_reports")

        with client.stream(
            "POST",
            f"{BASE_URL}/agent/chat",
            json={"message": "请说明主要技能差距", "reportId": report["reportId"], "roleId": role_id},
        ) as response:
            response.raise_for_status()
            events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
        assert any(event["type"] == "done" for event in events)
        assert any(event["type"] == "evidence" for event in events)
        capabilities = api(client, "GET", "/agent/capabilities")
        assert capabilities["fallback"] == "rules"
        assert capabilities["stream"] == "SSE"
        results.append("agent")

        for path_name in ("/datasets", "/reviews", "/quality/summary", "/admin/versions"):
            api(client, "GET", path_name)
        results.append("admin")

    print(json.dumps({"status": "PASS", "checks": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
