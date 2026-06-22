"""业绩档案:把"业绩台账(txt)"和"业绩证明扫描件"合成一张项目卡。

库里早有关联——业绩证明导入时已写 performance_project / evidence_type / evidence_seq
(见 scripts/import_performance_evidence.py),但 UI 没显示出来,看着像一堆散件。本服务:
  1. 读业绩台账(documents.category=业绩 的 txt),解析成项目档案卡;
  2. 读业绩证明,按 performance_project 分组成证据包(中标/合同/交工 各几张);
  3. 把两边按项目名对号(difflib 模糊匹配),输出 已配对 / 有证明缺台账 / 有台账缺证明,
     并给每条配对一个置信度,供人工抽查。

只读不改库。改归属/改名/合并等写操作后续在面板里做。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from rag.vector_store import _connect

# 证据链规范顺序(展示与"完整链"判断都按这个)
EVIDENCE_ORDER = ["中标通知书", "合同", "交工验收"]

# 置信度阈值:>=HIGH 视为可信自动配对;[REVIEW,HIGH) 需人工抽查;<REVIEW 视为对不上号
MATCH_HIGH = 0.86
MATCH_REVIEW = 0.72


def _norm(name: str) -> str:
    """项目名归一化,供模糊匹配:去序号前缀/空白/标点/全角括号内容差异。"""
    if not name:
        return ""
    s = re.sub(r"^\d+[-#＃]+", "", name)  # 去 "251#" 这种序号前缀
    s = re.sub(r"[\s　]+", "", s)  # 去空白(含全角空格)
    s = re.sub(r"[（(].*?[)）]", "", s)  # 去括号补充说明
    s = s.replace("年度", "年")
    s = re.sub(r"[、，,。.：:；;_（）()【】\[\]\"'“”—\-]", "", s)  # 去标点
    return s.strip()


def _parse_ledger(content: str) -> dict[str, str]:
    """从业绩 txt 正文抽字段。无"业绩项目："的(如业绩统计表)返回空名。"""

    def grab(label: str) -> str:
        m = re.search(rf"{label}[：:]\s*([^\n　]+)", content or "")
        return m.group(1).strip() if m else ""

    name = grab("业绩项目")
    year = ""
    ym = re.search(r"(20\d{2})\s*年", content or "")
    if ym:
        year = ym.group(1)
    return {
        "name": name,
        "type": grab("项目类型"),
        "amount": grab("中标金额"),
        "date": grab("中标日期"),
        "year": year,
        "manager": grab("项目经理"),
        "chief": grab("项目总工"),
        "contract_no": grab("合同编号"),
    }


def list_performance_ledger() -> list[dict[str, object]]:
    """业绩台账项目卡列表(只取真项目 txt,跳过没有"业绩项目："的汇总表)。"""
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT d.id, d.file_name, string_agg(c.content, ' ')
            FROM documents d
            LEFT JOIN knowledge_chunks c ON c.document_id = d.id
            WHERE d.project_id IS NULL
              AND d.metadata_json->>'document_category' = '业绩'
            GROUP BY d.id, d.file_name
            ORDER BY d.id
            """
        )
        rows = cursor.fetchall()

    ledger: list[dict[str, object]] = []
    for doc_id, file_name, content in rows:
        parsed = _parse_ledger(content or "")
        if not parsed["name"]:
            continue  # 业绩统计表等非单项目,跳过
        ledger.append({"document_id": int(doc_id), "file_name": file_name, **parsed})
    return ledger


def list_evidence_groups() -> dict[str, dict[str, object]]:
    """业绩证明按 performance_project 分组。返回 {项目名: {evidence: {类型:[doc...]}, total, types}}。"""
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, file_name, file_path,
                   metadata_json->>'performance_project',
                   metadata_json->>'evidence_type',
                   metadata_json->>'evidence_seq'
            FROM documents
            WHERE project_id IS NULL
              AND metadata_json->>'document_category' = '业绩证明'
            ORDER BY metadata_json->>'performance_project',
                     metadata_json->>'evidence_type',
                     (metadata_json->>'evidence_seq')::int NULLS LAST
            """
        )
        rows = cursor.fetchall()

    groups: dict[str, dict[str, object]] = {}
    for doc_id, file_name, file_path, proj, etype, seq in rows:
        proj = (proj or "(未标项目)").strip()
        etype = (etype or "其他").strip()
        group = groups.setdefault(proj, {"evidence": {}, "total": 0})
        bucket = group["evidence"].setdefault(etype, [])  # type: ignore[index]
        bucket.append(
            {
                "document_id": int(doc_id),
                "file_name": file_name,
                "file_path": file_path,
                "evidence_type": etype,
                "evidence_seq": int(seq) if (seq or "").isdigit() else 0,
            }
        )
        group["total"] = int(group["total"]) + 1  # type: ignore[arg-type]
    for proj, group in groups.items():
        group["types"] = {t: len(v) for t, v in group["evidence"].items()}  # type: ignore[union-attr]
    return groups


def _best_ledger_match(
    proj_norm: str, ledger_norm: list[tuple[str, int]]
) -> tuple[int, float]:
    """返回 (台账索引, 相似度)。先精确/包含,再 difflib 比值。"""
    best_idx, best_score = -1, 0.0
    for norm, idx in ledger_norm:
        if not norm:
            continue
        if norm == proj_norm:
            return idx, 1.0
        if proj_norm and (proj_norm in norm or norm in proj_norm):
            score = 0.9 * min(len(proj_norm), len(norm)) / max(len(proj_norm), len(norm))
            score = max(score, 0.82)  # 包含关系给个保底高分
        else:
            score = SequenceMatcher(None, proj_norm, norm).ratio()
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx, round(best_score, 3)


def build_archive() -> dict[str, object]:
    """对号并归类,产出可供报告/面板用的结构。"""
    ledger = list_performance_ledger()
    groups = list_evidence_groups()
    ledger_norm = [(_norm(str(r["name"])), i) for i, r in enumerate(ledger)]
    matched_ledger_ids: set[int] = set()

    matched: list[dict[str, object]] = []  # 配对成功(含需抽查)
    evidence_only: list[dict[str, object]] = []  # 有证明,对不上台账

    for proj, group in groups.items():
        idx, score = _best_ledger_match(_norm(proj), ledger_norm)
        if idx >= 0 and score >= MATCH_REVIEW:
            led = ledger[idx]
            matched_ledger_ids.add(int(led["document_id"]))
            matched.append(
                {
                    "evidence_project": proj,
                    "ledger": led,
                    "evidence": group["evidence"],
                    "types": group["types"],
                    "total": group["total"],
                    "score": score,
                    "needs_review": score < MATCH_HIGH,
                    "complete_chain": {"中标通知书", "交工验收"}
                    <= set(group["types"]),  # type: ignore[arg-type]
                }
            )
        else:
            evidence_only.append(
                {
                    "evidence_project": proj,
                    "evidence": group["evidence"],
                    "types": group["types"],
                    "total": group["total"],
                    "best_guess": ledger[idx]["name"] if idx >= 0 else "",
                    "best_score": score,
                }
            )

    ledger_only = [  # 有台账,没找到证明
        led for led in ledger if int(led["document_id"]) not in matched_ledger_ids
    ]

    return {
        "matched": sorted(matched, key=lambda m: m["score"]),  # 低分在前,便于抽查
        "evidence_only": sorted(evidence_only, key=lambda e: -int(e["total"])),
        "ledger_only": ledger_only,
        "stats": {
            "ledger_total": len(ledger),
            "evidence_projects": len(groups),
            "evidence_images": sum(int(g["total"]) for g in groups.values()),
            "matched": len(matched),
            "matched_need_review": sum(1 for m in matched if m["needs_review"]),
            "matched_complete_chain": sum(1 for m in matched if m["complete_chain"]),
            "evidence_only": len(evidence_only),
            "ledger_only": len(ledger_only),
        },
    }


def reassign_evidence(document_ids: list[int], target_project: str) -> int:
    """把若干业绩证明改挂到 target_project 名下(改归属/认领/合并都走这一个原语)。

    只动 performance_project 这个关联键,不碰文件本身。返回实际改动条数。
    """
    target = (target_project or "").strip()
    if not target:
        raise ValueError("target_project 不能为空")
    ids = [int(i) for i in document_ids if str(i).strip()]
    if not ids:
        raise ValueError("document_ids 不能为空")

    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE documents
            SET metadata_json = jsonb_set(
                COALESCE(metadata_json, '{}'::jsonb),
                '{performance_project}', to_jsonb(%s::text)
            )
            WHERE id = ANY(%s)
              AND project_id IS NULL
              AND metadata_json->>'document_category' = '业绩证明'
            """,
            (target, ids),
        )
        changed = cursor.rowcount
        # 同步到检索分片,保持一致
        cursor.execute(
            """
            UPDATE knowledge_chunks
            SET metadata = COALESCE(metadata, '{}'::jsonb)
                || jsonb_build_object('performance_project', %s::text)
            WHERE document_id = ANY(%s)
            """,
            (target, ids),
        )
        conn.commit()
    return int(changed)


def rename_evidence(document_id: int, title: str) -> None:
    """给单张业绩证明改个看得懂的名字(只改 file_name,关联/类型不变)。"""
    new_title = (title or "").strip()
    if not new_title:
        raise ValueError("名称不能为空")
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE documents SET file_name = %s "
            "WHERE id = %s AND project_id IS NULL "
            "AND metadata_json->>'document_category' = '业绩证明'",
            (new_title, int(document_id)),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"业绩证明 {document_id} 不存在")
        conn.commit()


def display_name(evidence_project: str, evidence_type: str, seq: int) -> str:
    """规范展示名:【业绩·项目简称】类型_序号。原文件名仍留在 file_name。"""
    short = _norm(evidence_project)[:16] or evidence_project[:16]
    return f"【业绩·{short}】{evidence_type}_{seq + 1:02d}"
