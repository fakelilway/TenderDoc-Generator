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
| 格式 | 商务卷=照抄格式章、技术卷=生成正文、不出报价 | 必须 | ✅ 两卷装配 | ✅ |
| 表格 | 商务/报价表格数 vs 招标格式页表格数 | ≥ 90% | 待测 | ❓ |

## 交付装配（现状）

- 所有原格式文档走两卷装配 `_assemble_two_volumes`：
  - 商务卷 = 格式章照抄（PDF=整页截图+已知字段烧录进表单；DOCX=copy-then-prune 保留页眉脚/图片）+ 合规正文。
  - 技术卷 = LLM 施工组织设计正文（标准 25 节深度大纲），独立成文档（正奇排版 + 自动更新目录），不与商务格式页混排。
  - 报价卷不产出（外部造价软件）。
- 旧的关键字/`format_outline_tree`/页块三卷拆分已**删除**：真实招标文件里技术=生成、报价=外部，格式章≈商务卷，没有可拆的三卷。
- PDF 商务卷为纯内联图（已弃用 VML 文本层/pdf2docx），Pages/LibreOffice/Word/新点都能渲染。

## 首次 E2E 实测（招标#1，无知识库，2026-06-15）

`generate_v2_bid_package` 跑通（audit 未阻断），技术正文 6169 压缩字。

- 评分点响应率 **2/3 = 67%**，唯一未命中是「投标报价评分」——**报价项，本就外部造价软件管、不入技术卷**。技术相关评分点实为 **2/2**。
- 废标项 **2/27 = 7%**，未命中全是**商务/报价废标**（商务文件形式/资格/响应性评审、报价文件评审…）。

> **重要：响应率必须按卷分母。** 技术评分项 vs 技术正文；商务/报价废标 vs 商务卷照抄+填空 + reviewer 审查。拿全部 27 个（多为商务/报价）废标比技术正文 → 7% 是分母错位，不是质量问题。`benchmark_vs_baseline.py` 后续应按卷拆分响应率。

## 视觉回归注意

- `visual_regression.py`（soffice 渲染）对**技术卷**（markdown→docx，无 VML）可靠。
- 对**商务卷**（整页图 + VML 填空框）**不可靠**：实测 16 页格式章被 soffice 渲成 46 页（每页夹 2 空白页）。已隔离证实是 **soffice 多节+浮动 VML 形状的渲染缺陷**（image-only 多节=16 页✓、单节+填空框=1 页✓，仅"多节+VML"在 soffice 膨胀），**很可能非 Word/新点的真实缺陷**，待用 Word 核实。商务卷视觉以"页标记数"为准。

## 待办

- 响应率指标需要先用 Parser 解析出 `requirements.json`（含 `technical_score_items`/`invalid_bid_items`）才能算；并按卷拆分分母。
- 用 Word/新点核实商务卷是否真有空白页（soffice 渲染不可信）。

## 验收流程

1. 用真实招标文件跑通生成，导出 DOCX。
2. `compare` 生成稿与配对的真实中标标书 + 解析 requirements。
3. 所有 ❌/❓ 维度逐个推到阈值，再请人工按 `docs/visual_review_checklist.md` 目视终审。
