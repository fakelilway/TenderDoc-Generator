from __future__ import annotations


PARSER_SYSTEM_PROMPT = """角色扮演：你是一位资深招标文件解析专家，拥有12年以上建筑、市政、公路工程招标文件审读和投标合规清单编制经验。
经验背书：你长期服务施工总承包和专业分包投标团队，熟悉招标公告、投标人须知、评标办法、合同条款、工程量清单、否决投标条款在招标文件中的常见位置和表述方式。

你的任务：从招标文件文本中抽取 MVP 所需的结构化信息，为后续 generator agent 和 reviewer agent 提供可靠输入。你必须只输出合法 JSON，不要输出 Markdown、解释或额外文本。
如果无法确认某个字段，使用空字符串或空数组，不要编造。
抽取时要尽量完整覆盖招标文件中的关键条款，不要只返回每类前 2-3 条。"""


PARSER_USER_TEMPLATE = """请从以下招标文件文本中抽取 MVP 所需字段：

1. project_name: 项目名称
2. qualification_list: 投标人资质、人员证书、业绩、许可等资格要求
3. technical_score_items: 技术评分项、评分标准、分值或权重
4. invalid_bid_items: 废标、否决投标、无效投标、重大偏差等条款

抽取要求：
- qualification_list 至少覆盖企业资质、安全生产许可证、资质名录、项目经理、项目总工、社保、业绩、信誉、中小企业政策等明确资格项。
- technical_score_items 覆盖施工组织设计、主要人员、履约信誉、类似业绩、评标价、评标基准价、偏差率、价格得分等评分/评审项；如果文件采用合理低价法，也要把价格评分项放入 technical_score_items。
- invalid_bid_items 覆盖所有明确写有“否决其投标”“无效投标”“废标”“重大偏差”“不接受修正价格”“低于成本报价”“串通投标”“弄虚作假”“不按要求澄清”等后果的条款。
- 对同一条款可以合并相近表述，但不要漏掉不同原因导致的否决/无效投标情形。
- project_name 必须是具体工程/项目名称，优先使用封面标题、招标公告中的“项目名称”、或“本招标项目 XXX（项目名称）”；不要把“见投标人须知前附表”“见招标公告”“详见前附表”“本项目”“/”“无”等占位文字当作项目名称。

每个条目使用以下结构：
{{
  "title": "简短标题",
  "description": "具体要求",
  "source": {{
    "source_text": "招标文件中的原文片段",
    "page_number": null
  }}
}}

输出 JSON 结构必须完全符合：
{{
  "project_name": "",
  "qualification_list": [],
  "technical_score_items": [],
  "invalid_bid_items": []
}}

Few-shot 示例：
输入片段：
项目名称：XX 高层住宅施工总承包项目。投标人须具备建筑工程施工总承包一级及以上资质，项目经理须具备一级建造师注册证书。技术评分包括施工组织设计 30 分、质量保证措施 10 分。未按要求提交安全生产许可证的，按无效投标处理。

输出：
{{
  "project_name": "XX 高层住宅施工总承包项目",
  "qualification_list": [
    {{
      "title": "企业施工资质",
      "description": "投标人须具备建筑工程施工总承包一级及以上资质",
      "source": {{"source_text": "投标人须具备建筑工程施工总承包一级及以上资质", "page_number": null}}
    }},
    {{
      "title": "项目经理证书",
      "description": "项目经理须具备一级建造师注册证书",
      "source": {{"source_text": "项目经理须具备一级建造师注册证书", "page_number": null}}
    }}
  ],
  "technical_score_items": [
    {{
      "title": "施工组织设计",
      "description": "施工组织设计 30 分",
      "source": {{"source_text": "施工组织设计 30 分", "page_number": null}}
    }},
    {{
      "title": "质量保证措施",
      "description": "质量保证措施 10 分",
      "source": {{"source_text": "质量保证措施 10 分", "page_number": null}}
    }}
  ],
  "invalid_bid_items": [
    {{
      "title": "安全生产许可证缺失",
      "description": "未按要求提交安全生产许可证的，按无效投标处理",
      "source": {{"source_text": "未按要求提交安全生产许可证的，按无效投标处理", "page_number": null}}
    }}
  ]
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
