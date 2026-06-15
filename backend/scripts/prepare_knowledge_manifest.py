from __future__ import annotations

import argparse
import collections
import csv
import hashlib
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
    is_duplicate: bool = False
    duplicate_of: str = ""


def build_manifest(
    source_dir: Path, prepared_root: Path | None = None
) -> list[KnowledgeManifestRow]:
    rows: list[KnowledgeManifestRow] = []
    for path in _iter_files(source_dir):
        row = classify_file(path, source_dir)
        suggested_dir = prepared_root or source_dir
        row.suggested_path = str(suggested_dir / row.suggested_filename)
        rows.append(row)
    _mark_duplicates(rows)
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

    if _classify_by_structure(row, path, source_dir, stem, suffix, text, raw_text):
        pass
    elif _contains(text, "营业执照"):
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
            data["is_duplicate"] = _parse_bool(data.get("is_duplicate"))
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
        if row.is_duplicate:
            results.append(
                {
                    "original_path": row.original_path,
                    "suggested_filename": row.suggested_filename,
                    "status": "skipped_duplicate",
                    "message": f"duplicate of {row.duplicate_of}",
                }
            )
            continue
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


# ── Folder-structure aware classification ──────────────────────────────
# An organized 证件库 encodes the real signal in its hierarchy, not the
# filenames (which are often "001.jpg" or "基本信息.txt"):
#   正奇证件库/4.正奇安许证/旧/正奇安许.pdf          → 公司证件·安全生产许可证
#   正奇证件库/1.人员证书/1.建造师/一级建造师注册证/1、江舟/江舟身份证.jpg
#                                                   → 人员证件·身份证·owner=江舟
# Filename rules stay as the fallback when the hierarchy is flat/uninformative.

_NON_PERSON_FOLDERS = {
    "解聘", "转出", "离职", "退休", "注销", "作废", "过期",
    "旧", "新", "其他", "人员信息", "基本信息", "备份",
}

# Tokens that mean a captured string is a category/label, not a person's name.
_NAME_NOISE = (
    "证书", "名单", "名册", "花名", "列表", "汇总", "统计", "合同", "公告",
    "截图", "下载", "工程", "公路", "养护", "专管", "劳资", "造价", "检测",
    "试验", "人员", "社保", "身份", "复印", "扫描", "信息", "备案", "附件", "文件",
)


def _is_person_name(name: str) -> bool:
    """Reject category/label fragments that filename heuristics mistake for names."""
    if not name or not (2 <= len(name) <= 5):
        return False
    if name in _NON_PERSON_FOLDERS:
        return False
    return not any(token in name for token in _NAME_NOISE)

_COMPANY_CERT_KEYWORDS = (
    ("营业执照", "营业执照"),
    ("安全生产许可证", "安全生产许可证"),
    ("安许", "安全生产许可证"),
    ("开户许可证", "开户许可证"),
    ("开户", "开户许可证"),
    ("劳务资质", "施工劳务资质证书"),
    ("资质", "资质证书"),
    ("三大体系", "体系证书"),
    ("体系", "体系证书"),
    ("信用", "信用证书"),
    ("aaa", "信用证书"),
    ("专利", "专利证书"),
    ("工法", "工法证书"),
    ("表彰", "荣誉证书"),
    ("荣誉", "荣誉证书"),
)


def _strip_folder_index(name: str) -> str:
    """Drop a leading '1.' / '2、' / '03-' ordering prefix from a folder name."""
    return re.sub(r"^\s*\d+\s*[、.．\-_]\s*", "", name).strip()


def _company_cert_from_text(text: str) -> str:
    lowered = text.lower()
    for keyword, cert_type in _COMPANY_CERT_KEYWORDS:
        if keyword and keyword.lower() in lowered:
            return cert_type
    return ""


def _person_name_from_folders(raw_parts: list[str], clean_parts: list[str]) -> str:
    """Pull a person's name from a '序号、姓名' (or 人员信息/姓名) folder.

    Takes the deepest match so '1.建造师/.../3、罗国华/...' yields 罗国华.
    """
    name = ""
    for index, part in enumerate(raw_parts):
        # Person folders use the Chinese enumeration comma (序号、姓名 → "1、江舟"),
        # while category folders use a dot ("1.建造师"). Matching only "、" keeps
        # category folders from being misread as people.
        match = re.match(r"^\s*\d+\s*[、，]\s*([一-鿿·]{2,5})\s*$", part)
        candidate = match.group(1) if match else ""
        if not candidate and index > 0 and clean_parts[index - 1] == "人员信息":
            if re.match(r"^[一-鿿·]{2,4}$", clean_parts[index]):
                candidate = clean_parts[index]
        if not candidate:
            trailing = re.search(r"[\-—_]\s*([一-鿿]{2,4})$", clean_parts[index])
            if trailing:
                candidate = trailing.group(1)
        if _is_person_name(candidate):
            name = candidate
    return name


def _classify_by_structure(
    row: KnowledgeManifestRow,
    path: Path,
    source_dir: Path,
    stem: str,
    suffix: str,
    text: str,
    raw_text: str,
) -> bool:
    """Classify from the folder hierarchy. Returns False (→ filename rules) when
    the directory layout is flat or gives no confident answer."""
    raw_parts = list(path.relative_to(source_dir).parts[:-1])
    if not raw_parts:
        return False
    clean_parts = [_strip_folder_index(part) for part in raw_parts]
    top = clean_parts[0]
    in_person_tree = any("人员" in part for part in clean_parts)

    # 1) 正奇's own company-cert folders (营业执照/安许/资质/体系/信用/专利/工法/开户…)
    folder_company_cert = _company_cert_from_text(top)
    if folder_company_cert and not in_person_tree:
        _set_company_certificate(row, folder_company_cert)
        if folder_company_cert == "资质证书":
            row.project_type = "公路工程"
            row.specialty = _specialty_from_text(text)
        row.valid_to = _extract_date(raw_text)
        row.confidence = 0.9
        return True

    if in_person_tree:
        # 2) A company cert misfiled under the person tree (e.g. an exec's 营业执照).
        filename_company_cert = _company_cert_from_text(_normalize_text(stem))
        if filename_company_cert:
            _set_company_certificate(row, filename_company_cert)
            is_zhengqi = "正奇" in raw_text
            row.owner_name = "安徽正奇建设有限公司" if is_zhengqi else ""
            row.valid_to = _extract_date(raw_text)
            row.confidence = 0.82 if is_zhengqi else 0.45
            if not is_zhengqi:
                row.notes = "公司证件但单位名疑非正奇，需人工核对所属单位。"
            return True

        # 3) Person certificate: type from folder/filename, owner from folder.
        cert_type = _certificate_type_from_person_text(text)
        owner = _person_name_from_folders(raw_parts, clean_parts)
        if not owner:
            candidate = _person_name_from_text(stem)
            owner = candidate if _is_person_name(candidate) else ""
        _set_person_certificate(row, cert_type)
        row.owner_name = owner
        row.valid_to = _extract_date(raw_text)
        row.project_type = "公路工程" if _contains(text, "交安", "公路") else "通用"
        row.specialty = "道路" if _contains(text, "一建", "建造师", "注册证") else "通用"
        if owner and cert_type != "人员证件":
            row.confidence = 0.85
        elif owner:
            row.confidence = 0.72
        else:
            row.confidence = 0.5
            row.notes = "未能从文件夹识别人员姓名，需人工补全。"
        return True

    return False


def _file_hash(path: Path) -> str | None:
    try:
        digest = hashlib.sha1()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _mark_duplicates(rows: list[KnowledgeManifestRow]) -> None:
    """Flag byte-identical files (the same scan copied into many folders).

    Only hashes files that share a byte size, so unique-size files are never
    read. The first occurrence is kept; later copies get is_duplicate=True and
    are skipped on import.
    """
    by_size: dict[int, list[KnowledgeManifestRow]] = collections.defaultdict(list)
    for row in rows:
        try:
            size = Path(row.original_path).stat().st_size
        except OSError:
            continue
        by_size[size].append(row)

    seen: dict[str, str] = {}
    for group in by_size.values():
        if len(group) < 2:
            continue
        for row in group:
            digest = _file_hash(Path(row.original_path))
            if not digest:
                continue
            keeper = seen.get(digest)
            if keeper:
                row.is_duplicate = True
                row.duplicate_of = keeper
                note = f"与已收录 {keeper} 内容完全相同（重复扫描件）"
                row.notes = f"{row.notes}；{note}" if row.notes else note
            else:
                seen[digest] = row.suggested_filename or Path(row.original_path).name


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
    if _contains(text, "毕业证", "学历", "学位"):
        return "毕业证"
    if _contains(text, "注册安全工程师", "安全工程师"):
        return "注册安全工程师证"
    if _contains(text, "试验检测"):
        return "试验检测工程师证"
    if _contains(text, "造价"):
        return "造价工程师证"
    if _contains(
        text, "八大员", "施工员", "质量员", "材料员", "资料员", "安全员", "标准员", "机械员", "劳务员"
    ):
        return "八大员证书"
    if _contains(text, "特种"):
        return "特种作业证"
    if _contains(text, "养护工"):
        return "养护工证书"
    if _contains(text, "劳资专管员", "劳资员"):
        return "劳资专管员证"
    if _contains(text, "交安"):
        return "交安证"
    if _contains(text, "建安"):
        return "建安证"
    # 二级 must be checked before the generic 建造师/注册证 fallback, otherwise a
    # "二级建造师注册证" folder would be mislabelled as 一级建造师证.
    if _contains(text, "二级建造师", "二建"):
        return "二级建造师证"
    if _contains(text, "一级建造师", "一建", "建造师", "注册证"):
        return "一级建造师证"
    if _contains(text, "职称", "工程师"):
        return "职称证书"
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
