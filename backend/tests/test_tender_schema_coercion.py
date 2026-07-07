"""TenderRequirements 对解析 LLM 输出形状抖动的纠形(2026-07-07 用户线上报错回归)。

报错原样:format_outline_tree.commercial 被 LLM 写成单个根节点 dict
({'title': '投标文件…', 'children': [...]}) 而非节点列表,pydantic list_type
校验失败导致整次解析报废。schema 现在 mode='before' 纠形兼容。
"""

from schemas.tender import FormatOutlineNode, TenderRequirements


def test_volume_as_single_root_dict_is_wrapped() -> None:
    req = TenderRequirements(
        format_outline_tree={
            "commercial": {
                "title": "投标文件商务卷",
                "children": [{"title": "一、投标函", "children": []}],
            },
            "technical": {"title": "投标文件技术卷 施工组织设计", "children": []},
            "pricing": {"title": "投标文件报价卷 工程量清单", "children": []},
        }
    )
    tree = req.format_outline_tree
    for key in ("commercial", "technical", "pricing"):
        assert isinstance(tree[key], list) and len(tree[key]) == 1
    assert tree["commercial"][0].children[0].title == "一、投标函"


def test_bare_string_nodes_and_dict_children_are_coerced() -> None:
    req = TenderRequirements(
        format_outline_tree={
            "commercial": [
                "一、投标函",
                {"title": "二、授权书", "children": {"title": "附:身份证", "children": None}},
            ],
            "technical": None,
        }
    )
    commercial = req.format_outline_tree["commercial"]
    assert commercial[0].title == "一、投标函"
    assert commercial[1].children[0].title == "附:身份证"
    assert req.format_outline_tree["technical"] == []


def test_wellformed_tree_unchanged() -> None:
    node = FormatOutlineNode(
        title="一、投标函", children=[FormatOutlineNode(title="附录A")]
    )
    req = TenderRequirements(format_outline_tree={"commercial": [node.model_dump()]})
    assert req.format_outline_tree["commercial"][0].children[0].title == "附录A"
