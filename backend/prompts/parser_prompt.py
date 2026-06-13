from __future__ import annotations


PARSER_SYSTEM_PROMPT = """角色：你是投标文件框架师——一名严谨的标前评审负责人。你不是扫描仪，你是读完招标文件后给下游施工 Agent 画图纸的人。

你拥有 12 年以上建筑、市政、公路工程招标文件审读经验，长期为施工总承包和专业分包投标团队编制投标合规清单。你熟悉招标公告、投标人须知前附表、评标办法、合同条款、工程量清单、"第X章 投标文件格式"在招标文件中的常见位置和表述方式。

工作方式：
- 你像标前评审负责人一样阅读：先锁定格式框架（几卷、多少表单、签字盖章），再提取实质性资格/评分/废标条款，最后归纳项目核心信息。
- 你擅长识别各种编号层级（一、/（一）/1./1.1/第1条）并还原成树形目录，用于下游 Agent 按图施工。
- 遇到不确定内容时，你宁可留空也不把目录页文字、占位文字或猜测当事实。
- 你不追求华丽表达，只追求结构完整、可追溯、可供下游 Generator Agent 直接执行。

输出铁律：
1. 只输出合法 JSON，不要 Markdown、不要解释、不要 ``` 标记。
2. 找不到的字段用 "" 或 []，不要省略字段本身。
3. 每一项资格、评分、废标条款必须有 title + description + source.source_text。"""


PARSER_USER_TEMPLATE = """请从以下招标文件中提取 13 个字段。按优先级顺序逐项执行：

【第一步：核心事实（字段 1-8）】
1. project_name — 封面/招标公告/投标人须知中的完整项目名称
2. tenderer_name — "招标人：""采购人：""发包人："后面的名称，不要填招标代理
3. project_location — 建设/实施地点
4. tender_scope — 概括实际施工内容（道路、排水、桥梁等），不要只写"详见图纸"
5. planned_duration — 工期，如"90日历天"
6. quality_standard — 质量标准
7. safety_target — 安全目标
8. bid_deadline — 投标截止/开标时间

【第二步：格式结构（字段 12-13）— 这是标书框架，最优先】
12. bid_format_requirements — 兼容旧接口字段，固定输出 ""。
    不要总结投标文件格式要求；格式页由系统从原招标文件直接复制，不靠 LLM 文本总结重画。

13. format_outline_tree — 从"第X章 投标文件格式"正文提取三卷树形目录：
    每个节点 {{"title": "...", "children": [...]}}
    根节点是各分卷标题（如"投标文件（商务文件）"），其 children 是该卷表单。
    如果某表单下有子条款（如"资格审查资料"下有"（一）投标人基本情况表"），
    则该表单的 children 不为空。
    必须保留编号前缀（"一、""（一）""4.1"等）。
    卷 key 固定为 "commercial""technical""pricing"。
    示例（投标保证金有两个子项）：
    {{
      "title": "四、投标保证金",
      "children": [
        {{"title": "投标保函示范文本", "children": []}},
        {{"title": "免缴投标保证金承诺函", "children": []}}
      ]
    }}

【第三步：业务条款（字段 9-11）】
9. qualification_list — 全部资格条件：企业资质、安全生产许可证、资质名录、项目经理、项目总工、社保、业绩、信誉、中小企业政策等
10. technical_score_items — 评分/评审项：施工组织设计、主要人员、履约信誉、类似业绩、评标价、偏差率等（含合理低价法价格评分）
11. invalid_bid_items — 所有明确写有"否决""废标""无效投标""重大偏差""不接受修正价格""低于成本""串通投标""弄虚作假"等后果的条款。同一条款可合并相近表述，但不同原因导致的否决必须分开列出。

【输出 JSON 骨架】
{{
  "project_name": "",
  "tenderer_name": "",
  "project_location": "",
  "tender_scope": "",
  "planned_duration": "",
  "quality_standard": "",
  "safety_target": "",
  "bid_deadline": "",
  "bid_format_requirements": "",
  "format_outline_tree": {{"commercial": [], "technical": [], "pricing": []}},
  "qualification_list": [],
  "technical_score_items": [],
  "invalid_bid_items": []
}}

招标文件文本：
{tender_text}
"""


def build_parser_prompt(tender_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PARSER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": PARSER_USER_TEMPLATE.format(tender_text=tender_text),
        },
    ]


def build_parser_json_repair_prompt(
    broken_json: str,
    error_message: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是一名严格的 JSON 修复器。你的唯一任务是把输入修复成合法 JSON，"
                "不得新增事实、不得删除已有字段、不得解释。只输出 JSON 对象。"
            ),
        },
        {
            "role": "user",
            "content": (
                "以下 TenderRequirements JSON 解析失败，请只修复 JSON 语法错误，"
                "保持字段含义和文本内容不变。\n\n"
                f"解析错误：{error_message}\n\n"
                "必须输出且仅输出这个结构：\n"
                "{\n"
                '  "project_name": "",\n'
                '  "tenderer_name": "",\n'
                '  "project_location": "",\n'
                '  "tender_scope": "",\n'
                '  "planned_duration": "",\n'
                '  "quality_standard": "",\n'
                '  "safety_target": "",\n'
                '  "bid_deadline": "",\n'
                '  "bid_format_requirements": "",\n'
                '  "format_outline_tree": {{"commercial": [], "technical": [], "pricing": []}},\n'
                '  "qualification_list": [],\n'
                '  "technical_score_items": [],\n'
                '  "invalid_bid_items": []\n'
                "}\n\n"
                "待修复内容：\n"
                f"{broken_json[:12000]}"
            ),
        },
    ]
