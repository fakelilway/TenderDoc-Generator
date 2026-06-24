"""项目经理/总工证件插图标记生成测试(身份证正反 + 建造师/职称/安全/社保)。"""

from __future__ import annotations

import re

from services import v2_generation_service as v2


def test_personnel_cert_markdown_emits_idcard_and_certs(monkeypatch) -> None:
    # mock 身份证最小覆盖选图(正面+背面各一)
    monkeypatch.setattr(
        "services.asset_resolver.pick_id_card_documents",
        lambda name: [
            {"document_id": 1, "side": "front"},
            {"document_id": 2, "side": "back"},
        ],
    )
    # mock 知识库图片引用:江舟的建造师证/职称证/社保(社保无图)
    refs = [
        {"document_id": 10, "owner_name": "江舟", "certificate_type": "一级建造师证", "image_insertable": True, "file_type": "jpg"},
        {"document_id": 11, "owner_name": "江舟", "certificate_type": "职称证书", "image_insertable": True, "file_type": "jpg"},
        {"document_id": 12, "owner_name": "别人", "certificate_type": "一级建造师证", "image_insertable": True, "file_type": "jpg"},
    ]
    monkeypatch.setattr(
        "services.knowledge_service.list_knowledge_image_references",
        lambda *a, **k: refs,
    )

    md = v2._one_person_cert_markdown("项目经理", "江舟", "项目经理资历表")

    # 身份证正反两面 + 建造师 + 职称 都有标记;别人的不混入
    assert "身份证正面" in md and "身份证背面" in md
    assert "注册建造师证" in md
    assert "职称证书" in md
    doc_ids = re.findall(r"document_id=(\d+)", md)
    assert "1" in doc_ids and "2" in doc_ids  # 身份证正反
    assert "10" in doc_ids and "11" in doc_ids  # 江舟的证
    assert "12" not in doc_ids  # 别人的不取
    # 锚点正确(落到项目经理资历表后)
    assert 'anchor="项目经理资历表"' in md


def test_personnel_cert_markdown_empty_name() -> None:
    assert v2._one_person_cert_markdown("项目经理", "", "项目经理资历表") == ""


def test_personnel_cert_evidence_combines_pm_and_tech(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.asset_resolver.pick_id_card_documents", lambda name: []
    )
    monkeypatch.setattr(
        "services.knowledge_service.list_knowledge_image_references",
        lambda *a, **k: [
            {"document_id": 20, "owner_name": "张经理", "certificate_type": "二级建造师证", "image_insertable": True, "file_type": "jpg"},
            {"document_id": 21, "owner_name": "李总工", "certificate_type": "职称证书", "image_insertable": True, "file_type": "jpg"},
        ],
    )
    md = v2._personnel_cert_evidence_markdown("张经理", "李总工")
    assert "项目经理（张经理）" in md
    assert "项目技术负责人（李总工）" in md
    assert 'anchor="项目经理资历表"' in md
    assert 'anchor="项目总工资历表"' in md


def test_personnel_cert_evidence_empty_when_no_people() -> None:
    assert v2._personnel_cert_evidence_markdown("", "") == ""
