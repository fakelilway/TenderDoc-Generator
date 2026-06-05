from __future__ import annotations

from schemas.bid_template import BidTemplate
from schemas.tender import TenderRequirements


GENERATOR_SYSTEM_PROMPT = """角色扮演：你是一位“真实投标文件总编 + 施工组织设计主笔 + 商务标合规顾问”。
经验背书：你拥有15年以上施工总承包、专业分包、市政道路、公路工程和政府采购工程项目投标文件编制经验，长期为施工企业编制可递交的一信封/二信封投标文件。你熟悉《招标投标法》《建筑工程施工组织设计规范》《建设工程工程量清单计价规范》、公路工程标准施工招标文件、地方公共资源交易中心电子标格式、资格审查资料组织方式、技术评分最低标价法和综合评分法常见评审口径。

人格化工作方式：
- 你不是写通用说明书的助手，而是对废标风险负责的投标文件主笔。你写出的每一段都要像真实投标文件正文，使用正式、承诺性、工程化语言。
- 你必须主动站在评标专家、招标代理和投标企业三方视角检查内容：是否响应招标文件、是否有依据、是否可落地、是否会触发废标。
- 当企业事实资料不足时，你必须像谨慎的标书负责人一样停在人工确认点，绝不替用户编造。

你的任务：基于 parser agent 抽取的招标文件关键信息、RAG 检索到的企业真实投标文件/企业自有素材、以及真实投标文件模板结构，生成可供人工审阅、继续补充后递交的正式投标文件初稿。输出必须同时覆盖【技术标】和【商务标】，且技术标必须排在商务标之前。

硬性原则：
1. 严格响应招标文件解析出的资格要求、评分办法、废标/否决条款，不能漏掉实质性要求。
2. 不得编造企业名称、人员姓名、证书编号、业绩金额、投标报价、保证金金额、银行账号等事实数据；缺少依据时必须使用“⚠️人工确认点：【待补充】...”标注。
3. 技术标必须排在商务标之前，并使用企业真实投标文件/知识库片段中的章节风格、正式措辞和施工组织深度，不得写成摘要、说明书或聊天回答。
4. 商务标必须包含投标函、授权委托、资格审查、报价文件、投标保证金、承诺函等内容；报价只生成目录和编制说明，具体数值要求人工填写。
5. 标题编号使用“一、1.（1）①”四级风格；施工组织设计章节优先使用“第X章、第X节、一、（一）”的真实标书层级；每个主要章节末尾必须有“本章响应度自查：完全满足”。
6. 对每一条废标/否决条款，必须在商务标或技术标中明确响应，并在文末设置“废标风险逐条响应自查表”。
7. 真实模板优先级高于通用写法：如果模板给出了主目录、施工组织设计目录、附表或固定表单，必须优先沿用模板顺序和章节名称。
"""


def build_section_prompt(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> list[dict[str, str]]:
    chunks_text = "\n\n".join(
        f"[企业真实投标文件/知识库片段 {index + 1}]\n{chunk}"
        for index, chunk in enumerate(retrieved_chunks)
    )
    user_prompt = f"""请撰写【技术标】章节：{section_title}

项目名称：{requirements.project_name}

资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

可引用知识库片段：
{chunks_text or "暂无知识库片段。"}

写作格式必须遵守：
- 输出 Markdown。
- 第一行必须是二级标题 `## {section_title}`。
- 章节标题层级使用：`### 第一节、...`、`#### 一、...`、`#### 1. ...`、`#### （1）...`。
- 内容必须像正式投标文件，语气使用“我单位”“本公司”“本项目部”，保持承诺性、落地性。
- 每章至少写 2 个小节，每个小节至少 2 段或 3 条措施。
- 优先复用企业真实投标文件片段中的章节组织方式、管理措施和施工技术表达。
- 对公路/市政/建筑场景，结合项目特点覆盖施工部署、关键工序、质量、安全、进度、环保、文明施工、应急等内容。
- 必须明确响应招标文件中的工期、质量、安全、资质、评分点和废标/否决风险。
- 涉及人员、证书、业绩、报价等企业事实数据时，若知识库无依据，必须写 `⚠️人工确认点：【待补充】...`。
- 章末必须写：`本章响应度自查：完全满足`。
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
) -> list[dict[str, str]]:
    chunks_text = "\n\n".join(
        f"[企业真实投标文件模板/企业自有素材片段 {index + 1}]\n{chunk[:1200]}"
        for index, chunk in enumerate(retrieved_chunks[:12])
        if chunk.strip()
    )
    user_prompt = f"""请根据招标文件解析结果和企业真实投标文件模板，生成一份完整的“投标文件初稿”，必须包含【技术标】和【商务标】两大部分，并且必须先输出技术标、后输出商务标。

项目名称：{requirements.project_name}
投标人：{company_name}

结构来源优先级（必须遵守，避免死板冲突）：
1. 招标文件解析 JSON 决定“必须响应什么”：资格要求、评分点、废标/否决条款、工期质量安全等实质性要求。
2. 真实投标文件模板 JSON 决定“按照什么格式写”：主目录、施工组织设计目录、固定表单、附表清单和章节顺序。
3. 本 prompt 只提供角色、写作原则、真实性约束和缺少模板时的兜底规则；不得用 prompt 中的通用示例覆盖模板 JSON。

【确认生成结构】
以下目录已经由招标文件解析结果 + 真实模板 JSON 生成。必须沿用这些标题和顺序，不要擅自改写标题：
{_format_items(outline_titles)}

{_format_template_summary(bid_template)}

资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

企业真实投标文件模板/企业自有素材片段：
{chunks_text or "暂无模板片段。"}

输出结构规则：
- 第一行使用 `# {requirements.project_name or '投标项目'} 投标文件（技术标及商务标）`。
- 标题下方写 `投标人：{company_name}` 和“投标文件响应总说明”。
- 必须先输出 `【技术标】`，再输出 `【商务标】`，最后输出“废标风险逐条响应自查表”。
- 技术标正文必须按【确认生成结构】输出；如果模板提供附表，必须在技术标末尾生成对应附表标题、用途说明和人工确认点。
- 商务标章节必须优先沿用模板主目录中的固定表单章节；若模板没有给出商务标表单，才使用投标函、授权委托、资格审查、报价文件、投标保证金、承诺函作为兜底。

技术标写作要求：
- 必须吸收企业真实投标文件片段中的正式措辞和章节深度。
- 必须覆盖施工部署、分部分项施工方法、进度计划、总平面布置、质量、安全、工期、资源、绿色文明、季节性施工、协调配合。
- 对招标文件技术评分点要逐项嵌入相应章节，不要只列清单。

商务标写作要求：
- 投标函中必须出现投标报价、工期、质量、投标有效期等字段；没有具体数值时用 `⚠️人工确认点：【待补充】...`。
- 资格审查资料必须逐项响应解析出的资格要求，包括企业资质、安全生产许可证、项目经理资格、技术负责人、业绩、社保等。
- 报价文件只写“已标价工程量清单目录”和“编制说明”，不得编造报价金额。
- 对投标保证金、农民工工资、质量、安全、环保、工期、廉洁、无转包违法分包等承诺明确成文。

废标规避要求：
- 对每条废标/否决风险，必须在正文中找到对应响应，并在“废标风险逐条响应自查表”中列出“风险条款 / 响应章节 / 响应措施 / 人工确认点”。
- 涉及未提供的企业真实数据，必须标注 `⚠️人工确认点：【待补充】`，不要虚构。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)


def _format_template_summary(bid_template: BidTemplate | None) -> str:
    if not bid_template:
        return "真实模板 JSON：未提供。使用【确认生成结构】作为兜底目录，但不得覆盖招标文件实质性要求。"

    main_sections = _format_items(
        [
            f"{section.title}（{section.section_type}，页码 {section.start_page or '-'}-{section.end_page or '-'}）"
            for section in bid_template.main_sections
        ]
    )
    fixed_forms = _format_items([section.title for section in bid_template.fixed_form_sections])
    appendices = _format_items([section.title for section in bid_template.appendix_sections])

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
