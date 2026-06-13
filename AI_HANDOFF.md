# AI Handoff — WorkBuddy (DeepSeek V4-Pro) ↔ Codex (GPT-5.5)

> 每次 push 后更新状态。另一个 AI 打开项目时先读这个文件。

---

## 当前状态 (2026-06-14 02:01)

**V2 原文复制骨架 — DOCX 已实现真正的 OOXML 原样复制**

```
✅ V2-M1~M7 全部完成
✅ 5/5 真实 case 格式提取通过
✅ API: BID_GENERATION_MODE=v2
✅ 🔥 DOCX OOXML 原样复制: 表格边框/合并单元格/下划线/对齐 100% 保真
⚠️ PDF: 仍走 Markdown 骨架路径（未实现原样复制）
```

**边界（说死，不误解）:**
- DOCX 输入 → `original_docx_format_service.py` 直接 copy 格式章 OOXML 元素
- DOCX 复制失败 → 直接报错，**不回退 Markdown 近似**
- PDF 输入 → Markdown 骨架路径（PDF→DOCX 原样复制是独立工程）
- 替换：仅占位符 `（招标人名称）（项目名称）` 做有限替换，不碰格式

**新文件:**
- `backend/services/original_docx_format_service.py` — 核心
- `backend/tests/test_original_docx_format_service.py` — 256 passed, 3 skipped

**真实中标标书基线（对比用）:**
- 南陵县三里镇: 183页/41K字 商务+技术+报价全有
- 萧县2025公路: 892页/322K字 200+页施工方案工程细节

**原则铁律:** 结构交给原文；原文 > 代码 > LLM
