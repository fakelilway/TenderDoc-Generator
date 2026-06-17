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
