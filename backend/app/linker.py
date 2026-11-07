"""Deterministic, batch-scoped entity candidate indexing and linking."""

import json
import re
import unicodedata
from collections import defaultdict
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import EXAMPLE_ROOT
from .models import DatasetRegistry
from .neo4j_client import neo4j


LINKER_VERSION = "entity-linker-v1"
ACTIVE_LINKER: ContextVar["EntityLinker | None"] = ContextVar("active_entity_linker", default=None)
MAX_DYNAMIC_CITIES = 20
EDUCATION_TERMS = (
    "博士", "硕士", "研究生", "本科", "学士", "大专", "专科", "高职", "高中", "中专", "不限",
)
ENTITY_LABELS = {"Skill": "Skill", "JobRole": "JobRole", "Company": "Company"}
ENTITY_KEYS = {"Skill": "skill_id", "JobRole": "role_id", "Company": "company_id"}


def normalize_surface(value: str) -> str:
    return re.sub(r"[\s\u3000_-]+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def _edit_similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for row, char_left in enumerate(left, 1):
        current = [row]
        for column, char_right in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (char_left != char_right),
            ))
        previous = current
    return 1 - previous[-1] / max(len(left), len(right))


def _entity_id(row: dict, entity_type: str) -> str:
    return str(row.get("id") or row.get(ENTITY_KEYS[entity_type]) or "")


class EntityLinker:
    def __init__(self, entities: list[dict] | None = None, *, missing_eligibility: dict | None = None,
                 dynamic_cities: list[str] | None = None):
        self.entities: dict[str, dict[str, dict]] = defaultdict(dict)
        self.aliases: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        self.buckets: dict[str, dict[tuple[str, int], list[dict]]] = defaultdict(lambda: defaultdict(list))
        self.missing_eligibility = missing_eligibility or {}
        self.dynamic_city_count = 0
        for entity in entities or []:
            self.add_entity(entity)
        city_path = EXAMPLE_ROOT / "frontend" / "src" / "data" / "chinaCities.json"
        if city_path.exists():
            for city in json.loads(city_path.read_text(encoding="utf-8")):
                name = str(city.get("n") or "").strip()
                if name:
                    canonical = name[:-1] if name.endswith("市") else name
                    self.add_entity({"id": f"city:{canonical}", "type": "City", "name": canonical,
                                     "aliases": [name], "origin": "synthetic"})
        for name in EDUCATION_TERMS:
            self.add_entity({"id": f"education:{name}", "type": "Education", "name": name,
                             "aliases": [], "origin": "synthetic"})
        for city in (dynamic_cities or []):
            self.add_dynamic_city(city)

    def add_dynamic_city(self, city: str) -> None:
        canonical = str(city).strip()
        known = any(normalize_surface(item["name"]) == normalize_surface(canonical)
                    for item in self.entities["City"].values())
        if canonical and self.dynamic_city_count < MAX_DYNAMIC_CITIES and not known:
            self.add_entity({"id": f"city:{canonical}", "type": "City", "name": canonical,
                             "aliases": [], "origin": "synthetic"})
            self.dynamic_city_count += 1

    def add_entity(self, entity: dict) -> None:
        entity_type = str(entity.get("type") or "")
        entity_id = str(entity.get("id") or "")
        name = str(entity.get("name") or "").strip()
        if not entity_type or not entity_id or not name:
            return
        item = {"id": entity_id, "type": entity_type, "name": name,
                "aliases": list(entity.get("aliases") or []), "origin": entity.get("origin", "asset")}
        key = normalize_surface(name)
        self.entities[entity_type][entity_id] = item
        for alias in {name, *item["aliases"]}:
            normalized = normalize_surface(alias)
            if normalized:
                self.aliases[entity_type][normalized].append(item)
        first = key[:1]
        self.buckets[entity_type][(first, len(key))].append(item)

    def link(self, entity_type: str, surface: str) -> dict:
        surface = str(surface or "").strip()
        normalized = normalize_surface(surface)
        if not normalized:
            return {"entity_id": None, "confidence": 0.0, "status": "new_candidate", "candidates": [], "origin": "asset"}
        exact = [item for item in self.entities.get(entity_type, {}).values()
                 if normalize_surface(item["name"]) == normalized]
        if exact:
            return self._result(exact, 1.0, "accepted")
        aliases = [item for item in self.aliases.get(entity_type, {}).get(normalized, [])
                   if normalize_surface(item["name"]) != normalized]
        if aliases:
            return self._result(aliases, 0.9, "accepted")

        matches = []
        for (first, length), items in self.buckets.get(entity_type, {}).items():
            if first != normalized[:1] or abs(length - len(normalized)) > 2:
                continue
            for item in items:
                score = _edit_similarity(normalized, normalize_surface(item["name"]))
                if 0.8 <= score < 1.0:
                    confidence = min(0.75, 0.6 + (score - 0.8) * 1.5)
                    matches.append((item, confidence))
        if matches:
            best = max(score for _, score in matches)
            winners = [item for item, score in matches if abs(score - best) < 1e-9]
            return self._result(winners, best, "accepted" if len(winners) == 1 and best >= 0.6 else "unresolved")

        containing = [item for item in self.entities.get(entity_type, {}).values()
                      if normalized in normalize_surface(item["name"]) or normalize_surface(item["name"]) in normalized]
        if containing:
            return self._result(containing, 0.5, "unresolved")
        return {"entity_id": None, "confidence": 0.0, "status": "new_candidate", "candidates": [], "origin": "asset"}

    def extract_skills(self, text: str) -> list[dict]:
        found = []
        occupied = set()
        sentences = [part.strip() for part in re.split(r"[\n。；;]", text) if part.strip()]
        for item in self.entities.get("Skill", {}).values():
            names = [item["name"], *item["aliases"]]
            matched = next((alias for alias in sorted(names, key=len, reverse=True)
                            if alias and _surface_span(text, alias) is not None), None)
            if not matched:
                continue
            result = self.link("Skill", matched)
            if result["entity_id"] in occupied:
                continue
            start_end = _surface_span(text, matched)
            evidence = next((sentence for sentence in sentences if _surface_span(sentence, matched)), "")
            found.append({"skill_id": result["entity_id"] or "", "skill_name": item["name"],
                          "evidence": evidence[:300], "confidence": result["confidence"],
                          "raw_record_id": "", "link_status": result["status"],
                          "link_candidates": result["candidates"], "surface_form": text[start_end[0]:start_end[1]]})
            occupied.add(result["entity_id"] or normalize_surface(matched))
            if len(found) >= 80:
                break
        return found

    @staticmethod
    def _result(items: list[dict], confidence: float, status: str) -> dict:
        candidates = [{"entityId": item["id"], "name": item["name"], "confidence": round(confidence, 4),
                      "origin": item["origin"]} for item in items[:3]]
        if len(items) > 1:
            status = "unresolved"
        return {"entity_id": items[0]["id"] if len(items) == 1 and status == "accepted" else None,
                "confidence": round(confidence, 4), "status": status, "candidates": candidates,
                "origin": items[0]["origin"] if len(items) == 1 else "asset"}


def _surface_span(text: str, alias: str) -> tuple[int, int] | None:
    start = text.casefold().find(alias.casefold())
    if start >= 0:
        return start, start + len(alias)
    return None


def refresh_entity_linker(db: Session, *, dynamic_cities: list[str] | None = None, neo4j_client=neo4j) -> EntityLinker:
    dataset_ids = list(db.scalars(select(DatasetRegistry.id).where(DatasetRegistry.usage_boundary == "formal")).all())
    if not dataset_ids:
        return EntityLinker(dynamic_cities=dynamic_cities)
    query = (
        "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) AND n.dataset_id IN $dataset_ids "
        "AND toLower(toString(coalesce(n.eligible_for_graph_final,n.eligible_for_graph,'true')))='true' "
        "RETURN labels(n) AS labels, n.skill_id AS skill_id, n.role_id AS role_id, n.company_id AS company_id, "
        "coalesce(n.entity_name,n.skill_name,n.role_name,n.company_name,n.name) AS name, "
        "coalesce(n.aliases_canonical,n.aliases) AS aliases"
    )
    rows = neo4j_client.query(query, {"labels": list(ENTITY_LABELS.values()), "dataset_ids": dataset_ids})
    entities = []
    for row in rows:
        label = next((item for item in row.get("labels", []) if item in ENTITY_LABELS), "")
        if not label:
            continue
        aliases = row.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [part.strip() for part in re.split(r"[;,；、]", aliases) if part.strip()]
        entities.append({"id": _entity_id(row, label), "type": label, "name": row.get("name"), "aliases": aliases})
    missing_query = (
        "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) AND n.dataset_id IN $dataset_ids "
        "AND n.eligible_for_graph_final IS NULL AND n.eligible_for_graph IS NULL "
        "RETURN head(labels(n)) AS entity_type,count(n) AS count"
    )
    missing = {key: 0 for key in ENTITY_LABELS}
    missing.update({str(row.get("entity_type")): int(row.get("count") or 0) for row in
                    neo4j_client.query(missing_query, {"labels": list(ENTITY_LABELS.values()), "dataset_ids": dataset_ids})})
    return EntityLinker(entities, missing_eligibility=missing, dynamic_cities=dynamic_cities)
