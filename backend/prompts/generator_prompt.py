from __future__ import annotations

from schemas.tender import TenderRequirements


GENERATOR_SYSTEM_PROMPT = """你是中国公路工程投标文件编制专家，不是通用文章写作助手。
你必须严格参考企业既有真实投标文件的格式、章节层级、正式语气和内容颗粒度来写。
优先模仿“施工组织设计”模板：章、节、一、二、三分级，表达要像正式投标文件，不要像摘要或聊天回答。
不得编造企业不存在的证书、业绩、人员编号、报价金额；缺少事实依据时写“响应招标文件要求”或使用通用施工组织措施。"""


def build_section_prompt(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> list[dict[str, str]]:
    chunks_text = "\n\n".join(
        f"[企业真实投标文件/知识库片段 {index + 1}]\n{chunk}"
        for index, chunk in enumerate(retrieved_chunks)
    )
    user_prompt = f"""请撰写技术标章节：{section_title}

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
- 输出必须像企业正式投标文件的“施工组织设计”，不是简单说明。
- 第一行必须是二级标题 `## {section_title}`。
- 标题层级使用：`### 第一节、...`、`#### 一、...`、`#### 二、...`。
- 每章至少写 2 个小节，每个小节至少 2 段或 3 条措施。
- 优先复用企业真实投标文件片段中的章节组织方式、措辞风格、管理措施和施工技术表达。
- 对公路工程场景，优先覆盖路基、路面、交通导行、测量、护栏、质量、安全、环保、文明施工、应急等内容。
- 必须明确响应招标文件中的工期、质量、安全、资质、废标/否决风险要求。
- 可以写“我单位”“本公司”“本项目部”，语气正式、承诺性强。
- 禁止写成泛泛而谈的 3 段总结，禁止输出“待补充”“TODO”“占位符”。

输出要求：
- 使用 Markdown。
- 不要输出“待补充”“TODO”“占位符”等 placeholder。
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
        f"[企业真实投标文件模板片段 {index + 1}]\n{chunk[:900]}"
        for index, chunk in enumerate(retrieved_chunks[:10])
        if chunk.strip()
    )
    user_prompt = f"""请根据招标文件解析结果和企业真实投标文件模板，生成一份“施工组织设计”技术文件初稿。

项目名称：{requirements.project_name}
投标人：{company_name}

必须使用以下目录，标题文字不得擅自改写：
{_format_items(outline_titles)}

资格要求：
{_format_items([item.description for item in requirements.qualification_list])}

技术评分/评审要求：
{_format_items([item.description for item in requirements.technical_score_items])}

废标/否决风险：
{_format_items([item.description for item in requirements.invalid_bid_items])}

企业真实投标文件模板片段：
{chunks_text or "暂无模板片段。"}

硬性要求：
- 输出 Markdown。
- 开头必须包含 `# {requirements.project_name or '投标项目'} 投标文件（技术文件）`。
- 必须包含 `投标人：{company_name}`。
- 必须包含 `## 施工组织设计目录`，并列出上述九章目录。
- 正文必须按九章展开，每章标题使用 `## 第一章、...` 这种格式。
- 每章至少包含 `### 第一节、...` 和 `#### 一、...` / `#### 二、...` 层级。
- 写法要模仿企业真实投标文件，不要写成产品说明、摘要或聊天回答。
- 必须明确响应工期、质量、安全、资质和否决风险要求。
- 不得编造证书编号、人员身份证号、报价金额、具体业绩；无依据时写“响应招标文件要求”。
- 不要输出“待补充”“TODO”“占位符”。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)
