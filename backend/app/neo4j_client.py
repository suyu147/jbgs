import base64
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import settings


class Neo4jError(RuntimeError):
    pass


class Neo4jHttpClient:
    def __init__(self) -> None:
        token = base64.b64encode(
            f"{settings.neo4j_user}:{settings.neo4j_password}".encode("utf-8")
        ).decode("ascii")
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        self.endpoint = (
            f"{settings.neo4j_url.rstrip('/')}/db/{settings.neo4j_database}/tx/commit"
        )

    def query(self, statement: str, parameters: dict[str, Any] | None = None) -> list[dict]:
        payload = {"statements": [{"statement": statement, "parameters": parameters or {}}]}
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self.headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise Neo4jError(f"Neo4j connection failed: {exc}") from exc
        if body.get("errors"):
            raise Neo4jError(body["errors"][0].get("message", "Neo4j query failed"))
        result = body["results"][0]
        columns = result["columns"]
        return [dict(zip(columns, row["row"], strict=False)) for row in result["data"]]

    def scalar(self, statement: str, parameters: dict[str, Any] | None = None) -> Any:
        rows = self.query(statement, parameters)
        return next(iter(rows[0].values())) if rows else None


neo4j = Neo4jHttpClient()
