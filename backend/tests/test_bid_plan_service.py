from schemas.bid import BidDocumentOutlineSection
from schemas.evidence import EvidenceItem, EvidencePack
from schemas.template_profile import (
    TemplateProfile,
    TemplateSlot,
    TemplateVolumeProfile,
)
from schemas.tender import RequirementItem, TenderRequirements
from services.bid_plan_service import build_bid_plan


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="萧县农村公路项目",
        qualification_list=[RequirementItem(title="项目经理", description="项目经理须具备一级建造师")],
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 40 分")
        ],
        invalid_bid_items=[RequirementItem(title="投标保证金", description="未提交投标保证金无效")],
    )


def test_build_bid_plan_uses_template_profile_and_evidence_pack() -> None:
    profile = TemplateProfile(
        template_name="公路投标模板",
        volumes=[
            TemplateVolumeProfile(
                name="商务/资格标",
                role="business",
                section_titles=["资格审查资料"],
            ),
            TemplateVolumeProfile(
                name="技术标",
                role="technical",
                section_titles=["施工组织设计", "附表一、施工总体计划表"],
            ),
        ],
        section_order=["资格审查资料", "施工组织设计", "附表一、施工总体计划表"],
        image_slots=[
            TemplateSlot(
                section_title="资格审查资料",
                slot_type="knowledge_image",
                description="人员证件和公司证件扫描件",
                evidence_categories=["建造师", "营业执照"],
            )
        ],
        table_slots=[
            TemplateSlot(
                section_title="附表一、施工总体计划表",
                slot_type="table",
                description="施工总体计划表",
            )
        ],
        forbidden_phrases=["本系统自动生成"],
    )
    pack = EvidencePack(
        company_certificates=[
            EvidenceItem(
                chunk_id=11,
                document_id=101,
                title="营业执照",
                certificate_type="营业执照",
            )
        ],
        technical_schemes=[
            EvidenceItem(chunk_id=22, document_id=102, content="施工组织设计措施")
        ],
        image_evidence=[
            EvidenceItem(
                document_id=201,
                title="张三一级建造师证",
                certificate_type="建造师证",
                metadata={"tags": ["项目经理"]},
                evidence_type="image",
            )
        ],
    )

    plan = build_bid_plan(
        _requirements(),
        template_profile=profile,
        evidence_pack=pack,
    )

    qualification = plan.section_for_title("资格审查资料")
    technical = plan.section_for_title("施工组织设计")
    table = plan.section_for_title("附表一、施工总体计划表")

    assert plan.template_name == "公路投标模板"
    assert qualification
    assert qualification.evidence_chunk_ids == [11]
    assert qualification.image_document_ids == [201]
    assert technical
    assert technical.evidence_chunk_ids == [22]
    assert table
    assert table.table_required is True
    assert "本系统自动生成" in technical.forbidden_phrases


def test_build_bid_plan_can_fall_back_to_document_outline() -> None:
    plan = build_bid_plan(
        _requirements(),
        evidence_pack=EvidencePack(),
        document_outline=[
            BidDocumentOutlineSection(
                title="商务文件",
                volume="商务标",
                section_type="business_volume",
                children=[
                    BidDocumentOutlineSection(
                        title="投标函",
                        volume="商务标",
                        section_type="fixed_form",
                    )
                ],
            )
        ],
    )

    assert plan.sections[0].title == "商务文件"
    assert plan.sections[1].title == "投标函"
