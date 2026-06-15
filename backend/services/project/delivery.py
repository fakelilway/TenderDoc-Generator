"""Delivery preview, download URLs, artifact export and review report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from core.config import settings
from utils.docx_exporter import (
    build_export_filename,
    markdown_to_docx,
    markdown_to_pdf,
    split_delivery_markdown,
)

from . import _runtime
from ._helpers import _fetch_project, _hydrated_workflow_state


_DOWNLOAD_ARTIFACTS = {
    "docx": ("合并投标 DOCX", "docx"),
    "pdf": ("合并投标 PDF", "pdf"),
    "markdown": ("Markdown 源文件", "md"),
    "review": ("审查报告", "md"),
}
_DELIVERY_VOLUME_LABELS = {
    "commercial": "商务文件",
    "technical": "技术文件",
    "pricing": "报价文件",
}
_DELIVERY_FORMATS = {"docx", "pdf"}


# Cache of the latest delivery preview per project, keyed by a fingerprint of
# the fields the preview is derived from. The fingerprint changes on any
# project write that affects the preview, so stale entries are never served;
# write paths in this module also invalidate eagerly.
_delivery_preview_cache: dict[int, tuple[str, dict[str, Any]]] = {}


def _delivery_markdown_source(project: dict[str, Any]) -> str:
    markdown = project.get("edited_markdown") or (
        project.get("workflow_state_json") or {}
    ).get("draft_markdown", "")
    if markdown:
        return markdown
    object_name = project.get("generated_markdown_path")
    if not object_name:
        raise ValueError("尚未生成可拆分的 Markdown 源文件")
    return _runtime.minio().download_bytes(settings.minio_bucket, object_name).decode(
        "utf-8"
    )


def _delivery_preview_fingerprint(project: dict[str, Any]) -> str:
    workflow_state = project.get("workflow_state_json") or {}
    payload = json.dumps(
        {
            "status": project.get("status"),
            "edited_markdown": project.get("edited_markdown"),
            "draft_markdown": workflow_state.get("draft_markdown"),
            "draft_volumes": workflow_state.get("draft_volumes"),
            "generated_markdown_path": project.get("generated_markdown_path"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def invalidate_delivery_preview_cache(project_id: int) -> None:
    _delivery_preview_cache.pop(project_id, None)


def get_project_delivery_preview(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    fingerprint = _delivery_preview_fingerprint(project)
    cached = _delivery_preview_cache.get(project_id)
    if cached and cached[0] == fingerprint:
        return cached[1]
    volumes = _delivery_volumes(project)
    response_volumes = {}
    for key, label in _DELIVERY_VOLUME_LABELS.items():
        markdown = volumes[key]
        response_volumes[key] = {
            "key": key,
            "label": label,
            "markdown": markdown,
            "line_count": len(markdown.splitlines()),
            "char_count": len(markdown),
        }
    preview = {
        "project_id": project["id"],
        "status": project["status"],
        "volumes": response_volumes,
    }
    _delivery_preview_cache[project_id] = (fingerprint, preview)
    return preview


def _delivery_volumes(project: dict[str, Any]) -> dict[str, str]:
    if project.get("edited_markdown"):
        return split_delivery_markdown(project["edited_markdown"])
    workflow_state = project.get("workflow_state_json") or {}
    draft_volumes = workflow_state.get("draft_volumes") or {}
    if draft_volumes:
        return {
            key: draft_volumes.get(key, "")
            or f"# {_DELIVERY_VOLUME_LABELS[key]}\n\n（本卷暂无内容，请人工补充。）"
            for key in _DELIVERY_VOLUME_LABELS
        }
    return split_delivery_markdown(_delivery_markdown_source(project))


def get_project_download_url(
    project_id: int,
    artifact: str = "docx",
    expiry: int = 3600,
) -> dict[str, Any]:
    project = _fetch_project(project_id)
    artifact = (artifact or "docx").lower()
    label, suffix = _DOWNLOAD_ARTIFACTS.get(artifact, ("", ""))
    project_name = project.get("name") or "投标文件"
    version = len(project.get("final_versions_json") or []) or 1

    if artifact == "docx":
        object_name = project.get("generated_docx_path")
        if not object_name:
            raise ValueError("尚未生成可下载的标书文件")
        filename = build_export_filename(project_name, version, suffix=suffix)
    elif artifact == "pdf":
        object_name = _export_delivery_artifact(project, volume=None, suffix="pdf")
        filename = build_export_filename(project_name, version, suffix=suffix)
    elif artifact == "markdown":
        object_name = project.get("generated_markdown_path")
        if not object_name:
            raise ValueError("尚未生成可下载的 Markdown 文件")
        filename = build_export_filename(project_name, version, suffix=suffix)
    elif artifact == "review":
        object_name = _export_review_report(project)
        filename = build_export_filename(f"{project_name}_审查报告", version, suffix=suffix)
    else:
        volume, file_format = _parse_delivery_artifact(artifact)
        label = f"{_DELIVERY_VOLUME_LABELS[volume]} {file_format.upper()}"
        suffix = file_format
        object_name = _export_delivery_artifact(
            project,
            volume=volume,
            suffix=file_format,
        )
        filename = build_export_filename(
            project_name,
            version,
            kind=_DELIVERY_VOLUME_LABELS[volume],
            suffix=suffix,
        )

    return {
        "project_id": project["id"],
        "status": project["status"],
        "download_url": _runtime.minio().get_presigned_url(
            settings.minio_bucket,
            object_name,
            expiry=expiry,
            response_filename=filename,
        ),
        "expires_in": expiry,
        "artifact": artifact,
        "artifact_label": label,
        "filename": filename,
    }


def _parse_delivery_artifact(artifact: str) -> tuple[str, str]:
    try:
        volume, file_format = artifact.rsplit("_", 1)
    except ValueError as error:
        raise ValueError(f"不支持的下载类型：{artifact}") from error
    if volume not in _DELIVERY_VOLUME_LABELS or file_format not in _DELIVERY_FORMATS:
        raise ValueError(f"不支持的下载类型：{artifact}")
    return volume, file_format


def _export_delivery_artifact(
    project: dict[str, Any],
    *,
    volume: str | None,
    suffix: str,
) -> str:
    markdown = _delivery_markdown_source(project)
    project_id = project["id"]
    title = project.get("name") or "投标文件"
    if volume and suffix == "docx":
        # Check if pre-built volume DOCX exists (V2 original format path)
        from core.config import get_settings as _gs
        prebuilt = f"projects/{project_id}/generated/{volume}.docx"
        object_exists = getattr(_runtime.minio(), "object_exists", None)
        if object_exists and object_exists(_gs().minio_bucket, prebuilt):
            return prebuilt
    if volume:
        markdown = _delivery_volumes(project)[volume]
        label = _DELIVERY_VOLUME_LABELS[volume]
        object_name = f"projects/{project_id}/generated/delivery/{volume}.{suffix}"
        title = f"{title}（{label}）"
    else:
        object_name = f"projects/{project_id}/generated/delivery/combined.{suffix}"

    with TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / f"delivery.{suffix}"
        if suffix == "docx":
            markdown_to_docx(
                markdown,
                output_path,
                title=title,
                subtitle="投标文件",
                cover=True,
                toc=True,
                header_text=title,
                page_numbers=True,
                style_profile="zhengqi",
            )
        elif suffix == "pdf":
            markdown_to_pdf(markdown, output_path, title=title)
        else:
            raise ValueError(f"不支持的下载格式：{suffix}")
        _runtime.minio().upload_file(settings.minio_bucket, output_path, object_name)
    return object_name


def _export_review_report(project: dict[str, Any]) -> str:
    """Render the review report to markdown, store it in MinIO, return its key."""
    report = project.get("review_report_json")
    if not report:
        raise ValueError("尚无审查报告可下载")
    markdown = _build_review_report_markdown(project)
    object_name = f"projects/{project['id']}/generated/review_report.md"
    _runtime.minio().upload_file(
        settings.minio_bucket,
        markdown.encode("utf-8"),
        object_name,
    )
    return object_name


def _build_review_report_markdown(project: dict[str, Any]) -> str:
    report = project.get("review_report_json") or {}
    findings = report.get("findings", [])
    lines = [
        f"# 审查报告 - {project.get('name', '')}",
        "",
        f"- 通过项：{report.get('pass_count', 0)}",
        f"- 警告项：{report.get('warning_count', 0)}",
        f"- 失败项：{report.get('fail_count', 0)}",
        "",
        "## 审查明细",
        "",
    ]
    if not findings:
        lines.append("（暂无审查发现）")
    for finding in findings:
        lines.append(f"### [{finding.get('status', '')}] {finding.get('rule', '')}")
        lines.append(f"- 严重度：{finding.get('severity', '')}")
        if finding.get("suggestion"):
            lines.append(f"- 建议：{finding.get('suggestion')}")
        if finding.get("evidence"):
            lines.append(f"- 证据：{finding.get('evidence')}")
        lines.append("")
    return "\n".join(lines)


def get_project_review_report(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    workflow_state = _hydrated_workflow_state(project)
    project_status = project["status"]
    running_statuses = {"uploading", "parsing", "processing", "generating", "reviewing"}
    return {
        "project_id": project["id"],
        "status": (
            project_status
            if project_status in running_statuses
            else (workflow_state or {}).get("status") or project_status
        ),
        "review_report": project.get("review_report_json"),
        "workflow_state": workflow_state,
    }
