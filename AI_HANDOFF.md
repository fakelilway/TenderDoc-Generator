# AI Handoff — WorkBuddy (DeepSeek V4-Pro) ↔ Codex (GPT-5.5)

> 每次 push 后更新状态。另一个 AI 打开项目时先读这个文件。

---

## 当前状态 (2026-06-14 00:02)

**V2 原文复制骨架 — 全线完成并接入 API**

```
✅ V2-M1  格式页提取器      extract_format_pages()         零LLM
✅ V2-M2  原文模板抽取      Codex 已完成                   零LLM
✅ V2-M3  Form Filler       fill_page_template()           零LLM
✅ V2-M4  Content Writer    fill_technical_volume()         1次LLM
✅ V2-M5  三层审计          full_audit()                   1次LLM
✅ V2-M6  端到端管线        generate_v2_bid_package()      已接入API
✅ V2-M7  5/5真实case验证   长丰/萧县/南陵/颍州/鸠江 全过
```

**API 模式:** `BID_GENERATION_MODE=v2` (.env)，切回 V1 改 `multi_agent`

**关键决定:**
- Pass 1 结构审计去 LLM — 确定性比对，不再幻觉假阳性
- 结构从"代码生成"升级到"原文复制"（第一性原理）
- 零 LLM 层：格式提取 + 表单填空 + 格式审计 + 证据审计

**测试:** 235 passed, 3 skipped

**下一步建议:**
- 跑一次前端端到端（点「重新生成」→ 查看输出）
- 从 V1 Markdown 骨架完全切换到 V2
- 删除 `_enforce_skeleton_headings` 和 LLM Pass 1 等 V1 专用代码

**原则铁律:** 结构交给原文；原文 > 代码 > LLM

## 开发环境

```
后端: localhost:8001 (BID_GENERATION_MODE=v2)
前端: localhost:3000
数据库: Docker (PostgreSQL + Redis + MinIO)
测试: ./venv/bin/python3 -m pytest tests/ -q
```

## 真实 Case 覆盖

| Case | 类型 | 格式页 | 验证 |
|------|------|--------|------|
| 长丰县罗塘乡 | 三卷 公开招标 | 32页 | ✅ |
| 萧县2025公路 | 双信封 | 41页 | ✅ |
| 南陵县三里镇 | 双信封 | 36页 | ✅ |
| 颍州区袁集镇 | 竞争性磋商 DOCX | 8页 | ✅ |
| 鸠江区日常养护 | 竞争性磋商 养护 | 9页 | ✅ |
