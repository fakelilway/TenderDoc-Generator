from __future__ import annotations

from pydantic import BaseModel


class CompanyProfile(BaseModel):
    """投标人企业档案：生成标书时注入【投标人信息】并填写商务卷表格。

    所有字段都是字符串，留空表示未填写；生成时未填写的字段保持"________"。
    """

    company_name: str = ""
    credit_code: str = ""
    legal_representative: str = ""
    registered_capital: str = ""
    establish_date: str = ""
    registered_address: str = ""
    company_type: str = ""
    business_scope: str = ""
    qualification_grade: str = ""
    safety_license_no: str = ""
    contact_person: str = ""
    contact_phone: str = ""
    bank_name: str = ""
    bank_account: str = ""
    project_manager_name: str = ""
    project_manager_cert: str = ""


COMPANY_PROFILE_FIELD_LABELS: dict[str, str] = {
    "company_name": "公司名称",
    "credit_code": "统一社会信用代码",
    "legal_representative": "法定代表人",
    "registered_capital": "注册资本",
    "establish_date": "成立日期",
    "registered_address": "注册地址",
    "company_type": "公司类型",
    "business_scope": "经营范围",
    "qualification_grade": "资质等级",
    "safety_license_no": "安全生产许可证号",
    "contact_person": "联系人",
    "contact_phone": "联系电话",
    "bank_name": "开户银行",
    "bank_account": "银行账号",
    "project_manager_name": "拟派项目经理",
    "project_manager_cert": "项目经理建造师证号",
}


class CompanyProfileResponse(BaseModel):
    profile: CompanyProfile
    updated_at: str | None = None
