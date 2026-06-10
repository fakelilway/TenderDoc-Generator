# 正奇模板库说明

当前仓库内置模板优先服务正奇建设市政/公路投标业务，不作为全行业模板库维护。

## 第一版模板方向

- 市政工程
- 公路改建/扩建
- 交通安全设施养护
- 商务资格文件
- 报价文件

现有 `road_first_envelope_template.json` 来自公路工程第一信封商务及技术文件样本，可作为公路类项目的默认模板基线。

后续新增模板应带有清晰标签：

- `project_type`: municipal / highway / traffic_safety
- `specialty`: road / reconstruction / maintenance / guardrail / marking 等
- `volume`: commercial / technical / pricing / combined
- `region`
- `project_year`

模板 JSON 决定章节结构；prompt 不硬编码目录。
