"""深读招标 → 投标规格(TenderSpec)的 LLM 抽取提示词(阶段一,先走 A=LLM)。

只抽闭环切片需要的结构化项;抽不准的表后续针对性上 PDF 真表解析(B)。
"""

from __future__ import annotations

DEEP_SPEC_SYSTEM = (
    "你是标前评审负责人,读招标文件、把'投标规格'抽成结构化数据供下游逐空核对。"
    "只输出合法 JSON,不要 Markdown、不要解释、不要 ``` 标记。找不到的留 \"\"/[]/null,绝不编。"
)

DEEP_SPEC_USER = """从下面招标文件里抽出"投标规格",只输出这个 JSON:

{{
  "duration": "计划工期原文(投标人须知前附表1.3.x,如 90日历天)",
  "bid_validity": "投标有效期原文(如 90日历天/60天)",
  "cert_requirements": [
    {{"cert_type": "企业资质", "required_value": "资质要求原文,必须含专业+等级(如 公路工程施工总承包二级及以上)", "source": "资格审查附录1或前附表条款号"}}
  ],
  "performance_requirement": {{"since": "时间下限原文(如 2022年以来/近3年)", "category": "同类工程类型", "min_amount_wan": 0, "min_count": 0, "time_basis": "交工"}},
  "attachment_requirements": {{"投标人基本情况表": ["营业执照", "资质证书", "安全生产许可证"]}},
  "instructions_table": [{{"clause_no": "1.3.2", "name": "计划工期", "content": "90日历天"}}],
  "contract_appendix": [{{"clause_no": "1.1.4.5", "name": "缺陷责任期", "content": "自实际交工日期起2年"}}]
}}

抽取规则:
- duration/bid_validity:从投标人须知前附表逐字照抄,别换算。
- cert_requirements:**企业资质必须抽出"专业+等级"原话**(如"公路工程施工总承包二级"),这关系到我方资质够不够、会不会没资格投。找资格审查条件/附录1/投标人须知前附表的资质条款。
- attachment_requirements:招标要求"投标人基本情况表后附"的证明材料(投标人须知3.5.1附近);抽不到就给 {{"投标人基本情况表": ["营业执照", "资质证书", "安全生产许可证"]}}。
- instructions_table:投标人须知前附表的关键行(条款号/名称/内容),抽到几行算几行。
- contract_appendix:投标函附录的合同参数行(条款号/名称/约定内容)。

招标文件文本:
{tender_text}
"""


def build_tender_spec_prompt(tender_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": DEEP_SPEC_SYSTEM},
        {"role": "user", "content": DEEP_SPEC_USER.format(tender_text=tender_text)},
    ]
