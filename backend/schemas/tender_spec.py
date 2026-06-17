"""投标规格 + 逐空核对的结构化模型。

核心改造:系统从"填表机"升级成"逐空核对引擎"。先把招标读成结构化「投标规格」
(TenderSpec),再对投标卷里每个要填的空走"找要求→核对我方→符合才填/不符合告警",
产出「逐空核对报告」(ConformanceReport)。本文件是这条闭环的数据结构。
"""

from __future__ import annotations

from pydantic import BaseModel


class ClauseItem(BaseModel):
    """前附表 / 投标函附录里的一行:条款号 → 内容。"""

    clause_no: str = ""  # 如 1.3.2 / 11.5（3）
    name: str = ""  # 如 计划工期 / 缺陷责任期
    content: str = ""  # 如 90日历天 / 自实际交工日期起2年


class CertRequirement(BaseModel):
    """招标要求的一项资质/证件。"""

    cert_type: str = ""  # 企业资质 / 安全生产许可证 / 营业执照
    required_value: str = ""  # 公路工程施工总承包一级
    source: str = ""  # 出处,如 资格审查附录1


class PerformanceRequirement(BaseModel):
    """招标对类似业绩的要求。"""

    since: str = ""  # 时间下限,如 "2022年以来" / "近3年"
    category: str = ""  # 同类:公路工程 / 市政
    min_amount_wan: float = 0.0  # 单项中标金额下限(万元)
    min_count: int = 0  # 需几个
    time_basis: str = "交工"  # 时间以"交工"为准


class TenderSpec(BaseModel):
    """读懂招标的结构化成果(阶段一,LLM 抽 + 人工核)。

    仅含闭环切片需要的字段;后续按需扩(信誉/评分细则/承诺要求/各表附件)。
    """

    instructions_table: list[ClauseItem] = []  # 投标人须知前附表
    contract_appendix: list[ClauseItem] = []  # 投标函附录(合同参数)
    cert_requirements: list[CertRequirement] = []  # 资格审查的证件/资质要求
    performance_requirement: PerformanceRequirement | None = None
    # 供"三处一致性"核对的关键值(从前附表/附录抽出)
    duration: str = ""  # 工期
    bid_validity: str = ""  # 投标有效期
    # 各表"该附什么"(表名 → 附件清单)
    attachment_requirements: dict[str, list[str]] = {}


class ReviewCriterion(BaseModel):
    """招标第三章评标办法里的一条「评审因素 × 评审标准」(形式/响应性/资格/详细评审)。

    这是"以招标真实标准审标书"的核心:招标明文写了哪些评审因素、对应什么标准、不符合是否否决。
    """

    category: str = ""  # 形式评审 / 响应性评审 / 资格评审 / 详细评审
    clause_no: str = ""  # 真实条款号,如 2.1.1（3）
    factor: str = ""  # 评审因素,如 投标文件签字盖章 / 投标报价
    standard: str = ""  # 评审标准原文(照抄招标)
    is_reject: bool = False  # 不符合是否否决(废标级)


class ScoreItem(BaseModel):
    """评分因素 × 分值 × 评分细则(技术/商务评分)。"""

    clause_no: str = ""
    factor: str = ""  # 评分因素,如 施工组织设计-总体布置 / 类似业绩 / 信誉
    max_score: float = 0.0  # 该项满分/权重
    rule: str = ""  # 评分细则原文(基本分+加分区间等)


class RejectionRule(BaseModel):
    """否决投标(废标)情形原文。"""

    clause_no: str = ""
    rule: str = ""  # 否决情形原文,如 串通投标、低于成本、修正价不接受等


class TenderReviewMethod(BaseModel):
    """招标第三章「评标办法」的结构化结果——审查标准的本体(取代写死的通用规则)。"""

    method_name: str = ""  # 评标办法名称,如 技术评分最低标价法
    total_score: float = 0.0  # 总分(如 100)
    criteria: list[ReviewCriterion] = []  # 形式/响应性/资格评审标准
    score_items: list[ScoreItem] = []  # 评分因素与细则
    rejection_rules: list[RejectionRule] = []  # 否决投标情形

    def is_empty(self) -> bool:
        return not (self.criteria or self.score_items or self.rejection_rules)


class FillRequirement(BaseModel):
    """一个空的核对结果。"""

    field: str  # 空名:工期 / 企业资质 / 项目经理 / 投标人基本情况表附件
    source: str = ""  # 出处(哪章哪条)
    required: str = ""  # 招标要求
    our_value: str = ""  # 我方资料
    # 符合 / 不符合 / 缺料 / 待人工 / 一致 / 不一致
    status: str = "待人工"
    # 填 / 告警 / 留空
    action: str = "告警"
    note: str = ""


class ConformanceReport(BaseModel):
    """逐空核对报告:出标时一并产出,告诉用户哪些填了、哪些预警、哪些待人工。"""

    project_id: int
    items: list[FillRequirement] = []

    @property
    def warnings(self) -> list[FillRequirement]:
        return [i for i in self.items if i.status in ("不符合", "缺料", "不一致")]

    @property
    def pending_manual(self) -> list[FillRequirement]:
        return [i for i in self.items if i.status == "待人工"]

    @property
    def has_blocking(self) -> bool:
        # 资质/项目经理不达标这类是废标级
        return any(i.status == "不符合" for i in self.items)


class ConformanceReportResponse(BaseModel):
    project_id: int
    items: list[FillRequirement]
    has_blocking: bool = False
    warning_count: int = 0
    pending_count: int = 0
