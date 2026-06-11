from rag.retriever import RetrievalResult
from schemas.tender import RequirementItem, TenderRequirements
from services.evidence_pack_service import build_evidence_pack


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="萧县农村公路项目",
        qualification_list=[RequirementItem(title="项目经理", description="项目经理须具备一级建造师")],
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 40 分")
        ],
    )


def test_build_evidence_pack_classifies_documents_and_images() -> None:
    selected = [
        {
            "chunk_id": 11,
            "document_id": 101,
            "title": "安徽正奇营业执照.pdf",
            "content": "资料名称：安徽正奇营业执照\n资料类别：公司证件",
            "metadata": {
                "document_category": "公司证件",
                "certificate_type": "营业执照",
                "ingestion_mode": "structured_evidence",
            },
        },
        {
            "chunk_id": 12,
            "document_id": 102,
            "title": "历史施工组织设计.docx",
            "content": "施工组织设计应包含质量、安全、进度和环保保证措施。",
            "metadata": {"document_category": "历史投标文件"},
        },
    ]
    retrieved = [
        RetrievalResult(
            chunk_id=13,
            document_id=103,
            content="工程量清单报价编制说明和综合单价说明。",
            metadata={"file_name": "报价说明.docx"},
            distance=0.1,
            score=0.9,
        )
    ]
    images = [
        {
            "document_id": 201,
            "file_name": "人员_张三_建造师证.jpg",
            "caption": "张三一级建造师证",
            "document_category": "人员证件",
            "certificate_type": "建造师证",
            "tags": ["项目经理"],
            "match_score": 9,
        }
    ]

    pack = build_evidence_pack(
        _requirements(),
        selected_references=selected,
        image_references=images,
        retrieved_results=retrieved,
    )

    assert pack.selected_chunk_ids == [11, 12]
    assert pack.company_certificates[0].chunk_id == 11
    assert pack.technical_schemes[0].chunk_id == 12
    assert pack.pricing_attachments[0].chunk_id == 13
    assert pack.image_evidence[0].document_id == 201


def test_structured_image_summary_does_not_become_technical_scheme() -> None:
    pack = build_evidence_pack(
        _requirements(),
        retrieved_results=[
            RetrievalResult(
                chunk_id=31,
                document_id=301,
                content="资料名称：建安B证\n资料类别：人员证件\n图片用途：允许作为标书插图候选",
                metadata={
                    "file_name": "建安B证.jpg",
                    "file_type": "jpg",
                    "ingestion_mode": "structured_evidence",
                    "indexing_status": "structured_evidence",
                },
                distance=0.1,
                score=0.9,
            )
        ],
    )

    assert not pack.technical_schemes
    assert pack.person_certificates[0].chunk_id == 31
