from __future__ import annotations

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
) -> list[dict[str, str]]:
    chunks_text = "\n\n".join(
        f"[企业真实投标文件模板/企业自有素材片段 {index + 1}]\n{chunk[:1200]}"
        for index, chunk in enumerate(retrieved_chunks[:12])
        if chunk.strip()
    )
    user_prompt = f"""请根据招标文件解析结果和企业真实投标文件模板，生成一份完整的“投标文件初稿”，必须包含【技术标】和【商务标】两大部分，并且必须先输出技术标、后输出商务标。

项目名称：{requirements.project_name}
投标人：{company_name}

【技术标】必须使用以下目录，标题文字不得擅自改写：
{_format_items(outline_titles)}

资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

企业真实投标文件模板/企业自有素材片段：
{chunks_text or "暂无模板片段。"}

输出结构必须严格如下：
# {requirements.project_name or '投标项目'} 投标文件（技术标及商务标）
投标人：{company_name}

## 投标文件响应总说明

【技术标】
## 一、技术标
### 1. 施工组织设计
### 2. 质量管理体系与措施
### 3. 安全管理体系与措施
### 4. 工期保证措施
### 5. 资源配置计划
### 6. 绿色施工、文明施工及环保措施
### 7. 特殊气候条件施工措施
### 8. 与业主、监理、设计单位的配合协调方案

【商务标】
## 二、商务标
### 1. 投标函及投标函附录
### 2. 法定代表人身份证明及授权委托书
### 3. 资格审查资料
### 4. 报价文件
### 5. 投标保证金承诺函或已缴凭证说明
### 6. 其他承诺

## 三、废标风险逐条响应自查表

商务标写作要求：
- 投标函中必须出现投标报价、工期、质量、投标有效期等字段；没有具体数值时用 `⚠️人工确认点：【待补充】...`。
- 资格审查资料必须逐项响应解析出的资格要求，包括企业资质、安全生产许可证、项目经理资格、技术负责人、业绩、社保等。
- 报价文件只写“已标价工程量清单目录”和“编制说明”，不得编造报价金额。
- 对投标保证金、农民工工资、质量、安全、环保、工期、廉洁、无转包违法分包等承诺明确成文。

技术标写作要求：
- 必须吸收企业真实投标文件片段中的正式措辞和章节深度。
- 必须覆盖施工部署、分部分项施工方法、进度计划、总平面布置、质量、安全、工期、资源、绿色文明、季节性施工、协调配合。
- 对招标文件技术评分点要逐项嵌入相应章节，不要只列清单。

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
