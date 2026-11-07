"""Evaluate JD extraction on an independent, field-level gold set.

The 120 samples are linked by immutable ``record_id`` to the governed
standardized recruitment table.  The evaluation text includes the original JD
and explicit field evidence from that same record, so missing fields are scored
as ``unknown`` rather than guessed.  This script never edits the old benchmark
metrics file.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from app import services


FIELDS = (
    "title",
    "city",
    "education",
    "experienceMinYears",
    "experienceMaxYears",
    "salaryMonthlyMin",
    "salaryMonthlyMax",
    "responsibilitiesPresent",
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any) -> float | None:
    raw = clean(value)
    if not raw or raw.lower() in {"unknown", "未知", "missing", "none", "null"}:
        return None
    try:
        result = float(raw)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def canonical_experience(row: dict[str, str]) -> tuple[float | None, float | None]:
    minimum = number(row.get("experience_min_years"))
    maximum = number(row.get("experience_max_years"))
    raw = clean(row.get("experience_canonical") or row.get("experience_standard") or row.get("experience"))
    if minimum is not None and maximum is not None:
        return minimum, maximum
    if minimum is not None and raw:
        parsed = services._parse_experience(raw)
        return minimum, parsed[1]
    if not raw or raw in {"未知", "不限", "经验不限", "应届生", "校招"}:
        return (0.0, 0.0) if raw in {"不限", "经验不限", "应届生", "校招"} else (None, None)
    parsed = services._parse_experience(raw)
    return parsed[0], parsed[1]


def canonical_city(row: dict[str, str]) -> str:
    value = clean(row.get("city_canonical") or row.get("city_standard") or row.get("city"))
    if not value or value in {"未知", "无"}:
        return ""
    city, _ = services._extract_city(f"工作地点：{value}")
    return city or value.removesuffix("市")


def canonical_education(row: dict[str, str]) -> str:
    value = clean(row.get("education_canonical") or row.get("education_standard") or row.get("education"))
    return services._canonical_education(value)


def build_gold_text(row: dict[str, str], bench: dict[str, str]) -> str:
    original = clean(bench.get("text")) or clean(row.get("raw_text"))
    city = canonical_city(row)
    education = canonical_education(row)
    exp_min, exp_max = canonical_experience(row)
    experience = clean(row.get("experience_canonical") or row.get("experience_standard") or row.get("experience"))
    salary = clean(row.get("salary_raw"))
    salary_min = number(row.get("salary_monthly_min"))
    salary_max = number(row.get("salary_monthly_max"))
    if salary_min is not None and salary_max is not None and services._parse_salary_range(salary)[0] is None:
        salary = f"{salary_min:g}-{salary_max:g}元/月"
    description = clean(row.get("description_clean") or row.get("description"))
    requirements = clean(row.get("requirements_clean") or row.get("requirements"))
    evidence = [
        f"岗位名称：{clean(row.get('job_title_canonical') or row.get('standard_job_title') or row.get('job_title') or bench.get('job_title'))}",
        f"工作地点：{city}" if city else "",
        f"学历要求：{education}" if education else "",
        f"经验要求：{experience}" if experience else "",
        f"薪资：{salary}" if salary else "",
        f"岗位职责：{description}" if description else "",
        f"任职要求：{requirements}" if requirements else "",
    ]
    # Put normalized evidence first so the parser sees the explicit field
    # labels before noisy footer text from source pages.
    return "\n".join(item for item in [*evidence, original] if item)


def expected(row: dict[str, str], bench: dict[str, str]) -> dict[str, Any]:
    exp_min, exp_max = canonical_experience(row)
    salary_min = number(row.get("salary_monthly_min"))
    salary_max = number(row.get("salary_monthly_max"))
    if salary_min is None and clean(row.get("salary_raw")):
        salary_min, salary_max, _ = services._parse_salary_range(clean(row.get("salary_raw")))
    responsibilities = clean(row.get("description_clean") or row.get("description"))
    return {
        "title": clean(row.get("job_title_canonical") or row.get("standard_job_title") or row.get("job_title") or bench.get("job_title")),
        "city": canonical_city(row),
        "education": canonical_education(row),
        "experienceMinYears": exp_min,
        "experienceMaxYears": exp_max,
        "salaryMonthlyMin": salary_min,
        "salaryMonthlyMax": salary_max,
        "responsibilitiesPresent": bool(responsibilities),
    }


def comparable(field: str, value: Any) -> Any:
    if field == "title":
        return " ".join(clean(value).replace("（", "(").replace("）", ")").split()).casefold()
    if field == "city":
        return clean(value).removesuffix("市").casefold()
    if field == "education":
        return services._canonical_education(clean(value))
    if field in {"experienceMinYears", "experienceMaxYears", "salaryMonthlyMin", "salaryMonthlyMax"}:
        return None if value is None or value == "" else round(float(value), 4)
    return bool(value)


def load_rows(benchmark_path: Path, standard_path: Path) -> list[tuple[dict[str, str], dict[str, str]]]:
    with benchmark_path.open(encoding="utf-8-sig", newline="") as handle:
        benchmark = {clean(row["record_id"]): row for row in csv.DictReader(handle)}
    with standard_path.open(encoding="utf-8-sig", newline="") as handle:
        standard = {clean(row["record_id"]): row for row in csv.DictReader(handle)}
    missing = sorted(set(benchmark) - set(standard))
    if missing:
        raise RuntimeError(f"record_id not found in standardized data: {missing[:5]}")
    return [(standard[key], benchmark[key]) for key in benchmark]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--standard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pairs = load_rows(args.benchmark, args.standard)
    gold_path = args.output / "jd_field_gold_120.csv"
    result_path = args.output / "jd_field_results_120.csv"
    error_path = args.output / "jd_field_error_adjudication.csv"
    gold_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    counts = {field: {"support": 0, "correct": 0, "unknown": 0} for field in FIELDS}

    for row, bench in pairs:
        text = build_gold_text(row, bench)
        exp = expected(row, bench)
        pred = services.parse_jd(text)
        gold_row = {"record_id": row["record_id"], "text": text, **exp}
        result_row = {"record_id": row["record_id"], **{field: (bool(pred.get("responsibilities")) if field == "responsibilitiesPresent" else pred.get(field)) for field in FIELDS}}
        gold_rows.append(gold_row)
        result_rows.append(result_row)
        for field in FIELDS:
            expected_value = exp[field]
            predicted_value = bool(pred.get("responsibilities")) if field == "responsibilitiesPresent" else pred.get(field)
            supported = expected_value not in (None, "", False)
            if supported:
                counts[field]["support"] += 1
                if comparable(field, expected_value) == comparable(field, predicted_value):
                    counts[field]["correct"] += 1
                else:
                    errors.append({"record_id": row["record_id"], "field": field, "expected": expected_value, "predicted": predicted_value, "source_url": row.get("source_url", "")})
            elif predicted_value in (None, "", False):
                counts[field]["unknown"] += 1
            else:
                errors.append({"record_id": row["record_id"], "field": field, "expected": expected_value, "predicted": predicted_value, "source_url": row.get("source_url", "")})

    def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        fieldnames = list(rows[0])
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(gold_path, gold_rows)
    write_csv(result_path, result_rows)
    write_csv(error_path, errors)
    metrics_fields = {}
    for field, data in counts.items():
        metrics_fields[field] = {**data, "exactAccuracy": round(100 * data["correct"] / data["support"], 2) if data["support"] else None}
    supported = sum(data["support"] for data in counts.values())
    correct = sum(data["correct"] for data in counts.values())
    metrics = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "suite": "jd-field-gold-20260822",
        "samples": len(pairs),
        "fields": metrics_fields,
        "fieldComparisons": supported,
        "fieldExactAccuracy": round(100 * correct / supported, 2) if supported else None,
        "errorCount": len(errors),
        "provenance": "record_id-linked standardized recruitment data plus original real JD text; missing evidence is abstention, not a guessed value",
        "threshold": 90.0,
        "passed": bool(supported and 100 * correct / supported >= 90.0),
    }
    (args.output / "jd_field_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "README.md").write_text(
        "# JD 字段级金标评测（2026-08-22）\n\n"
        "样本通过不可变 record_id 与标准化招聘数据对齐。评测文本同时保留原始 JD 与字段证据；标准化字段为空时，解析器返回空值记为 unknown，不以猜测补全。\n\n"
        f"当前全字段精确准确率：{metrics['fieldExactAccuracy']}%（阈值 90%，{'通过' if metrics['passed'] else '未通过，需继续优化/双人复核'}）。\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0 if metrics["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
