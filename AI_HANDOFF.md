# AI Handoff — WorkBuddy (DeepSeek V4-Pro) ↔ Codex (GPT-5.5)

> 每次 push 后更新状态。另一个 AI 打开项目时先读这个文件。

---

## 当前状态 (2026-06-14 00:40)

**V2 全文复制骨架 — 流程跑通，正在优化内容质量**

```
✅ V2-M1~M7 全部完成
✅ 5/5 真实 case 格式提取通过
✅ API: BID_GENERATION_MODE=v2 (3bc10f8)
✅ Content Writer 强化: ≥5段/节, 真实中标风格示例
✅ Form Filler 强化: 招标人/项目名/工期/质量自动填入
🔧 待加强: 表格数量少(3 vs 49-75)、施工方案篇幅薄(9K vs 41K-322K字)

📊 VS 真实中标标书基线:
  南陵县三里镇(183页/41K字) + 萧县2025(892页/322K字) = 黄金标准
  每次生成后对比: 表格密度/施工篇幅/项目针对性/填空率
```

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
