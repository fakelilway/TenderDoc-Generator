# 正奇历史案例说明

当前仓库内置历史案例优先服务正奇建设市政/公路投标业务，不作为全行业模板库维护，也不作为线上默认结构来源。

## 第一版案例方向

- 市政工程
- 公路改建/扩建
- 交通安全设施养护
- 商务资格文件
- 报价文件

现有 `road_first_envelope_template.json` 来自公路工程第一信封商务及技术文件样本，可作为公路类项目的离线评估样本或手动选择的风格案例。

后续新增案例应带有清晰标签：

- `project_type`: municipal / highway / traffic_safety
- `specialty`: road / reconstruction / maintenance / guardrail / marking 等
- `volume`: commercial / technical / pricing / combined
- `region`
- `project_year`

线上生成时，案例 JSON 不决定章节结构；招标文件格式要求和人工确认目录才是结构来源。
