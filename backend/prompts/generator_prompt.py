from __future__ import annotations

from schemas.tender import TenderRequirements


GENERATOR_SYSTEM_PROMPT = """你是中国建筑行业技术标书撰写助手。
请根据招标文件解析结果和企业知识库片段，撰写可直接进入技术标初稿的 Markdown 内容。
要求：内容务实、结构清晰，不要编造不存在的企业业绩或证书；如知识库没有依据，用通用施工管理表述。"""


def build_section_prompt(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> list[dict[str, str]]:
    chunks_text = "\n\n".join(
        f"[知识片段 {index + 1}]\n{chunk}" for index, chunk in enumerate(retrieved_chunks)
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

输出要求：
- 使用 Markdown。
- 第一行必须是二级标题 `## {section_title}`。
- 至少包含 3 个自然段或要点。
- 不要输出“待补充”“TODO”“占位符”等 placeholder。
"""
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)
