from __future__ import annotations

import re

from schemas.bid_template import BidTemplate
from schemas.strategy import PricingStrategy
from schemas.tender import TenderRequirements


# Textual summary of how a real, submittable Chinese bid reads. The document
# structure comes from BidTemplate JSON; DOCX visual styling comes from
# utils.docx_exporter. This prompt must not become another structural template.
REAL_BID_WRITING_SPEC = """真实投标文件文风与正文规范（务必逐条遵守）：
1. 文风：通篇正式、书面、承诺性工程语言，主语用“我单位／本公司／本项目部”。禁止口语、解释性旁白、对话语气以及“以下是／作为AI／本文档”等元话语。
2. 标题写法：沿用系统给出的 BidTemplate 章节标题和顺序；若某章内部需要小节，使用真实标书常见层级“第X节、 → 一、 → （一） → 1. → （1）”。标题简洁，不带说明性后缀。
3. 正文：每个小节由完整段落组成（每段约3–6句），围绕施工部署、施工工艺、质量、安全、进度、环境保护、文明施工、应急保障等展开，写成连贯论述，不要写成要点清单或评分点摘要。
4. 表格：进度计划、劳动力／机械设备配置、附表等用 Markdown 表格表达，表头清晰、列项规范。
5. 排版由系统导出 DOCX 时统一套用（正文宋体小四、标题黑体加粗、首行缩进两字、1.5 倍行距、页眉页脚与页码自动生成）。因此正文中禁止自行书写页眉、页脚、页码或“第X页/共X页”。

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

你的任务：基于 parser agent 抽取的招标文件关键信息、系统传入的 BidTemplate 结构、以及检索到的企业真实投标文件/企业自有素材，生成一份可直接套用 DOCX 排版、继续补充真实数据后递交的正式投标文件正文。招标 JSON 决定必须响应什么，BidTemplate JSON 是唯一章节结构来源，知识库/RAG 只提供措辞和素材，DOCX exporter 统一负责最终视觉排版。

{REAL_BID_WRITING_SPEC}

硬性原则：
1. 严格响应招标文件解析出的资格要求、评分办法、废标/否决条款，不能漏掉实质性要求，但要转化为我方承诺与措施，而非照抄条款。
2. 不得编造企业名称、人员姓名、证书编号、业绩金额、投标报价、保证金金额、银行账号等事实数据；缺少依据时按上文“缺少企业真实数据时的处理”留空白。
3. 技术标必须排在商务标之前，并使用企业真实投标文件/知识库片段中的章节风格、正式措辞和施工组织深度，不得写成摘要、说明书或聊天回答。
4. 商务标必须包含投标函、授权委托、资格审查、报价文件、投标保证金、承诺函等内容；报价只生成目录和编制说明，具体数值留空白由投标人填写。
5. 不得从 prompt、RAG 或招标文件原文里自行发明目录；系统已经传入的 BidTemplate/outline 是唯一章节结构来源。
6. 如果没有 BidTemplate，才允许使用生成器的兜底章节；一旦有 BidTemplate，必须优先沿用模板顺序和章节名称。
"""


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


def build_section_prompt(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> list[dict[str, str]]:
    cleaned_chunks = [
        c for c in (_clean_chunk(chunk) for chunk in retrieved_chunks) if c
    ]
    chunks_text = "\n\n".join(
        f"[企业真实投标文件/知识库片段 {index + 1}]\n{chunk}"
        for index, chunk in enumerate(cleaned_chunks)
    )
    user_prompt = f"""请撰写【技术标】章节：{section_title}

项目名称：{requirements.project_name}

资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

可参考的企业素材（仅供吸收措辞与深度，禁止照抄其页码、点线或残句）：
{chunks_text or "暂无可参考片段，请按企业既有公路/市政/建筑投标文件的施工组织设计深度撰写。"}

写作约束必须遵守：
- 输出 Markdown。
- 第一行必须是二级标题 `## {section_title}`。
- 不得改写传入的章节标题；章内小节可使用：`### 第一节、...`、`#### 一、...`、`#### 1. ...`、`#### （1）...`。
- 内容必须像正式投标文件，语气使用“我单位”“本公司”“本项目部”，每个小节由完整段落组成，保持承诺性、落地性。
- 每章至少写 2 个小节，每个小节至少 2 段连贯论述或一张规范表格。
- 必须明确响应招标文件中的工期、质量、安全、资质、评分点和废标/否决风险，并转化为我方措施与承诺。
- 涉及人员、证书、业绩、报价等无依据的企业事实数据时，按规范留下划线空白“________”，禁止编造，禁止写“人工确认点/待补充”等提示词。
- 严禁出现页码、页眉页脚、目录点线、自查语句或解释性旁白。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_document_prompt(
    requirements: TenderRequirements,
    outline_titles: list[str],
    retrieved_chunks: list[str],
    company_name: str,
    bid_template: BidTemplate | None = None,
    pricing_strategy: PricingStrategy | None = None,
) -> list[dict[str, str]]:
    cleaned_chunks = [
        c for c in (_clean_chunk(chunk) for chunk in retrieved_chunks) if c
    ]
    chunks_text = "\n\n".join(
        f"[企业真实投标文件模板/企业自有素材片段 {index + 1}]\n{chunk[:1200]}"
        for index, chunk in enumerate(cleaned_chunks[:12])
    )
    user_prompt = f"""请根据招标文件解析结果和企业真实投标文件模板，生成一份完整的“投标文件正文”，必须包含【技术标】和【商务标】两大部分，并且必须先输出技术标、后输出商务标。

项目名称：{requirements.project_name}
投标人：{company_name}

结构来源优先级（必须遵守，避免死板冲突）：
1. 招标文件解析 JSON 决定“必须响应什么”：资格要求、评分点、废标/否决条款、工期质量安全等实质性要求。
2. BidTemplate JSON 是唯一章节结构来源：主目录、施工组织设计目录、固定表单、附表清单和章节顺序都以它为准。
3. 知识库/RAG 只提供素材、表述习惯和施工措施参考，不能改变章节结构。
4. 本 prompt 只提供角色、文风、真实性约束和缺少模板时的兜底规则；不得用 prompt 中的通用示例覆盖模板 JSON。

【确认生成结构】
以下目录已经由招标文件解析结果 + 真实模板 JSON 生成。必须沿用这些标题和顺序，不要擅自改写标题：
{_format_items(outline_titles)}

{_format_template_summary(bid_template)}

{_format_pricing_summary(pricing_strategy)}
资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

可参考的企业真实投标文件/企业自有素材（仅供吸收章节组织与措辞深度，禁止照抄页码、点线、残句）：
{chunks_text or "暂无可参考片段。"}

输出规则：
- 第一行使用 `# {requirements.project_name or '投标项目'} 投标文件（技术标及商务标）`。
- 标题下方写 `投标人：{company_name}`，随后写一段“投标文件响应总说明”正文（不加任何确认点）。
- 必须先输出 `【技术标】`，再输出 `【商务标】`。
- 技术标正文必须按【确认生成结构】输出；如果模板提供附表，必须在技术标末尾生成对应附表标题与正式的表格/用途说明。
- 商务标章节必须优先沿用 BidTemplate 中的固定表单/资格/声明章节；若模板没有给出商务标表单，才使用投标函、授权委托、资格审查、报价文件、投标保证金、承诺函作为兜底。

技术标写作要求：
- 吸收企业真实投标文件片段中的正式措辞和章节深度，写成连贯论述。
- 覆盖施工部署、分部分项施工方法、进度计划、总平面布置、质量、安全、工期、资源、绿色文明、季节性施工、协调配合。
- 把招标文件技术评分点逐项转化并嵌入相应章节的措施与承诺中，不要罗列评分规则原文。

商务标写作要求：
- 投标函中必须出现投标报价、工期、质量、投标有效期等字段；没有具体数值时保留下划线空白“________”。
- 资格审查资料必须逐项响应解析出的资格要求，包括企业资质、安全生产许可证、项目经理资格、技术负责人、业绩、社保等。
- 报价文件只写“已标价工程量清单目录”和“编制说明”，金额处留空白，不得编造报价金额。
- 对投标保证金、农民工工资、质量、安全、环保、工期、廉洁、无转包违法分包等承诺明确成文。

严禁事项（再次强调）：
- 正文中不得出现“人工确认点／待补充／占位／本章响应度自查／废标风险逐条响应自查表”等任何元注释或自查用语。
- 不得出现页码、页眉页脚、目录点线、检索片段残句或乱码。
- 不得整段照抄招标文件评分规则与条款原文。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)


def _format_pricing_summary(pricing_strategy: PricingStrategy | None) -> str:
    if not pricing_strategy:
        return ""
    parts: list[str] = ["商务标关键约束（从招标文件抽取，必须在商务标中逐条响应）："]
    if pricing_strategy.payment_terms:
        parts.append("付款条件约束：")
        for c in pricing_strategy.payment_terms[:4]:
            parts.append(
                f"  - {c.source_text[:120]}" if c.source_text else f"  - {c.name}"
            )
    if pricing_strategy.guarantee_requirements:
        parts.append("担保/保证金约束：")
        for c in pricing_strategy.guarantee_requirements[:4]:
            parts.append(
                f"  - {c.source_text[:120]}" if c.source_text else f"  - {c.name}"
            )
    if pricing_strategy.extracted_conditions:
        schedule = [c for c in pricing_strategy.extracted_conditions if "工期" in c.name]
        quote = [c for c in pricing_strategy.extracted_conditions if "报价" in c.name]
        if schedule:
            parts.append("工期约束：")
            for c in schedule[:2]:
                parts.append(
                    f"  - {c.source_text[:120]}" if c.source_text else f"  - {c.name}"
                )
        if quote:
            parts.append("报价/评标价约束：")
            for c in quote[:2]:
                parts.append(
                    f"  - {c.source_text[:120]}" if c.source_text else f"  - {c.name}"
                )
    if len(parts) == 1:
        return ""
    parts.append("（以上商务条件均须转化为我方响应与承诺，不得照抄条款原文，具体金额留下划线空白由投标人填写。）")
    return "\n".join(parts) + "\n"


def _format_template_summary(bid_template: BidTemplate | None) -> str:
    if not bid_template:
        return "真实模板 JSON：未提供。使用【确认生成结构】作为兜底目录，但不得覆盖招标文件实质性要求。"

    main_sections = _format_items(
        [
            f"{section.title}（{section.section_type}，页码 {section.start_page or '-'}-{section.end_page or '-'}）"
            for section in bid_template.main_sections
        ]
    )
    fixed_forms = _format_items(
        [section.title for section in bid_template.fixed_form_sections]
    )
    appendices = _format_items(
        [section.title for section in bid_template.appendix_sections]
    )

    return f"""真实模板 JSON 摘要：
- 模板名称：{bid_template.template_name}
- 模板信封/文件类型：{bid_template.envelope_type or '未识别'} / {bid_template.document_type or '未识别'}
- 模板主目录：
{main_sections}
- 模板固定表单/商务资料：
{fixed_forms}
- 模板附表：
{appendices}
"""
