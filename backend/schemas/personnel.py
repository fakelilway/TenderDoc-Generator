"""公司人员名册(项目经理/总工/安全员/八大员等候选)的结构化模型。

公司有上百名建造师/工程师,投标时按招标的项目经理要求(建造师等级+专业+安全B证)从
名册里选派,而不是 company_profile 里写死的单个项目经理。数据源是公司的人员证书台账
xlsx(建造师/三类人员安全证/职称/八大员/特种工/养护工,按身份证号串联同一人)。
"""

from __future__ import annotations

from pydantic import BaseModel


class BuilderCert(BaseModel):
    """一张建造师证(一人可有多专业/多等级)。"""

    level: str = ""  # 一级建造师 / 二级建造师
    specialty: str = ""  # 公路工程 / 市政公用工程 / ...
    cert_no: str = ""  # 证书编号
    valid_to: str = ""  # 有效期


class PersonnelMember(BaseModel):
    """名册里的一个人,聚合其全部证书。身份证号是同一人跨表的连接键。"""

    name: str
    id_number: str = ""  # 身份证号(主连接键)
    builder_certs: list[BuilderCert] = []  # 建造师证(=项目经理候选资格)
    safety_cert_classes: list[str] = []  # 安全考核证类别子集:A(企业负责人)/B(项目负责人)/C(专职安全员)
    safety_cert_no: str = ""
    title: str = ""  # 职称:高级工程师/工程师/助理工程师
    title_specialty: str = ""  # 职称专业
    eight_roles: list[str] = []  # 八大员证书类别(标准员/材料员/机械员…)
    special_works: list[str] = []  # 特种工工种
    source: str = "台账"  # 来源:台账 / 知识库 / 台账+知识库(知识库含历年,可能离职/过期)

    @property
    def is_pm_candidate(self) -> bool:
        """有建造师证即可作项目经理候选。"""
        return bool(self.builder_certs)

    @property
    def builder_specialties(self) -> list[str]:
        return sorted({c.specialty for c in self.builder_certs if c.specialty})

    @property
    def builder_levels(self) -> list[str]:
        return sorted({c.level for c in self.builder_certs if c.level})


class PMRequirement(BaseModel):
    """从招标资格条款里解析出的项目经理硬性要求(供推荐匹配)。"""

    builder_level: str = ""  # 一级建造师 / 二级建造师 / "" = 不限
    builder_specialty: str = ""  # 公路工程 / 市政公用工程 / "" = 不限
    requires_safety_b: bool = False  # 是否要求安全生产考核B证
    note: str = ""  # 原文摘录,供人工核对


class PMRecommendation(BaseModel):
    """一个被推荐的项目经理候选 + 匹配说明。"""

    member: PersonnelMember
    score: float
    matched: list[str] = []  # 命中点:如 ["等级达标:一级建造师", "专业匹配:公路工程"]
    gaps: list[str] = []  # 缺口:如 ["缺安全B证", "专业待核验"]


class PMRecommendationResponse(BaseModel):
    project_id: int
    requirement: PMRequirement
    recommendations: list[PMRecommendation]
    selected: PersonnelMember | None = None


class PMSelectionRequest(BaseModel):
    # None = 清空选派
    project_manager: PersonnelMember | None = None


class PMSelectionResponse(BaseModel):
    project_id: int
    selected: dict = {}  # {"project_manager": {...}} 或 {}
