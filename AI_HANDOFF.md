# AI Handoff — WorkBuddy (DeepSeek V4-Pro) ↔ Codex (GPT-5.5)

> 每次 push 后更新状态。另一个 AI 打开项目时先读这个文件。

---

## 当前状态 (2026-06-14 02:09)

**V2 原文复制 — DOCX + PDF 全线完成**

```
✅ DOCX: OOXML 原样复制（表格/边框/下划线/对齐 100% 保真）
✅ PDF:  页面级图像复制（200 DPI 全页图像嵌入 DOCX，像素级保真）
✅ 256 passed, 3 skipped
✅ API: BID_GENERATION_MODE=v2
✅ 失败不回退 Markdown 近似
```

**原样复制方式:**
| 格式 | 方式 | 保真度 | 文件 |
|------|------|--------|------|
| DOCX | OOXML deepcopy | 100% | `original_docx_format_service.py:build_original_format_docx` |
| PDF | 页面级图像渲染 200DPI | 100% | `original_docx_format_service.py:build_original_format_docx_from_pdf` |

**替换规则:** 仅占位符 `（招标人名称）（项目名称）（投标人名称）` 做有限替换，不动格式

**真实中标标书基线（对比用）:**
- 南陵县三里镇: 183页/41K字 商务+技术+报价全有
- 萧县2025公路: 892页/322K字 200+页施工方案工程细节

**原则铁律:** 结构交给原文；原文 > 代码 > LLM
