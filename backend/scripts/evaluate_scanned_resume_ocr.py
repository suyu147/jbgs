"""Create raster-only resume PDFs and evaluate the real OCR fallback."""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import APP_DATA_ROOT  # noqa: E402
from app.services import parse_resume  # noqa: E402


SUITE = "scan-ocr-20260825-v01"


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


def font_path() -> Path:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def build_scan_pdf(text: str, target: Path) -> None:
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(font_path()), 48)
    body_font = ImageFont.truetype(str(font_path()), 34)
    draw.text((130, 110), "个人能力档案", fill="#173f3a", font=title_font)
    y = 220
    for line in wrap_text(draw, text, body_font, 1394):
        draw.text((130, y), line, fill="#202828", font=body_font)
        y += 58
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as image_file:
        image_path = Path(image_file.name)
    try:
        image.save(image_path, "JPEG", quality=88, optimize=True)
        document = canvas.Canvas(str(target), pagesize=A4)
        document.drawImage(ImageReader(str(image_path)), 0, 0, width=A4[0], height=A4[1])
        document.save()
    finally:
        image_path.unlink(missing_ok=True)


def normalized_text(text: str) -> str:
    return re.sub(r"\W+", "", text.casefold(), flags=re.UNICODE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=APP_DATA_ROOT / "quality" / "acceptance-20260825-v04" / "privacy_resume_global_matching_120.csv",
    )
    parser.add_argument("--output", type=Path, default=APP_DATA_ROOT / "quality" / SUITE)
    parser.add_argument("--limit", type=int, default=24)
    args = parser.parse_args()
    if not args.benchmark.exists():
        raise SystemExit(f"missing benchmark: {args.benchmark}")
    with args.benchmark.open("r", encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))[: max(1, args.limit)]
    args.output.mkdir(parents=True, exist_ok=True)
    scan_dir = args.output / "scans"
    results = []
    tp = fp = fn = 0
    similarities = []
    for row in source_rows:
        pdf_path = scan_dir / f"{row['resume_id']}.pdf"
        build_scan_pdf(row["text"], pdf_path)
        parsed = parse_resume(pdf_path)
        gold = set(json.loads(row["gold_skill_ids"]))
        predicted = {item["skill_id"] for item in parsed.get("skills") or []}
        tp += len(gold & predicted)
        fp += len(predicted - gold)
        fn += len(gold - predicted)
        similarity = difflib.SequenceMatcher(
            None, normalized_text(row["text"]), normalized_text(parsed.get("text") or "")
        ).ratio()
        similarities.append(similarity)
        results.append(
            {
                "resume_id": row["resume_id"],
                "pdf": str(pdf_path.relative_to(args.output)),
                "ocr_engine": (parsed.get("ocr") or {}).get("engine", ""),
                "ocr_language": (parsed.get("ocr") or {}).get("language", ""),
                "character_similarity": round(similarity * 100, 2),
                "gold_skill_count": len(gold),
                "predicted_skill_count": len(predicted),
                "true_positive": len(gold & predicted),
                "false_positive": len(predicted - gold),
                "false_negative": len(gold - predicted),
                "warning": " | ".join(parsed.get("warnings") or []),
            }
        )
    skill_metric = metric(tp, fp, fn)
    engines = sorted({item["ocr_engine"] for item in results if item["ocr_engine"]})
    summary = {
        "suite": SUITE,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "samples": len(results),
        "engines": engines,
        "averageCharacterSimilarity": round(sum(similarities) / len(similarities) * 100, 2),
        "resumeSkillExtraction": skill_metric,
        "thresholds": {"characterSimilarity": 85, "resumeSkillF1": 90},
        "passed": bool(
            similarities
            and sum(similarities) / len(similarities) * 100 >= 85
            and skill_metric["f1"] >= 90
            and all(engine != "digital-text" for engine in engines)
        ),
        "method": "raster-only PDFs rendered at A4 resolution and parsed through the production OCR fallback",
    }
    with (args.output / "ocr_results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    (args.output / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
