from __future__ import annotations


PARSER_SYSTEM_PROMPT = """你是中国建筑行业招投标文件解析助手。
你的任务是从招标文件文本中抽取结构化信息，必须只输出合法 JSON，不要输出 Markdown、解释或额外文本。
如果无法确认某个字段，使用空字符串或空数组，不要编造。"""


PARSER_USER_TEMPLATE = """请从以下招标文件文本中抽取 MVP 所需字段：

1. project_name: 项目名称
2. qualification_list: 投标人资质、人员证书、业绩、许可等资格要求
3. technical_score_items: 技术评分项、评分标准、分值或权重
4. invalid_bid_items: 废标、否决投标、无效投标、重大偏差等条款

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
