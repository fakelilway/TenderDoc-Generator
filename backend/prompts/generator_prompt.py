from __future__ import annotations

import re

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


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)


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


