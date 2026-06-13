from __future__ import annotations

import re
from typing import Any

from schemas.tender import TenderRequirements


# Textual summary of how a real, submittable Chinese bid reads. The document
# structure comes from the tender's confirmed format requirements and the
# human-confirmed outline; DOCX visual styling comes from utils.docx_exporter.
# This prompt must not become another structural template.
REAL_BID_WRITING_SPEC = """真实投标文件文风与正文规范（务必逐条遵守）：
1. 文风：通篇正式、书面、承诺性工程语言，主语用“我单位／本公司／本项目部”。禁止口语、解释性旁白、对话语气以及“以下是／作为AI／本文档”等元话语。
2. 标题写法：沿用系统给出的招标文件格式要求和人工确认目录；若某章内部需要小节，使用真实标书常见层级“第X节、 → 一、 → （一） → 1. → （1）”。标题简洁，不带说明性后缀。
3. 正文：每个小节由完整段落组成（每段约3–6句），围绕施工部署、施工工艺、质量、安全、进度、环境保护、文明施工、应急保障等展开，写成连贯论述，不要写成要点清单或评分点摘要。
4. 表格：进度计划、劳动力／机械设备配置、项目管理机构、资格响应清单、附表等必须优先用 Markdown 表格表达，表头清晰、列项规范，避免把天然表格内容写成散文。
5. 图片：需要插入营业执照、资质证书、建造师证、建安证、交安证、职称证、业绩证明、施工平面图等知识库图片时，只能使用系统提供的 `{{knowledge_image:document_id=数字 caption="图片说明"}}` 标记。不得编造 document_id，不得引用清单外图片。
6. 排版由系统导出 DOCX 时统一套用（正文宋体小四、标题黑体加粗、首行缩进两字、1.5 倍行距、页眉页脚与页码自动生成）。因此正文中禁止自行书写页眉、页脚、页码或“第X页/共X页”。

【严禁输出（出现即视为错误）】
- “人工确认点”“待补充”“占位”“TODO”“本章响应度自查”“废标风险逐条响应自查表”等任何元注释、自查或提示性用语；
- 复制检索片段中的页码（如“第13页/共892页”）、页眉页脚、目录点线（…… 或 ......）、残缺词句、乱码或无关碎片；
- 将招标文件的评分规则、计分公式、招标条款原文大段照抄进投标正文（应转化为我方响应与承诺）。

【缺少企业真实数据时的处理】
报价、项目经理姓名、证书编号、业绩金额、保证金金额、招标人名称等企业事实数据若无依据：在该处保留下划线空白“________”，或采用真实表单写法（如“详见已标价工程量清单”）。绝不编造数据，也绝不写“人工确认点”之类的提示词——这些内容由投标人在工作台中自行填写。"""


GENERATOR_SYSTEM_PROMPT = f"""角色扮演：你是一位“真实投标文件总编 + 施工组织设计主笔 + 商务标合规顾问”。
经验背书：你拥有15年以上施工总承包、专业分包、市政道路、公路工程和政府采购工程项目投标文件编制经验，长期为施工企业编制可直接递交的一信封/二信封投标文件。你熟悉《招标投标法》《建筑工程施工组织设计规范》《建设工程工程量清单计价规范》、公路工程标准施工招标文件、地方公共资源交易中心电子标格式、资格审查资料组织方式、技术评分最低标价法和综合评分法常见评审口径。

人格化工作方式：
- 你不是写通用说明书的助手，而是对废标风险负责的投标文件主笔。你写出的每一段都要像真实投标文件正文，使用正式、承诺性、工程化语言。
- 你必须主动站在评标专家、招标代理和投标企业三方视角检查内容：是否响应招标文件、是否有依据、是否可落地、是否会触发废标。
- 你输出的是可直接排版递交的成稿，不是带批注的草稿。绝不在正文中加入任何提示、自查、确认点或解释性旁白。

你的任务：基于 parser agent 抽取并经人工确认的招标文件关键信息、投标文件格式要求、系统传入的人工确认目录、以及检索到的企业真实投标文件/企业自有素材，生成一份可直接套用 DOCX 排版、继续补充真实数据后递交的正式投标文件正文。招标文件格式要求决定卷册、表单和签章等强制结构；人工确认目录决定本次生成的章节顺序；公司风格案例只提供写作深度、表格习惯、图片位和语气参考；知识库/RAG 只提供真实资料和措辞素材；DOCX exporter 统一负责最终视觉排版。

{REAL_BID_WRITING_SPEC}

硬性原则：
1. 严格响应招标文件解析出的资格要求、评分办法、废标/否决条款，不能漏掉实质性要求，但要转化为我方承诺与措施，而非照抄条款。
2. 不得编造企业名称、人员姓名、证书编号、业绩金额、投标报价、保证金金额、银行账号等事实数据；缺少依据时按上文“缺少企业真实数据时的处理”留空白。
3. 知识库/RAG 样本中出现的人名、身份证号、电话、证书编号、具体金额等只属于历史样本，一律不得作为本项目事实写入正文，相应位置使用下划线空白。
4. 投标文件卷册、表单清单、签字盖章、正副本、密封/电子标要求必须以【招标文件格式要求】为最高权威；若招标文件采用第一信封/第二信封或资格标/技术标/商务标拆分，必须沿用对应顺序，不得强行改成技术标先行。
5. 完整标书必须覆盖资格/商务固定表单、技术标/施工组织设计、附表和报价/经济标说明；报价只生成目录和编制说明，具体数值留空白由投标人填写。
6. 不得从 prompt、RAG 或历史案例里自行发明本项目目录；系统已经传入的【招标文件格式要求】和【完整标书目录/人工确认结构】是本次生成的结构来源。
7. 公司风格案例不得覆盖招标文件格式要求；若案例目录与招标文件格式冲突，必须服从招标文件和人工确认目录。
"""


# Sample personal data leaked from historical bid documents must never reach
# the prompt: citizen ID numbers (18 digits, optional trailing X) and mainland
# mobile numbers are masked before any chunk is embedded.
_PII_PATTERNS = (
    re.compile(r"\d{17}[\dXx]"),  # 18-digit citizen ID, incl. trailing X
    re.compile(r"1[3-9]\d{9}"),  # 11-digit mobile number
)
_PII_MASK = "████"


def redact_pii(text: str) -> str:
    """Mask citizen IDs and mobile numbers in retrieved knowledge chunks."""
    for pattern in _PII_PATTERNS:
        text = pattern.sub(_PII_MASK, text)
    return text


def _clean_chunk(text: str) -> str:
    """Strip leaked page footers / dot leaders / noise from a retrieved chunk."""
    page_footer = re.compile(r"第\s*\d+\s*页\s*[/／共]?\s*\d*\s*页?")
    dots_only = re.compile(r"^[.·•。…\-—_=\s]+$")
    lines: list[str] = []
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if page_footer.fullmatch(stripped) or dots_only.match(stripped):
            continue
        lines.append(page_footer.sub("", stripped))
    return "\n".join(lines).strip()






def build_volume_agent_prompt(
    *,
    volume: str,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    bid_plan: dict[str, Any] | None = None,
    template_name: str = "",
    pricing_strategy: dict[str, Any] | None = None,
    knowledge_chunks: list[dict[str, Any]] | None = None,
    knowledge_images: list[dict[str, Any]] | None = None,
    tender_text: str = "",
    company_profile_block: str = "",
) -> list[dict[str, str]]:
    label = _volume_label(volume)
    volume_outline = _format_volume_outline(document_outline, volume)
    chunks = _format_long_context_chunks(
        _filter_chunks_for_volume(knowledge_chunks or [], volume)
    )
    images = _format_knowledge_images(knowledge_images)
    agent_profile = _volume_agent_profile(volume)
    profile_section = (
        "\n【投标人企业档案（已人工核实，必须原样使用）】\n" f"{company_profile_block}\n"
        if company_profile_block
        else ""
    )
    user_prompt = f"""请作为{label}分卷主笔，只生成本卷 Markdown 初稿。

{agent_profile}

项目名称：{requirements.project_name or "投标项目"}
投标人：{company_name}
公司风格案例：{template_name or "未选择，完全按招标文件格式和系统确认目录生成"}
{profile_section}

【项目核心字段】
- 招标人/采购人：{requirements.tenderer_name or "________"}
- 建设地点：{requirements.project_location or "________"}
- 招标范围/工程内容：{requirements.tender_scope or "________"}
- 计划工期：{requirements.planned_duration or "________"}
- 质量标准：{requirements.quality_standard or "________"}
- 安全目标：{requirements.safety_target or "________"}
- 投标截止时间：{requirements.bid_deadline or "________"}

【招标文件格式要求（最高权威）】
{requirements.bid_format_requirements or "- 招标文件未提取到明确格式要求；按本卷人工确认目录输出。"}

【本卷必需节点（从格式章节提取，逐项生成，不得增减）】
{_format_volume_node_tree(requirements, volume)}

【本项目标书框架 Skill 输出（分发前已确认，必须服从）】
{framework_brief or build_bid_framework_brief(requirements, document_outline)}

【本卷人工确认目录】
{volume_outline}

【生成计划/BidPlan】
{_format_bid_plan(bid_plan)}

【招标文件解析要求】
资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

【招标文件全文关键内容】
{_format_tender_text(tender_text)}

【生成规则——区分"照抄表单"和"自由撰写"】
本卷节点分为两类，你必须严格遵守各自的规则：

1. 照抄表单（投标函、法定代表人证明、授权委托书、保证金凭证、承诺书、各类表格等）：
   - 必须从招标文件全文关键内容中定位对应的模板原文，逐字照抄。
   - 表格必须原样复制表头和列项，不得改顺序、不得增删列。
   - 只允许替换公司信息（投标人名称→{company_name}、日期、法人代表等已提供的企业档案字段）。
   - 公司档案未提供的、无依据的事实数据，保留招标文件原文的下划线空白"________"。
   - 禁止改写、简写、用自己的话重述。

2. 自由撰写（施工组织设计、技术方案、施工部署等）：
   - 必须是成稿的连贯论述，不是评分点摘要。
   - 必须吸收招标文件全文中的工程范围、工期、质量标准、安全目标。
   - 每个主章至少3个小节，每节至少2段连贯论述。

【商务/报价约束】
{_format_pricing_strategy(pricing_strategy)}

【本卷可用企业资料】
{chunks or "暂无文本资料。请按招标文件要求和企业常规投标文件深度生成，不得编造企业事实。"}

{images}

【输出要求】
- 只输出{label}，禁止输出其他卷内容。
- 第一行必须是一级标题 `# {requirements.project_name or "投标项目"} {label}`。
- 必须覆盖【本卷人工确认目录】中的全部必需节点。
- 若同名表单在不同卷册中出现，必须按【本项目标书框架 Skill 输出】区分归属；不得把其他卷的投标函、报价表、资格表、施工组织设计复制到本卷。
- 不得编造企业名称、人员、证书编号、业绩金额、报价金额、保证金金额、银行账号；无依据处使用“________”或“详见已标价工程量清单”。
- 需要插入知识库图片时，单独一行使用 `{{{{knowledge_image:document_id=数字 caption="说明"}}}}`，只能使用【可插入知识库图片资料】列出的 document_id。
- 禁止输出页眉页脚、页码、目录点线、RAG 残片、自查表、AI 说明、生成器语气、“人工确认点/待补充/系统不自动生成”等提示词。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_volume_revision_prompt(
    *,
    volume: str,
    draft_markdown: str,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    audit_feedback: str = "",
    bid_plan: dict[str, Any] | None = None,
    pricing_strategy: dict[str, Any] | None = None,
    tender_text: str = "",
) -> list[dict[str, str]]:
    label = _volume_label(volume)
    user_prompt = f"""请作为{label}复核修订 Agent，基于招标全文和格式要求，只修订本卷 Markdown。

角色边界：
- 你是本卷终审编辑，不是重新生成整份标书的助手。
- 只允许补齐本卷漏项、修正不真实语气、修正格式响应、删除元话语。
- 禁止新增无依据事实，禁止改写成其他卷，禁止输出解释。

项目名称：{requirements.project_name or "投标项目"}
投标人：{company_name}

【招标文件格式要求（最高权威）】
{requirements.bid_format_requirements or "- 招标文件未提取到明确格式要求；按本卷人工确认目录输出。"}

【本项目标书框架 Skill 输出（分发前已确认，必须服从）】
{framework_brief or build_bid_framework_brief(requirements, document_outline)}

【本卷人工确认目录】
{_format_volume_outline(document_outline, volume)}

【总审打回修改意见】
{audit_feedback or "- 首轮本卷自查：补齐漏项、删除越卷内容、修正生成器语气。"}

【本卷必需节点树（从招标文件格式章节提取，必须逐项匹配，不得增减）】
{_format_volume_node_tree(requirements, volume)}

【生成计划/BidPlan】
{_format_bid_plan(bid_plan)}

【招标文件解析要求】
资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

【招标文件全文关键内容】
{_format_tender_text(tender_text)}

【生成规则——区分"照抄表单"和"自由撰写"】
本卷节点分为两类，你必须严格遵守各自的规则：

1. 照抄表单（投标函、法定代表人证明、授权委托书、保证金凭证、承诺书、各类表格等）：
   - 必须从招标文件全文关键内容中定位对应的模板原文，逐字照抄。
   - 表格必须原样复制表头和列项，不得改顺序、不得增删列。
   - 只允许替换公司信息（投标人名称→{company_name}、日期、法人代表等已提供的企业档案字段）。
   - 公司档案未提供的、无依据的事实数据，保留招标文件原文的下划线空白"________"。
   - 禁止改写、简写、用自己的话重述。

2. 自由撰写（施工组织设计、技术方案、施工部署等）：
   - 必须是成稿的连贯论述，不是评分点摘要。
   - 必须吸收招标文件全文中的工程范围、工期、质量标准、安全目标。
   - 每个主章至少3个小节，每节至少2段连贯论述。

【商务/报价约束】
{_format_pricing_strategy(pricing_strategy)}

【待修订本卷初稿】
{draft_markdown}

【输出要求】
- 只输出修订后的{label} Markdown。
- 第一行仍必须是一级标题。
- 保留合法的知识库图片标记。
- 必须落实【总审打回修改意见】；如果意见指出本卷出现不该有的其他卷表单，应直接删除该越卷表单。
- 删除“人工确认点/待补充/系统不自动生成/由模型生成/以下为”等元话语。
- 无依据金额、证书编号、人员姓名、日期等继续留“________”，不得编造。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_structure_audit_prompt(
    *,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    commercial_markdown: str,
    technical_markdown: str,
    pricing_markdown: str,
) -> list[dict[str, str]]:
    """Pass 1 audit: format outline tree match only. No content inspection."""
    project_name = requirements.project_name or "投标项目"
    tree_text = _format_outline_tree(requirements.format_outline_tree)
    user_prompt = f"""请作为投标文件结构审查 Agent，只做一件事：对比招标文件格式目录树和三卷生成的目录结构是否一致。

你只审查结构，不审查内容质量、废标风险、文笔、排版。结构不对的标书，内容写再好也没有意义。

项目名称：{project_name}
投标人：{company_name}

【招标文件格式目录树（唯一标准）】
只允许以下节点，不得多、不得少、不得放错卷：
{tree_text or framework_brief or "未能提取格式目录树，跳过结构审计"}

【框架约束（分发前已确认）】
{framework_brief or build_bid_framework_brief(requirements, document_outline)}

【各卷生成内容（只检查其目录/标题结构，不读正文）】
为节省 token，只提供每卷前 2000 字符（已含主要标题结构）：

== commercial / 商务资格卷 ==
{commercial_markdown[:2000]}
== technical / 技术卷 ==
{technical_markdown[:2000]}
== pricing / 报价经济卷 ==
{pricing_markdown[:2000]}

【输出要求】
只输出合法 JSON：
{{
  "status": "pass" 或 "revise",
  "summary": "一句话结构审查结论",
  "structural_issues": [
    {{
      "volume": "commercial" 或 "technical" 或 "pricing",
      "problem": "缺失节点 / 多余节点 / 放错卷 / 层级错位",
      "expected": "招标文件要求的是什么",
      "actual": "生成的是什么",
      "revision_prompt": "给该卷 Agent 的结构修改指令，只说怎么改结构，不说怎么写内容"
    }}
  ]
}}
- status=pass 当且仅当三卷结构完全匹配格式目录树（节点数量、层级、归属卷全部一致）。
- 只要有任一卷缺失必需节点、多出未要求节点、子节点层级错位或归属卷错误，status 必须是 revise。
- **status=revise 时，structural_issues 不能为空**——必须逐条写清楚哪个 volume、什么问题、怎么改。
- revision_prompt 只给结构层面的修改指令。不得涉及内容质量、废标风险或文笔。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_generation_audit_prompt(
    *,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    commercial_markdown: str,
    technical_markdown: str,
    pricing_markdown: str,
    tender_text: str = "",
) -> list[dict[str, str]]:
    project_name = requirements.project_name or "投标项目"
    user_prompt = f"""请作为投标文件内容审查 Agent（Pass 2：结构已通过），对三卷 Markdown 做废标风险、事实准确性和格式细节审查。

角色边界：
- 你不是合稿 Agent，不得输出修改后的标书正文。
- 你的任务是对照招标全文、招标文件格式要求、框架 Skill 输出和三卷正文，判断是否通过。
- 如果不通过，只输出可直接打回给对应分卷 Agent 的修改建议 prompt。
- 不得新增无依据事实；不得要求删除招标文件明确需要的表单。

项目名称：{project_name}
投标人：{company_name}

【招标文件格式要求（最高权威）】
{requirements.bid_format_requirements or "- 招标文件未提取到明确格式要求；按人工确认目录输出。"}

【本项目标书框架 Skill 输出（分发前已确认，必须服从）】
{framework_brief or build_bid_framework_brief(requirements, document_outline)}

【完整标书目录/人工确认结构】
{_format_outline(document_outline)}

【招标文件全文关键内容】
{_format_tender_text(tender_text)}

【生成规则——区分"照抄表单"和"自由撰写"】
本卷节点分为两类，你必须严格遵守各自的规则：

1. 照抄表单（投标函、法定代表人证明、授权委托书、保证金凭证、承诺书、各类表格等）：
   - 必须从招标文件全文关键内容中定位对应的模板原文，逐字照抄。
   - 表格必须原样复制表头和列项，不得改顺序、不得增删列。
   - 只允许替换公司信息（投标人名称→{company_name}、日期、法人代表等已提供的企业档案字段）。
   - 公司档案未提供的、无依据的事实数据，保留招标文件原文的下划线空白"________"。
   - 禁止改写、简写、用自己的话重述。

2. 自由撰写（施工组织设计、技术方案、施工部署等）：
   - 必须是成稿的连贯论述，不是评分点摘要。
   - 必须吸收招标文件全文中的工程范围、工期、质量标准、安全目标。
   - 每个主章至少3个小节，每节至少2段连贯论述。

【待审查三卷】
【commercial / 商务资格卷】
{commercial_markdown}

【technical / 技术卷】
{technical_markdown}

【pricing / 报价经济卷】
{pricing_markdown}

【输出要求】
- 只输出合法 JSON，不要 Markdown，不要解释。
- JSON 格式必须为：
  {{
    "status": "pass" 或 "revise",
    "summary": "一句话审查结论",
    "issues": [
      {{
        "volume": "commercial" 或 "technical" 或 "pricing" 或 "all",
        "severity": "critical" 或 "major" 或 "minor",
        "problem": "发现的问题",
        "revision_prompt": "给该分卷 Agent 的具体修改指令"
      }}
    ]
  }}
- 通过条件（结构已在 Pass 1 通过，此处只审内容）：没有废标/否决风险遗漏；没有生成器语气或 AI 元文本；没有编造企业事实数据；没有漏掉招标文件中的实质性资格、技术或评分要求；必填表单内容不为空。
- 如果发现问题，status 必须是 "revise"，issues 必须逐条给出对应 volume 和可执行 revision_prompt。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_bid_framework_brief(
    requirements: TenderRequirements,
    document_outline: list[dict[str, Any]],
) -> str:
    """Summarise the tender-native bid frame before dispatching volume agents."""
    volume_lines: dict[str, list[str]] = {
        "commercial": [],
        "technical": [],
        "pricing": [],
    }

    def walk(items: list[dict[str, Any]], inherited_volume: str = "") -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            volume = str(item.get("volume") or inherited_volume or "")
            label = _outline_volume_key(
                " ".join(
                    str(item.get(key) or "")
                    for key in ("title", "volume", "section_type")
                )
                + f" {volume}"
            )
            title = str(item.get("title") or "").strip()
            if title:
                volume_lines[label].append(title)
            children = item.get("children") or []
            if isinstance(children, list):
                walk(children, volume)

    walk(document_outline)
    lines = [
        "框架来源：招标文件格式要求 + 人工确认目录；该框架优先于风格案例和知识库。",
        "格式要求摘要：",
        requirements.bid_format_requirements.strip() or "未提取到明确格式要求，必须按人工确认目录生成。",
        "分卷任务边界：",
    ]
    for key, label in (
        ("commercial", "商务/资格卷"),
        ("technical", "技术卷"),
        ("pricing", "报价/经济卷"),
    ):
        titles = _dedupe_text(volume_lines[key])
        lines.append(
            f"- {label}：{'、'.join(titles[:30]) if titles else '本卷无明确节点；不得自行增加越卷表单。'}"
        )
    lines.extend(
        [
            "招标文件格式要求的完整目录树（必须按此结构生成，不得增减节点）：",
            _format_outline_tree(requirements.format_outline_tree),
            "强制规则：",
            "- 三个分卷 Agent 只能生成自己分配到的节点，不得互相补写。",
            "- 同名表单必须按卷册归属区分；双信封项目允许商务及技术文件和报价文件分别存在投标函。",
            "- 系统负责最终拼接和 DOCX 分卷标记，任何 Agent 不得输出内部 marker 或合稿说明。",
        ]
    )
    return "\n".join(lines)


def _format_outline_tree(tree: dict[str, list[Any]], indent: int = 0) -> str:
    """Render a format outline tree as indented ASCII-like text."""
    import json

    if not tree:
        return "- 未提取到格式目录树；按人工确认目录生成。"

    volume_labels = {"commercial": "商务文件", "technical": "技术文件", "pricing": "报价文件"}
    lines: list[str] = []

    for vol_key, vol_label in volume_labels.items():
        nodes = tree.get(vol_key, [])
        if not nodes:
            continue
        lines.append(f"{vol_label}")
        for node in nodes:
            if isinstance(node, dict):
                title = node.get("title", "")
                children = node.get("children", [])
            else:
                title = getattr(node, "title", "")
                children = getattr(node, "children", [])
            if not title:
                continue
            if children:
                lines.append(f"├── {title}")
                for child in children:
                    if isinstance(child, dict):
                        child_title = child.get("title", "")
                        grand_children = child.get("children", [])
                    else:
                        child_title = getattr(child, "title", "")
                        grand_children = getattr(child, "children", [])
                    if not child_title:
                        continue
                    if grand_children:
                        lines.append(f"│   ├── {child_title}")
                        for gc in grand_children:
                            gc_title = gc.get("title", "") if isinstance(gc, dict) else getattr(gc, "title", "")
                            if gc_title:
                                lines.append(f"│   │   └── {gc_title}")
                    else:
                        lines.append(f"│   └── {child_title}")
            else:
                lines.append(f"└── {title}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)


def _format_outline(document_outline: list[dict[str, Any]]) -> str:
    if not document_outline:
        return "- 系统未传入确认目录，请使用商务标、技术标、报价文件三卷完整结构。"

    lines: list[str] = []

    def walk(items: list[dict[str, Any]], depth: int = 0) -> None:
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            volume = str(item.get("volume") or "").strip()
            section_type = str(item.get("section_type") or "").strip()
            suffix = "；".join(part for part in (volume, section_type) if part)
            indent = "  " * depth
            lines.append(f"{indent}- {title}" + (f"（{suffix}）" if suffix else ""))
            children = item.get("children") or []
            if isinstance(children, list):
                walk(children, depth + 1)

    walk(document_outline)
    return "\n".join(lines) if lines else "- 系统未传入确认目录。"


def _format_volume_outline(document_outline: list[dict[str, Any]], volume: str) -> str:
    selected: list[dict[str, Any]] = []

    def walk(items: list[dict[str, Any]], parent_matches: bool = False) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            matches = _outline_item_matches_volume(item, volume) or parent_matches
            children = item.get("children") or []
            if matches:
                selected.append(item)
            if isinstance(children, list):
                walk(children, matches)

    walk(document_outline)
    return _format_outline(selected) if selected else _fallback_volume_outline(volume)


def _outline_item_matches_volume(item: dict[str, Any], volume: str) -> bool:
    text = " ".join(
        str(item.get(key) or "") for key in ("title", "volume", "section_type")
    )
    return _outline_volume_key(text) == volume


def _format_volume_node_tree(requirements: TenderRequirements, volume: str) -> str:
    """Render the format_outline_tree for a single volume as an exact node list."""
    nodes = requirements.format_outline_tree.get(volume, [])
    if not nodes:
        return f"- 未提取到{_VOLUME_LABELS.get(volume, volume)}格式树；按人工确认目录和格式要求生成。"

    lines: list[str] = []
    for node in nodes:
        title = node.title if hasattr(node, "title") else node.get("title", "")
        children = node.children if hasattr(node, "children") else node.get("children", [])
        lines.append(f"- {title}")
        for child in children:
            ct = child.title if hasattr(child, "title") else child.get("title", "")
            gc = child.children if hasattr(child, "children") else child.get("children", [])
            if gc:
                lines.append(f"  - {ct}")
                for g in gc:
                    gt = g.title if hasattr(g, "title") else g.get("title", "")
                    lines.append(f"    - {gt}")
            else:
                lines.append(f"  - {ct}")
    return "\n".join(lines)


def _outline_volume_key(text: str) -> str:
    if any(keyword in text for keyword in ("报价", "经济", "清单", "price")):
        return "pricing"
    if any(
        keyword in text for keyword in ("技术", "施工组织", "施工方案", "附图", "附表", "appendix")
    ):
        return "technical"
    return "commercial"


def _dedupe_text(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"\s+", "", item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _fallback_volume_outline(volume: str) -> str:
    if volume == "pricing":
        return "- 报价文件\n  - 投标总价\n  - 已标价工程量清单\n  - 报价编制说明"
    if volume == "technical":
        return "- 技术文件\n  - 施工组织设计\n  - 附图附表"
    return "- 商务/资格文件\n  - 投标函\n  - 法定代表人身份证明或授权委托书\n  - 资格审查资料\n  - 投标保证金\n  - 承诺函"


def _filter_chunks_for_volume(
    chunks: list[dict[str, Any]],
    volume: str,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for chunk in chunks:
        section = str(chunk.get("section_title") or "")
        title = str(chunk.get("title") or "")
        content = str(chunk.get("content") or "")
        text = f"{section} {title} {content[:240]}"
        if _text_matches_volume(text, volume):
            selected.append(chunk)
    return selected or chunks[:8]


def _text_matches_volume(text: str, volume: str) -> bool:
    if volume == "pricing":
        return any(keyword in text for keyword in ("报价", "清单", "投标总价", "计价"))
    if volume == "technical":
        return any(keyword in text for keyword in ("施工", "技术", "质量", "安全", "环保", "进度"))
    return any(
        keyword in text for keyword in ("商务", "资格", "证书", "营业执照", "授权", "保证金", "承诺")
    )


_VOLUME_LABELS = {"commercial": "商务文件", "technical": "技术文件", "pricing": "报价文件"}


def _volume_label(volume: str) -> str:
    return _VOLUME_LABELS.get(volume, volume)


def _volume_agent_profile(volume: str) -> str:
    if volume == "pricing":
        return "你是报价文件合规主笔，熟悉工程量清单、计价规范、投标总价扉页和报价编制说明。你的任务是生成报价卷的目录、依据和响应说明；没有正式清单和造价数据时必须留空白，不得编造金额。"
    if volume == "technical":
        return (
            "你是技术标/施工组织设计主笔，熟悉施工部署、主要施工方案、进度、质量、安全、环保、文明施工、应急和附图附表。你的任务是写出有项目针对性的技术标成稿。"
        )
    return "你是商务/资格文件合规主笔，熟悉投标函、法人授权、资格审查、保证金、承诺函、企业资料和电子标上传格式。你的任务是按招标文件格式生成商务/资格卷。"


def _format_long_context_chunks(chunks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, chunk in enumerate(chunks[:24], start=1):
        content = redact_pii(_clean_chunk(str(chunk.get("content") or "")))
        if not content:
            continue
        metadata = chunk.get("metadata") or {}
        title = chunk.get("title") or metadata.get("file_name") or f"企业资料 {index}"
        section = chunk.get("section_title") or "未指定章节"
        lines.append(f"[资料 {index}] 标题：{title}；适用章节：{section}\n{content[:1800]}")
    return "\n\n".join(lines)


def _format_bid_plan(bid_plan: dict[str, Any] | None) -> str:
    if not bid_plan:
        return "- 未传入 BidPlan；请以确认目录、招标要求和已选资料为准。"
    sections = bid_plan.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return "- BidPlan 未包含章节计划；请以确认目录、招标要求和已选资料为准。"
    lines: list[str] = []
    for section in sections[:30]:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if not title:
            continue
        chunk_ids = section.get("evidence_chunk_ids") or []
        image_ids = section.get("image_document_ids") or []
        table_required = section.get("table_required")
        notes = section.get("notes") or section.get("writing_notes") or ""
        parts = [f"- {title}"]
        if chunk_ids:
            parts.append(f"文本资料 chunk_id={','.join(str(v) for v in chunk_ids[:8])}")
        if image_ids:
            parts.append(f"图片 document_id={','.join(str(v) for v in image_ids[:8])}")
        if table_required:
            parts.append("需要表格")
        if notes:
            parts.append(str(notes)[:160])
        lines.append("；".join(parts))
    return "\n".join(lines) if lines else "- BidPlan 未包含可读章节计划。"


def _format_tender_text(tender_text: str) -> str:
    text = _clean_chunk(tender_text or "")
    if not text:
        return "- 当前项目未保存招标全文；只能依据解析 JSON 和已选资料生成。"

    keywords = (
        "项目名称",
        "工程名称",
        "招标范围",
        "建设地点",
        "计划工期",
        "工期",
        "质量",
        "安全",
        "环保",
        "文明施工",
        "施工组织",
        "评分",
        "技术",
        "资格",
        "否决",
        "废标",
        "工程量",
        "清单",
        "图纸",
        "公路",
        "道路",
        "桥梁",
        "管网",
        "交通",
        # 投标文件格式/组成要求：招标文件对商务卷表单和编排的规定必须进上下文
        "格式",
        "投标函",
        "投标文件的组成",
        "编制要求",
        "装订",
        "密封",
        "签字",
        "盖章",
        "授权委托",
        "承诺",
        "声明",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected: list[str] = []
    selected_length = 0
    for line in lines:
        if any(keyword in line for keyword in keywords):
            selected.append(line)
            selected_length += len(line) + 1
        if selected_length >= 14000:
            break
    if not selected:
        selected = lines[:220]
    excerpt = "\n".join(selected)
    return excerpt[:18000]


def _format_pricing_strategy(pricing_strategy: dict[str, Any] | None) -> str:
    if not pricing_strategy:
        return "- 未提取到明确商务/报价约束；报价数值均留空白，按招标文件和工程量清单人工复核。"
    lines: list[str] = []

    def append_conditions(label: str, values: list[Any]) -> None:
        if not values:
            return
        lines.append(f"{label}：")
        for value in values[:5]:
            if isinstance(value, dict):
                text = value.get("source_text") or value.get("name") or str(value)
            else:
                text = str(value)
            lines.append(f"- {text}")

    # 工期/报价约束没有独立字段，存放在 extracted_conditions 里按 name 区分。
    extracted = [
        item
        for item in (pricing_strategy.get("extracted_conditions") or [])
        if isinstance(item, dict)
    ]
    append_conditions("付款条件", pricing_strategy.get("payment_terms") or [])
    append_conditions("保证金/担保要求", pricing_strategy.get("guarantee_requirements") or [])
    append_conditions(
        "工期要求",
        [item for item in extracted if "工期" in str(item.get("name", ""))],
    )
    append_conditions(
        "报价约束",
        [item for item in extracted if "报价" in str(item.get("name", ""))],
    )

    manual_fields = [
        field
        for field in (pricing_strategy.get("manual_fields") or [])
        if isinstance(field, dict) and field.get("label")
    ]
    if manual_fields:
        lines.append("必须留空白线（________）由人工填写的字段：")
        for field in manual_fields[:8]:
            reason = str(field.get("reason") or "").strip()
            label = str(field.get("label") or "").strip()
            lines.append(f"- {label}" + (f"（{reason}）" if reason else ""))

    return "\n".join(lines) if lines else "- 报价数值均留空白，按招标文件和工程量清单人工复核。"


def _format_knowledge_images(
    knowledge_images: list[dict[str, object]] | None,
) -> str:
    if not knowledge_images:
        return "【可插入知识库图片资料】\n- 暂无。"
    lines = [
        "【可插入知识库图片资料】",
        "以下图片来自企业知识库，可在资格资料、人员证件、业绩证明、附图附表等需要展示原件扫描件的位置插入；只能使用这些 document_id：",
    ]
    for image in knowledge_images[:12]:
        document_id = image.get("document_id")
        caption = image.get("caption") or image.get("file_name") or "知识库图片资料"
        file_name = image.get("file_name") or ""
        tags = image.get("tags") or []
        tag_text = (
            "、".join(str(tag) for tag in tags[:4]) if isinstance(tags, list) else ""
        )
        lines.append(
            f'- document_id={document_id}；caption="{caption}"；file="{file_name}"；tags="{tag_text}"；插入标记：{{{{knowledge_image:document_id={document_id} caption="{caption}"}}}}'
        )
    return "\n".join(lines)
