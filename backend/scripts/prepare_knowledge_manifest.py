from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SKIP_FILENAMES = {".DS_Store", "Thumbs.db"}


@dataclass
class KnowledgeManifestRow:
    original_path: str
    suggested_filename: str
    suggested_path: str
    file_type: str
    project_type: str = "通用"
    document_type: str = ""
    document_category: str = ""
    specialty: str = "通用"
    volume: str = ""
    region: str = ""
    project_year: str = ""
    owner_type: str = ""
    owner_name: str = ""
    certificate_type: str = ""
    valid_from: str = ""
    valid_to: str = ""
    sensitivity: str = "内部"
    usage_scope: str = "可用于投标"
    verified_status: str = "待核验"
    image_insertable: bool = False
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    review_required: bool = True
    notes: str = ""


def build_manifest(
    source_dir: Path, prepared_root: Path | None = None
) -> list[KnowledgeManifestRow]:
    rows: list[KnowledgeManifestRow] = []
    for path in _iter_files(source_dir):
        row = classify_file(path, source_dir)
        suggested_dir = prepared_root or source_dir
        row.suggested_path = str(suggested_dir / row.suggested_filename)
        rows.append(row)
    return rows


def classify_file(path: Path, source_dir: Path) -> KnowledgeManifestRow:
    stem = path.stem
    suffix = path.suffix.lower()
    raw_text = " ".join(path.relative_to(source_dir).parts)
    text = _normalize_text(raw_text)
    row = KnowledgeManifestRow(
        original_path=str(path),
        suggested_filename=path.name,
        suggested_path="",
        file_type=suffix.lstrip(".") or "unknown",
        tags=[],
    )

    if _contains(text, "营业执照"):
        _set_company_certificate(row, "营业执照")
        row.valid_to = "长期有效"
        row.confidence = 0.92
    elif _contains(text, "安许", "安全生产许可证"):
        _set_company_certificate(row, "安全生产许可证")
        row.project_year = _extract_year(text)
        row.confidence = 0.86
    elif _contains(text, "劳务资质"):
        _set_company_certificate(row, "施工劳务资质证书")
        row.valid_to = _extract_date(raw_text)
        row.confidence = 0.9
    elif _contains(text, "资质", "路基路面", "交通安全设施"):
        _set_company_certificate(row, "资质证书")
        row.project_type = "公路工程"
        row.specialty = _specialty_from_text(text)
        row.valid_to = _extract_date(raw_text)
        row.confidence = 0.84 if _contains(text, "路基路面", "交通安全设施") else 0.88
    elif _contains(
        text, "建安", "交安", "建造师", "一建", "二建", "注册证", "职称", "身份证", "社保", "毕业证"
    ):
        _set_person_certificate(row, _certificate_type_from_person_text(text))
        row.owner_name = _person_name_from_text(stem) or row.owner_name
        row.valid_to = _extract_date(raw_text)
        row.project_type = "公路工程" if _contains(text, "交安", "公路") else "通用"
        row.specialty = "道路" if _contains(text, "一建", "建造师", "注册证") else "通用"
        row.confidence = 0.88 if row.owner_name else 0.74
    elif _contains(text, "业绩"):
        row.document_category = "业绩"
        row.document_type = "业绩统计表" if suffix in {".xls", ".xlsx"} else "业绩证明"
        row.volume = "资格文件"
        row.owner_type = "公司"
        row.owner_name = "安徽正奇建设有限公司"
        row.certificate_type = row.document_type
        row.sensitivity = "内部"
        row.usage_scope = "仅参考"
        row.verified_status = "待核验"
        row.image_insertable = False
        row.confidence = 0.86
        row.tags.extend(["业绩", "统计表"])
    else:
        row.document_category = "其他资料"
        row.document_type = "待分类资料"
        row.volume = "完整投标文件"
        row.usage_scope = "仅参考"
        row.confidence = 0.35
        row.notes = "未命中明确规则，需人工确认。"

    if suffix in IMAGE_EXTENSIONS and row.document_category in {
        "公司证件",
        "人员证件",
        "业绩",
        "图片资料",
    }:
        row.image_insertable = True
    if row.certificate_type:
        row.tags.append(row.certificate_type)
    if row.owner_name:
        row.tags.append(row.owner_name)
    if row.specialty and row.specialty != "通用":
        row.tags.append(row.specialty)
    row.tags = _unique_tags(row.tags)
    row.review_required = row.confidence < 0.85 or row.verified_status != "已核验"
    row.suggested_filename = _suggested_filename(row, suffix)
    return row


def write_csv(rows: list[KnowledgeManifestRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        list(asdict(rows[0]).keys())
        if rows
        else list(KnowledgeManifestRow("", "", "", "").__dict__.keys())
    )
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            data = asdict(row)
            data["tags"] = "、".join(row.tags)
            writer.writerow(data)


def write_json(rows: list[KnowledgeManifestRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(row) for row in rows]
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_csv_manifest(manifest_path: Path) -> list[KnowledgeManifestRow]:
    with manifest_path.open(encoding="utf-8-sig", newline="") as file:
        rows: list[KnowledgeManifestRow] = []
        for raw in csv.DictReader(file):
            data = dict(raw)
            data["image_insertable"] = _parse_bool(data.get("image_insertable"))
            data["review_required"] = _parse_bool(data.get("review_required"))
            data["confidence"] = _parse_float(data.get("confidence"), default=0.0)
            data["tags"] = _split_tags(str(data.get("tags") or ""))
            rows.append(KnowledgeManifestRow(**data))
    return rows


def import_rows_to_knowledge_base(
    rows: list[KnowledgeManifestRow],
    *,
    include_review_required: bool = False,
) -> list[dict[str, object]]:
    from services import knowledge_service

    results: list[dict[str, object]] = []
    for row in rows:
        if row.review_required and not include_review_required:
            results.append(
                {
                    "original_path": row.original_path,
                    "suggested_filename": row.suggested_filename,
                    "status": "skipped_review_required",
                    "message": "review_required=true; pass --include-review-required to import",
                }
            )
            continue

        source = (
            Path(row.suggested_path) if row.suggested_path else Path(row.original_path)
        )
        if not source.exists():
            source = Path(row.original_path)
        if not source.exists():
            results.append(
                {
                    "original_path": row.original_path,
                    "suggested_filename": row.suggested_filename,
                    "status": "failed",
                    "message": "source file not found",
                }
            )
            continue

        try:
            indexed = knowledge_service.index_uploaded_knowledge(
                file_bytes=source.read_bytes(),
                filename=row.suggested_filename or source.name,
                content_type=mimetypes.guess_type(source.name)[0],
                project_type=_clean_optional(row.project_type),
                document_type=_clean_optional(row.document_type),
                document_category=_clean_optional(row.document_category),
                specialty=_clean_optional(row.specialty),
                volume=_clean_optional(row.volume),
                region=_clean_optional(row.region),
                project_year=_parse_int(row.project_year),
                owner_type=_clean_optional(row.owner_type),
                owner_name=_clean_optional(row.owner_name),
                certificate_type=_clean_optional(row.certificate_type),
                valid_from=_clean_optional(row.valid_from),
                valid_to=_clean_optional(row.valid_to),
                sensitivity=_clean_optional(row.sensitivity),
                usage_scope=_clean_optional(row.usage_scope),
                verified_status=_clean_optional(row.verified_status),
                image_insertable=row.image_insertable,
                tags=row.tags,
                ingestion_mode=_ingestion_mode_for_row(row),
            )
            results.append(
                {
                    "original_path": row.original_path,
                    "suggested_filename": row.suggested_filename,
                    "status": "imported",
                    "document_id": indexed.get("document_id"),
                    "chunk_ids": indexed.get("chunk_ids"),
                    "indexing_status": indexed.get("indexing_status"),
                    "message": "",
                }
            )
        except Exception as error:
            results.append(
                {
                    "original_path": row.original_path,
                    "suggested_filename": row.suggested_filename,
                    "status": "failed",
                    "message": str(error),
                }
            )
    return results


def write_import_report(results: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "original_path",
        "suggested_filename",
        "status",
        "document_id",
        "chunk_ids",
        "indexing_status",
        "message",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            row = {key: result.get(key, "") for key in fieldnames}
            if isinstance(row["chunk_ids"], list):
                row["chunk_ids"] = ",".join(str(value) for value in row["chunk_ids"])
            writer.writerow(row)


def copy_prepared_files(rows: list[KnowledgeManifestRow], copy_to: Path) -> None:
    copy_to.mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    for row in rows:
        source = Path(row.original_path)
        target_name = _dedupe_filename(row.suggested_filename, used_names)
        target = copy_to / target_name
        shutil.copy2(source, target)
        row.suggested_filename = target_name
        row.suggested_path = str(target)


def _set_company_certificate(row: KnowledgeManifestRow, certificate_type: str) -> None:
    row.project_type = "通用"
    row.document_type = certificate_type
    row.document_category = "公司证件"
    row.specialty = "通用"
    row.volume = "资格文件"
    row.owner_type = "公司"
    row.owner_name = "安徽正奇建设有限公司"
    row.certificate_type = certificate_type
    row.sensitivity = "内部"
    row.usage_scope = "可用于投标"
    row.verified_status = "待核验"
    row.image_insertable = True


def _set_person_certificate(row: KnowledgeManifestRow, certificate_type: str) -> None:
    row.document_type = certificate_type
    row.document_category = "人员证件"
    row.volume = "资格文件"
    row.owner_type = "人员"
    row.certificate_type = certificate_type
    row.sensitivity = "严格受限" if certificate_type == "身份证" else "敏感"
    row.usage_scope = "可用于投标"
    row.verified_status = "待核验"
    row.image_insertable = True


def _suggested_filename(row: KnowledgeManifestRow, suffix: str) -> str:
    parts = [
        row.document_category or "待分类资料",
        f"{row.owner_type}-{row.owner_name}"
        if row.owner_type and row.owner_name
        else row.owner_type,
        row.certificate_type or row.document_type,
        row.project_type or "通用",
        _valid_label(row),
        row.verified_status,
    ]
    cleaned = [_safe_segment(part) for part in parts if part]
    return "_".join(cleaned) + suffix.lower()


def _valid_label(row: KnowledgeManifestRow) -> str:
    if row.valid_to == "长期有效":
        return "长期有效"
    if row.valid_to:
        return f"有效期至{row.valid_to.replace('-', '')}"
    if row.project_year:
        return str(row.project_year)
    return "有效期待核验"


def _iter_files(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_FILENAMES:
            continue
        yield path


def _contains(text: str, *keywords: str) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def _normalize_text(text: str) -> str:
    return text.replace(" ", "").replace("_", "").replace("-", "").replace("副本", "")


def _extract_date(text: str) -> str:
    match = re.search(
        r"(20\d{2})[.\-_/年]?(0[1-9]|1[0-2]|[1-9])[.\-_/月]?(3[01]|[12]\d|0[1-9]|[1-9])?",
        text,
    )
    if not match:
        return ""
    year, month, day = match.group(1), match.group(2), match.group(3)
    if not day:
        return ""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_year(text: str) -> str:
    match = re.search(r"(20\d{2})", text)
    return match.group(1) if match else ""


def _certificate_type_from_person_text(text: str) -> str:
    if _contains(text, "身份证"):
        return "身份证"
    if _contains(text, "社保"):
        return "社保"
    if _contains(text, "毕业证"):
        return "毕业证"
    if _contains(text, "交安"):
        return "交安证"
    if _contains(text, "建安"):
        return "建安证"
    if _contains(text, "职称"):
        return "职称证书"
    if _contains(text, "一建", "一级建造师", "建造师", "注册证"):
        return "一级建造师证"
    if _contains(text, "二建", "二级建造师"):
        return "二级建造师证"
    return "人员证件"


def _person_name_from_text(stem: str) -> str:
    cleaned = re.sub(r"^[0-9]+[.、_-]*", "", stem)
    for marker in ("一建", "二建", "建造师", "注册证", "建安", "交安", "身份证", "社保", "毕业证", "职称"):
        if marker in cleaned:
            return cleaned.split(marker, 1)[0].strip(" _-至")
    match = re.match(r"([\u4e00-\u9fff]{2,4})", cleaned)
    return match.group(1) if match else ""


def _specialty_from_text(text: str) -> str:
    specialties: list[str] = []
    if _contains(text, "路基", "路面", "道路"):
        specialties.append("道路")
    if _contains(text, "交通安全设施", "交安"):
        specialties.append("交安")
    if _contains(text, "养护"):
        specialties.append("养护")
    return "、".join(specialties) if specialties else "通用"


def _unique_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        clean = _safe_segment(tag)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "", str(value)).strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned[:80]


def _dedupe_filename(filename: str, used_names: set[str]) -> str:
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while candidate in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "是"}


def _parse_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int(value) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _clean_optional(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _split_tags(value: str) -> list[str]:
    return _unique_tags(
        [tag for tag in re.split(r"[,，、;；\n]+", value or "") if tag.strip()]
    )


def _ingestion_mode_for_row(row: KnowledgeManifestRow) -> str | None:
    if row.document_category in {"公司证件", "人员证件", "业绩"} and row.image_insertable:
        return "structured_evidence"
    if row.file_type.lower() in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "structured_evidence"
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and optionally import knowledge-base files."
    )
    parser.add_argument(
        "source_dir",
        type=Path,
        nargs="?",
        help="Folder containing raw knowledge files.",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="CSV manifest output path."
    )
    parser.add_argument(
        "--json-out", type=Path, help="Optional JSON manifest output path."
    )
    parser.add_argument(
        "--copy-to", type=Path, help="Optional folder for renamed copied files."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Use an existing edited CSV manifest instead of scanning source_dir.",
    )
    parser.add_argument(
        "--import-to-kb",
        action="store_true",
        help="Import files into the configured knowledge base after manifest preparation.",
    )
    parser.add_argument(
        "--include-review-required",
        action="store_true",
        help="Import rows even when review_required=true.",
    )
    parser.add_argument(
        "--import-report",
        type=Path,
        help="CSV report for import results.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    copy_to = args.copy_to.expanduser().resolve() if args.copy_to else None
    if args.manifest:
        rows = read_csv_manifest(args.manifest.expanduser().resolve())
    else:
        if not args.source_dir:
            raise SystemExit("source_dir is required unless --manifest is provided")
        source_dir = args.source_dir.expanduser().resolve()
        if not source_dir.is_dir():
            raise SystemExit(f"Source directory does not exist: {source_dir}")
        rows = build_manifest(source_dir, prepared_root=copy_to)
    if copy_to:
        copy_prepared_files(rows, copy_to)
    write_csv(rows, args.out.expanduser().resolve())
    if args.json_out:
        write_json(rows, args.json_out.expanduser().resolve())
    if args.import_to_kb:
        results = import_rows_to_knowledge_base(
            rows,
            include_review_required=args.include_review_required,
        )
        report_path = (
            args.import_report.expanduser().resolve()
            if args.import_report
            else args.out.expanduser()
            .resolve()
            .with_name("knowledge_import_report.csv")
        )
        write_import_report(results, report_path)
        imported = sum(1 for result in results if result.get("status") == "imported")
        skipped = sum(
            1
            for result in results
            if str(result.get("status", "")).startswith("skipped")
        )
        failed = sum(1 for result in results if result.get("status") == "failed")
        print(f"Import: {imported} imported, {skipped} skipped, {failed} failed")
        print(f"Import report: {report_path}")
    print(f"Prepared {len(rows)} files")
    print(f"CSV: {args.out.expanduser().resolve()}")
    if args.json_out:
        print(f"JSON: {args.json_out.expanduser().resolve()}")
    if copy_to:
        print(f"Copied files: {copy_to}")


if __name__ == "__main__":
    main()
