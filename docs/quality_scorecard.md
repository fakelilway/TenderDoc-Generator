# 质量评分卡：对标真实中标标书

判定"满意"的唯一客观依据。每次改动后用 `backend/scripts/benchmark_vs_baseline.py` 重跑，数字达阈值才算达标。

## 怎么跑

```bash
# 单文件指标
.venv/bin/python backend/scripts/benchmark_vs_baseline.py stats <doc.pdf|doc.docx>

# 生成稿 vs 基线（带响应率）
.venv/bin/python backend/scripts/benchmark_vs_baseline.py compare \
  --generated <生成稿.docx> \
  --baseline "data/baseline/真实投标文件（标书）/1.真实投标文件.PDF" \
  --requirements <解析出的 requirements.json> \
  --json eval_results/benchmark.json
```

精确页数依赖 LibreOffice（`soffice`，已装于 `/Applications/LibreOffice.app/...`，脚本自动探测）。

## 基线现状（2026-06-14 实测）

| 文件 | 页数 | 字数(压缩) | 备注 |
|------|------|-----------|------|
| 基线#1 真实投标文件 | 183 | 69,877 | 全卷含附件 |
| 当前生成稿（萧县项目，商务+技术） | 27 | 7,079 | 仅两卷，无附件 |

> 即便扣掉附件与报价卷，生成稿篇幅仍比真实中标标书低约一个数量级——**篇幅与深度是首要短板**（对应 Phase 1.3）。

## 阈值（满意线）

| 维度 | 指标 | 阈值 | 当前 | 状态 |
|------|------|------|------|------|
| 篇幅 | 技术卷字数 / 基线技术卷字数 | ≥ 60% | ~10%（粗估） | ❌ |
| 篇幅 | 技术卷页数 | ≥ 基线技术卷 70% | 待测 | ❌ |
| 响应 | 评分点响应率 | ≥ 90% | 待测（需 requirements.json） | ❓ |
| 响应 | 废标项响应率 | 100% | 待测 | ❓ |
| 填空 | 残留下划线占位数 | ≤ 基线水平 | 0（生成稿） | ✅ |
| 格式 | 三卷均非空且无错卷 | 必须 | ❌ 见下 | ❌ |
| 表格 | 商务/报价表格数 vs 招标格式页表格数 | ≥ 90% | 待测 | ❓ |

## 已知阻塞（2026-06-14）

- **卷拆分在真实招标文件上失效**：关键字 substring 命中目录/正文造成错卷；无关键字时整章复制进三卷。导致"三卷均非空且无错卷"不达标。详见 Phase 2.3，需改为按 `format_outline_tree` 表单清单驱动拆卷。
- 响应率指标需要先用 Parser 解析出 `requirements.json`（含 `technical_score_items`/`invalid_bid_items`）才能算。

## 验收流程

1. 用真实招标文件跑通生成，导出 DOCX。
2. `compare` 生成稿与配对的真实中标标书 + 解析 requirements。
3. 所有 ❌/❓ 维度逐个推到阈值，再请人工按 `docs/visual_review_checklist.md` 目视终审。
