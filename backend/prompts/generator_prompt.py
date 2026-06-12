from __future__ import annotations

import re
from typing import Any

from schemas.tender import TenderRequirements


# Textual summary of how a real, submittable Chinese bid reads. The document
# structure comes from BidTemplate JSON; DOCX visual styling comes from
# utils.docx_exporter. This prompt must not become another structural template.
REAL_BID_WRITING_SPEC = """真实投标文件文风与正文规范（务必逐条遵守）：
1. 文风：通篇正式、书面、承诺性工程语言，主语用“我单位／本公司／本项目部”。禁止口语、解释性旁白、对话语气以及“以下是／作为AI／本文档”等元话语。
2. 标题写法：沿用系统给出的 BidTemplate 章节标题和顺序；若某章内部需要小节，使用真实标书常见层级“第X节、 → 一、 → （一） → 1. → （1）”。标题简洁，不带说明性后缀。
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

你的任务：基于 parser agent 抽取的招标文件关键信息、系统传入的 BidTemplate 结构、以及检索到的企业真实投标文件/企业自有素材，生成一份可直接套用 DOCX 排版、继续补充真实数据后递交的正式投标文件正文。招标 JSON 决定必须响应什么，BidTemplate JSON 是唯一章节结构来源，知识库/RAG 只提供措辞和素材，DOCX exporter 统一负责最终视觉排版。

{REAL_BID_WRITING_SPEC}

硬性原则：
1. 严格响应招标文件解析出的资格要求、评分办法、废标/否决条款，不能漏掉实质性要求，但要转化为我方承诺与措施，而非照抄条款。
2. 不得编造企业名称、人员姓名、证书编号、业绩金额、投标报价、保证金金额、银行账号等事实数据；缺少依据时按上文“缺少企业真实数据时的处理”留空白。
3. 知识库/RAG 样本中出现的人名、身份证号、电话、证书编号、具体金额等只属于历史样本，一律不得作为本项目事实写入正文，相应位置使用下划线空白。
4. 投标文件卷册和章节顺序必须以 BidTemplate 主目录为准；若招标文件采用第一信封/第二信封或资格标/技术标/商务标拆分，必须沿用对应顺序，不得强行改成技术标先行。
5. 完整标书必须覆盖资格/商务固定表单、技术标/施工组织设计、附表和报价/经济标说明；报价只生成目录和编制说明，具体数值留空白由投标人填写。
6. 不得从 prompt、RAG 或招标文件原文里自行发明目录；系统已经传入的 BidTemplate/outline 是唯一章节结构来源。
7. 如果没有 BidTemplate，才允许使用生成器的兜底章节；一旦有 BidTemplate，必须优先沿用模板顺序和章节名称。
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


def build_section_prompt(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
    knowledge_images: list[dict[str, object]] | None = None,
) -> list[dict[str, str]]:
    cleaned_chunks = [
        c for c in (redact_pii(_clean_chunk(chunk)) for chunk in retrieved_chunks) if c
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

{_format_knowledge_images(knowledge_images)}

写作约束必须遵守：
- 输出 Markdown。
- 第一行必须是二级标题 `## {section_title}`。
- 不得改写传入的章节标题；章内小节可使用：`### 第一节、...`、`#### 一、...`、`#### 1. ...`、`#### （1）...`。
- 内容必须像正式投标文件，语气使用“我单位”“本公司”“本项目部”，每个小节由完整段落组成，保持承诺性、落地性。
- 每章至少写 2 个小节，每个小节至少 2 段连贯论述或一张规范表格。
- 进度计划、劳动力计划、机械设备计划、质量/安全责任分工、资格响应清单等天然表格内容必须输出 Markdown 表格。
- 只有在【可插入知识库图片资料】中存在匹配资料时，才可在需要插图的位置单独一行输出知识库图片标记；禁止编造图片编号。
- 必须明确响应招标文件中的工期、质量、安全、资质、评分点和废标/否决风险，并转化为我方措施与承诺。
- 涉及人员、证书、业绩、报价等无依据的企业事实数据时，按规范留下划线空白“________”，禁止编造，禁止写“人工确认点/待补充”等提示词。
- 严禁出现页码、页眉页脚、目录点线、自查语句或解释性旁白。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_long_context_prompt(
    *,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    bid_plan: dict[str, Any] | None = None,
    template_name: str = "",
    pricing_strategy: dict[str, Any] | None = None,
    knowledge_chunks: list[dict[str, Any]] | None = None,
    knowledge_images: list[dict[str, Any]] | None = None,
    tender_text: str = "",
) -> list[dict[str, str]]:
    """Build the simple long-context generation prompt.

    This prompt is intentionally document-level: selected knowledge is provided
    as reference material, while the model must produce the complete bid in one
    pass so tender nuance is not lost between per-section calls.
    """
    chunks = _format_long_context_chunks(knowledge_chunks or [])
    images = _format_knowledge_images(knowledge_images)
    user_prompt = f"""请一次性生成完整投标文件 Markdown 成稿。

项目名称：{requirements.project_name or "投标项目"}
投标人：{company_name}
模板名称：{template_name or "未绑定真实模板，使用系统确认目录"}

【项目核心字段】
- 招标人/采购人：{requirements.tenderer_name or "________"}
- 建设地点：{requirements.project_location or "________"}
- 招标范围/工程内容：{requirements.tender_scope or "________"}
- 计划工期：{requirements.planned_duration or "________"}
- 质量标准：{requirements.quality_standard or "________"}
- 安全目标：{requirements.safety_target or "________"}
- 投标截止时间：{requirements.bid_deadline or "________"}

【必须输出的卷册】
请严格按下面三个内部卷册标记输出，标记本身必须原样保留，便于系统拆分 DOCX：
<!-- tdg:volume:commercial -->
# {requirements.project_name or "投标项目"} 商务文件

<!-- tdg:volume:technical -->
# {requirements.project_name or "投标项目"} 技术文件

<!-- tdg:volume:pricing -->
# {requirements.project_name or "投标项目"} 报价文件

【完整标书目录/模板结构】
{_format_outline(document_outline)}

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

【商务/报价约束】
{_format_pricing_strategy(pricing_strategy)}

【已选择/检索企业资料】
{chunks or "暂无文本资料。请按招标文件要求和企业常规投标文件深度生成，不得编造企业事实。"}

{images}

【生成要求】
- 输出只能是 Markdown 正文，不要解释你如何生成。
- 必须同时覆盖商务/资格资料、技术标/施工组织设计、附图附表、报价/经济标说明。
- 必须优先沿用【完整标书目录/模板结构】中的章节名称和顺序；不要自行发明大目录。
- 商务标写成真实投标文件语气，包含投标函、授权/法人证明、资格审查、保证金、承诺函等需要的正式内容。
- 技术标必须写成可交付的施工组织设计成稿，不要写评分点摘要或空泛原则；必须吸收招标文件全文中的工程范围、施工内容、工期、质量标准、安全环保、交通组织、材料/机械/人员、关键节点和验收要求。
- 每个施工组织设计主章至少包含 3 个有项目针对性的小节；每个小节至少 2 段连贯论述，不能只写一两句。
- 进度计划、劳动力/机械设备投入、项目管理机构、资格响应、主要施工工序、质量/安全责任分工等天然表格内容必须输出 Markdown 表格，表格数据无依据时用“________”，不要省略表格。
- 正文必须出现具体项目名称、工程类别、施工范围和招标文件要求的响应内容；禁止只输出通用格式壳。
- 报价文件只写真实报价文件目录、编制依据和响应说明；具体金额、清单单价、合价、税金等没有依据时留“________”，不得编造。
- 需要插入知识库图片时，单独一行使用 `{{{{knowledge_image:document_id=数字 caption="说明"}}}}`，只能使用【可插入知识库图片资料】列出的 document_id。
- 缺少人员姓名、证书编号、业绩金额、保证金金额、报价金额等事实依据时，使用“________”或“详见已标价工程量清单”，禁止写“人工确认点/待补充/系统不自动生成”等提示语。
- 禁止输出页眉页脚、页码、目录点线、RAG 残片、自查表、AI 说明或生成器语气。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


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
