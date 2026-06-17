"""出标交付件的程序化质量打分接入层(非阻断)。

把 docx_health_check.score_delivery 接进生成管线:每次出标后按卷打分,
落 eval_results/ 并写日志。本模块对所有外部失败(MinIO 下载、profile 读取、
卷缺失、requirements 解析)都保持稳健——能算多少算多少,绝不抛异常影响出标。

两个入口:
  - score_delivery_files: 给定本地 .docx 路径(出标钩子用,文件还在临时目录里)。
  - score_project_delivery: 从 MinIO 拉项目已生成的卷(on-demand / 迭代循环用)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

logger = logging.getLogger(__name__)

# eval_results 落在 backend/eval_results(与 cwd 无关;该路径已被 .gitignore 忽略,
# 与 benchmark 等既有 eval 产物同处,不污染仓库根):
#   parents[0]=services  parents[1]=backend
_EVAL_RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval_results"


def _load_profile() -> dict[str, Any]:
    """读企业档案;务必取内层 ["profile"](外层是 {profile,updated_at} 包装)。

    失败返回空 dict —— score_delivery 对空 profile 走"表格行下划线空位"启发式。
    """
    try:
        from services.company_profile_service import get_company_profile

        profile = get_company_profile().get("profile", {})
        return profile if isinstance(profile, dict) else {}
    except Exception:
        logger.warning("delivery_quality: 读取企业档案失败,profile 退回空", exc_info=True)
        return {}


def _load_requirements(project_id: int | None) -> Any | None:
    """best-effort: 从项目 confirmed_parsed_json 解析 TenderRequirements。

    任何环节失败(无 project_id / 读 DB 失败 / 校验失败)都返回 None,
    score_delivery 对 None 用启发式基准。
    """
    if project_id is None:
        return None
    try:
        from schemas.tender import TenderRequirements
        from services.project_service import _connect

        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT confirmed_parsed_json, parsed_json FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            parsed = row.get("confirmed_parsed_json") or row.get("parsed_json")
        else:
            parsed = row[0] or row[1]
        if not parsed:
            return None
        return TenderRequirements.model_validate(parsed)
    except Exception:
        logger.warning(
            "delivery_quality: 解析 requirements 失败(project_id=%s),退回 None",
            project_id,
            exc_info=True,
        )
        return None


def _write_eval(project_id: int | None, result: dict[str, Any]) -> None:
    """把打分结果写到仓库根 eval_results/project_{id}.json。失败不抛。"""
    try:
        _EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        name = f"project_{project_id}.json" if project_id is not None else "project_unknown.json"
        target = _EVAL_RESULTS_DIR / name
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.warning("delivery_quality: 写 eval_results 失败", exc_info=True)


def score_delivery_files(
    *,
    commercial_path: str | Path | None = None,
    technical_path: str | Path | None = None,
    project_id: int | None = None,
    write_eval: bool = True,
) -> dict[str, Any]:
    """按卷给本地 .docx 打分,返回 score_delivery 的结果 dict。

    至少需给 commercial_path 或 technical_path 其一;某卷缺失就只打有的那卷。
    profile 取企业档案内层;requirements best-effort 从项目解析。
    write_eval=True 时把结果落 eval_results/project_{id}.json。
    """
    from services.docx_health_check import score_delivery

    profile = _load_profile()
    requirements = _load_requirements(project_id)

    result = score_delivery(
        technical_path=technical_path,
        commercial_path=commercial_path,
        profile=profile,
        requirements=requirements,
    )

    if write_eval:
        _write_eval(project_id, result)

    return result

