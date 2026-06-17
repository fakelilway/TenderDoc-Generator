"""抽取招标第三章「评标办法」→ 结构化评审标准(供"以招标标准审标书")。

刻意只喂评标办法那几页(评审因素/评审标准/评分细则/否决条款),让 LLM 逐条照抄招标原文 +
真实条款号,而不是凭常识编通用规则。产出 JSON,由 review_method_service 装进 TenderReviewMethod。
"""

from __future__ import annotations

_SYSTEM = (
    "你是招投标评标专家。任务:把招标文件第三章「评标办法」里写明的评审标准,"
    "**逐条照抄**成结构化 JSON。铁律:只输出招标原文写了的内容,不得用常识/经验补充或编造;"
    "招标没写的就不写。每条尽量带上真实条款号(如 2.1.1、3.2（3）)。"
)

_INSTRUCTION = """从下面的「评标办法」正文里抽取三类内容,输出**纯 JSON**(不要解释、不要 markdown 围栏):

{
  "method_name": "评标办法名称(如 技术评分最低标价法 / 综合评估法),没有则空字符串",
  "total_score": 总分数字(如 100,没有写则 0),
  "criteria": [
    {
      "category": "形式评审 | 响应性评审 | 资格评审 | 详细评审 (按招标归类)",
      "clause_no": "条款号(如 2.1.1（3）),没有则空",
      "factor": "评审因素(简短,如 投标文件签字盖章 / 投标报价 / 项目经理资格)",
      "standard": "评审标准原文(照抄招标这一条的标准,可适当截断但不改意思)",
      "is_reject": true/false  // 该条不符合是否导致否决/不通过(初步评审/资格评审通常 true)
    }
  ],
  "score_items": [
    {
      "clause_no": "条款号",
      "factor": "评分因素(如 施工组织设计-总体施工布置 / 类似业绩 / 履约信誉)",
      "max_score": 该项满分数字(如 4 / 15 / 30),
      "rule": "评分细则原文(基本分、加分区间、满分条件等,照抄)"
    }
  ],
  "rejection_rules": [
    { "clause_no": "条款号", "rule": "否决投标(废标)情形原文(如 串通投标、低于成本、修正价不接受、未提供XX 等)" }
  ]
}

要点:
- criteria 覆盖初步评审(形式评审表、响应性评审表)和资格评审标准里**每一条**评审因素与标准。
- score_items 覆盖评分办法里**每个评分因素及其分值与细则**(施工组织设计/主要人员/履约信誉/类似业绩等)。
- rejection_rules 覆盖"否决投标"那一节列明的**每一种**否决情形。
- 抽不到某类就给空数组。务必照抄原文,不要改写成你自己的判断标准。

评标办法正文:
---
{review_text}
---
只输出 JSON。"""


def build_review_method_prompt(review_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _INSTRUCTION.replace("{review_text}", review_text or "")},
    ]
