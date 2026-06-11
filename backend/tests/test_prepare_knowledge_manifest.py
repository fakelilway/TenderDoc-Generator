from pathlib import Path

from scripts import prepare_knowledge_manifest
from scripts.prepare_knowledge_manifest import (
    KnowledgeManifestRow,
    build_manifest,
    import_rows_to_knowledge_base,
    read_csv_manifest,
    write_csv,
)


def test_prepare_knowledge_manifest_classifies_company_and_person_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "knowledge"
    source.mkdir()
    (source / "1.江舟一建注册证至2026.08.23.jpg").write_bytes(b"image")
    (source / "正奇二级最新资质2029-11-28.jpeg").write_bytes(b"image")
    (source / "业绩统计表.xlsx").write_bytes(b"sheet")

    rows = build_manifest(source)
    by_original = {Path(row.original_path).name: row for row in rows}

    person = by_original["1.江舟一建注册证至2026.08.23.jpg"]
    assert person.document_category == "人员证件"
    assert person.owner_name == "江舟"
    assert person.certificate_type == "一级建造师证"
    assert person.valid_to == "2026-08-23"
    assert "有效期至20260823" in person.suggested_filename

    qualification = by_original["正奇二级最新资质2029-11-28.jpeg"]
    assert qualification.document_category == "公司证件"
    assert qualification.owner_name == "安徽正奇建设有限公司"
    assert qualification.certificate_type == "资质证书"
    assert qualification.valid_to == "2029-11-28"

    performance = by_original["业绩统计表.xlsx"]
    assert performance.document_category == "业绩"
    assert performance.usage_scope == "仅参考"
    assert performance.image_insertable is False


def test_read_csv_manifest_round_trips_tags_and_booleans(tmp_path: Path) -> None:
    row = KnowledgeManifestRow(
        original_path=str(tmp_path / "a.jpg"),
        suggested_filename="人员证件_人员-江舟_建安证_通用_有效期待核验_待核验.jpg",
        suggested_path=str(tmp_path / "copy.jpg"),
        file_type="jpg",
        document_category="人员证件",
        owner_type="人员",
        owner_name="江舟",
        certificate_type="建安证",
        image_insertable=True,
        tags=["建安证", "江舟"],
        confidence=0.88,
        review_required=True,
    )
    manifest = tmp_path / "manifest.csv"

    write_csv([row], manifest)
    loaded = read_csv_manifest(manifest)

    assert loaded[0].image_insertable is True
    assert loaded[0].review_required is True
    assert loaded[0].tags == ["建安证", "江舟"]
    assert loaded[0].confidence == 0.88


def test_import_rows_skips_review_required_by_default(tmp_path: Path) -> None:
    source = tmp_path / "证件.jpg"
    source.write_bytes(b"image")
    row = KnowledgeManifestRow(
        original_path=str(source),
        suggested_filename="人员证件_人员-江舟_建安证_通用_有效期待核验_待核验.jpg",
        suggested_path=str(source),
        file_type="jpg",
        document_category="人员证件",
        owner_type="人员",
        owner_name="江舟",
        certificate_type="建安证",
        image_insertable=True,
        review_required=True,
    )

    results = import_rows_to_knowledge_base([row])

    assert results[0]["status"] == "skipped_review_required"


def test_import_rows_calls_existing_knowledge_indexer(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "证件.jpg"
    source.write_bytes(b"image")
    row = KnowledgeManifestRow(
        original_path=str(source),
        suggested_filename="人员证件_人员-江舟_建安证_通用_有效期待核验_待核验.jpg",
        suggested_path=str(source),
        file_type="jpg",
        project_type="通用",
        document_type="建安证",
        document_category="人员证件",
        specialty="通用",
        volume="资格文件",
        owner_type="人员",
        owner_name="江舟",
        certificate_type="建安证",
        valid_to="",
        sensitivity="敏感",
        usage_scope="可用于投标",
        verified_status="待核验",
        image_insertable=True,
        tags=["建安证", "江舟"],
        review_required=True,
    )
    captured = {}

    def fake_index_uploaded_knowledge(**kwargs):
        captured.update(kwargs)
        return {
            "document_id": 99,
            "chunk_ids": [1001],
            "indexing_status": "structured_evidence",
        }

    monkeypatch.setattr(
        "services.knowledge_service.index_uploaded_knowledge",
        fake_index_uploaded_knowledge,
    )

    results = prepare_knowledge_manifest.import_rows_to_knowledge_base(
        [row],
        include_review_required=True,
    )

    assert results[0]["status"] == "imported"
    assert results[0]["document_id"] == 99
    assert captured["filename"] == row.suggested_filename
    assert captured["document_category"] == "人员证件"
    assert captured["owner_name"] == "江舟"
    assert captured["certificate_type"] == "建安证"
    assert captured["image_insertable"] is True
    assert captured["ingestion_mode"] == "structured_evidence"
    assert captured["tags"] == ["建安证", "江舟"]
