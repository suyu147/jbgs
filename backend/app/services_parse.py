"""Parser registry for the batch extraction and normalization stage."""

from dataclasses import dataclass
from typing import Callable

from .models import RawRecord
from .services import parse_jd


@dataclass(frozen=True)
class Parser:
    name: str
    version: str
    parse: Callable[[RawRecord], dict]


def _parse_job_posting(record: RawRecord) -> dict:
    return parse_jd(record.content)


def _parse_structured(record: RawRecord) -> dict:
    return {key: value for key, value in (record.raw_payload or {}).items()
            if not str(key).startswith("__")}


PARSER_REGISTRY = {
    "JobPosting": Parser("job_posting", "job-posting-parser-v1", _parse_job_posting),
}
DEFAULT_PARSER = Parser("structured", "structured-parser-v1", _parse_structured)


def parse_record(record: RawRecord) -> tuple[str, str, dict]:
    parser = PARSER_REGISTRY.get(record.node_type, DEFAULT_PARSER)
    return parser.name, parser.version, parser.parse(record)
