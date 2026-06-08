import pytest

from schemas.bid_template import BidTemplate, BidTemplateSection
from services import template_service


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)

    def fetchall(self):
        rows = list(self.rows)
        self.rows = []
        return rows


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


def _template_row(**overrides):
    row = {
        "id": 1,
        "name": "公路模板",
        "source_filename": "road.pdf",
        "project_type": "公路工程",
        "specialty": "道路",
        "envelope_type": "第一信封",
        "region": "安徽",
        "project_year": 2025,
        "tags": ["公路", "市政"],
        "template_json": {"project_name": "某公路工程", "page_count": 120},
        "created_by": 1,
        "created_at": None,
    }
    row.update(overrides)
    return row


def test_create_template_parses_and_inserts(monkeypatch) -> None:
    cursor = FakeCursor([_template_row()])
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(
        template_service,
        "parse_bid_template_bytes",
        lambda file_bytes, source_file="", template_name="": BidTemplate(
            template_name=template_name,
            source_file=source_file,
            page_count=120,
            project_name="某公路工程",
            envelope_type="第一信封",
        ),
    )

    summary = template_service.create_template(
        b"%PDF-1.4 fake",
        "road.pdf",
        "公路模板",
        project_type="公路工程",
        specialty="道路",
        tags=["公路"],
        created_by=1,
    )

    assert summary["id"] == 1
    assert summary["project_name"] == "某公路工程"
    assert summary["page_count"] == 120
    insert_statement, _params = cursor.statements[0]
    assert "INSERT INTO bid_templates" in insert_statement


def test_create_template_rejects_non_pdf() -> None:
    with pytest.raises(ValueError):
        template_service.create_template(b"data", "bid.docx", "模板")


def test_seed_template_from_json_inserts_when_missing(monkeypatch, tmp_path) -> None:
    template_path = tmp_path / "default_template.json"
    template_path.write_text(
        BidTemplate(
            template_name="默认公路第一信封模板",
            source_file="road_first_envelope_template.json",
            page_count=10,
            envelope_type="第一信封",
            construction_design_sections=[BidTemplateSection(title="第一章、总体施工组织布置及规划")],
        ).model_dump_json(),
        encoding="utf-8",
    )
    cursor = FakeCursor(
        [
            None,
            _template_row(
                id=9,
                name="默认公路第一信封模板",
                source_filename="road_first_envelope_template.json",
                tags=["默认模板", "公路", "第一信封"],
                template_json={"project_name": None, "page_count": 10},
            ),
        ]
    )
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    summary = template_service.seed_template_from_json(template_path)

    assert summary["id"] == 9
    assert summary["seeded"] is True
    assert summary["tags"] == ["默认模板", "公路", "第一信封"]
    insert_statement, params = cursor.statements[1]
    assert "INSERT INTO bid_templates" in insert_statement
    assert params[0] == "默认公路第一信封模板"


def test_seed_template_from_json_returns_existing_without_duplicate(
    monkeypatch, tmp_path
) -> None:
    template_path = tmp_path / "default_template.json"
    template_path.write_text(
        BidTemplate(
            template_name="默认公路第一信封模板",
            source_file="road_first_envelope_template.json",
            page_count=10,
            envelope_type="第一信封",
        ).model_dump_json(),
        encoding="utf-8",
    )
    cursor = FakeCursor(
        [
            _template_row(
                id=9,
                name="默认公路第一信封模板",
                source_filename="road_first_envelope_template.json",
            )
        ]
    )
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    summary = template_service.seed_template_from_json(template_path)

    assert summary["id"] == 9
    assert summary["seeded"] is False
    assert len(cursor.statements) == 1


def test_list_templates_returns_summaries(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            _template_row(id=2, name="房建模板", project_type="房屋建筑"),
            _template_row(id=1, name="公路模板", project_type="公路工程"),
        ]
    )
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    templates = template_service.list_templates()

    assert [t["id"] for t in templates] == [2, 1]
    assert templates[0]["name"] == "房建模板"


def test_update_template_renames_and_tags(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            _template_row(),  # current row fetched first
            _template_row(name="公路模板(已改名)", tags=["公路", "高速"]),
        ]
    )
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    summary = template_service.update_template(1, name="公路模板(已改名)", tags=["公路", "高速"])

    assert summary["name"] == "公路模板(已改名)"
    assert summary["tags"] == ["公路", "高速"]


def test_delete_template_missing_raises(monkeypatch) -> None:
    cursor = FakeCursor([])
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    with pytest.raises(template_service.TemplateNotFoundError):
        template_service.delete_template(99)


def test_recommend_templates_ranks_matching_type_first(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            _template_row(
                id=2, name="房建模板", project_type="房屋建筑", specialty="建筑", tags=["房建"]
            ),
            _template_row(
                id=1, name="公路模板", project_type="公路工程", specialty="道路", tags=["公路"]
            ),
        ]
    )
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    recommendations = template_service.recommend_templates(
        project_type="公路工程", specialty="道路"
    )

    assert recommendations[0]["template"]["id"] == 1
    assert recommendations[0]["match_score"] > recommendations[1]["match_score"]
    assert any("项目类型匹配" in reason for reason in recommendations[0]["match_reasons"])


def test_bid_template_for_project_returns_template(monkeypatch) -> None:
    template_json = BidTemplate(
        template_name="公路模板",
        source_file="road.pdf",
        page_count=120,
    ).model_dump(mode="json")
    cursor = FakeCursor([{"template_json": template_json}])
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    template = template_service.bid_template_for_project(7)

    assert template is not None
    assert template.template_name == "公路模板"


def test_bid_template_for_project_none_when_unset(monkeypatch) -> None:
    cursor = FakeCursor([])
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    assert template_service.bid_template_for_project(7) is None


def test_set_project_template_validates_and_updates(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            _template_row(id=3),  # template existence check
            {"id": 7, "template_id": 3},  # project update RETURNING
        ]
    )
    monkeypatch.setattr(template_service, "_connect", lambda: FakeConnection(cursor))

    result = template_service.set_project_template(7, 3)

    assert result == {"project_id": 7, "template_id": 3}
