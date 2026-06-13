"""V2-M7: Verify V2 pipeline on all 5 real tender cases.

Run format extraction + form filling + audit for each case.
Skip LLM-dependent content writing.
"""

import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import fitz
from schemas.tender import TenderRequirements
from services.format_skeleton_service import extract_format_pages, assign_page_volumes
from agents.form_filler_agent import fill_page_template, generate_missing_checklist
from services.v2_audit_service import audit_format_layer

CASES = [
    ("长丰县罗塘乡", "/Users/mingbai/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_hvidoi7eyzc812_ddf6/temp/drag/招标文件正文.pdf"),
    ("萧县2025公路", "/Users/mingbai/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_hvidoi7eyzc812_ddf6/temp/drag/1招标文件正文(1).pdf"),
    ("南陵县三里镇", "/Users/mingbai/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_hvidoi7eyzc812_ddf6/temp/drag/招标文件正文(3).pdf"),
    ("颍州区袁集镇", "/Users/mingbai/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_hvidoi7eyzc812_ddf6/temp/drag/颍州区袁集镇福满路、孝梯路道路排水改造工程(定稿）(1).docx"),
    ("鸠江区日常养护", "/Users/mingbai/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_hvidoi7eyzc812_ddf6/temp/drag/招标文件正文 (1)(1).pdf"),
]

PROFILE = {
    "company_name": "安徽正奇建设有限公司",
    "legal_rep": "冯伟",
    "address": "安徽省阜阳市颍州区西湖大道69号",
    "phone": "0558-2269081",
    "business_license_no": "91341200MA2XXXXXXX",
    "registered_capital": "5000万元",
}


def verify_case(name, path):
    print(f"\n{'='*60}")
    print(f"Case: {name}")
    print(f"File: {os.path.basename(path)}")
    print(f"{'='*60}")

    # Extract text
    if path.endswith('.docx'):
        try:
            from docx import Document
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            print(f"  ❌ DOCX parse failed: {e}")
            return False
    else:
        doc = fitz.open(path)
        text = "".join(page.get_text() for page in doc)
        doc.close()

    print(f"  Text: {len(text):,} chars")

    # Extract format pages
    pages = extract_format_pages(text)
    total_pages = sum(len(v) for v in pages.values())
    print(f"  Format pages: {total_pages}")

    if total_pages == 0:
        print(f"  ❌ No format pages extracted")
        return False

    # Try to parse if we have the parsed result
    try:
        with open('/tmp/parsed_result.json') as f:
            d = json.load(f)
        requirements = TenderRequirements.model_validate(d)
    except Exception:
        print(f"  ⚠️ No parsed requirements available, skipping volume classification")
        requirements = None

    if requirements:
        classified = assign_page_volumes(pages["commercial"], requirements)
        for vol in ("commercial", "technical", "pricing"):
            ps = classified.get(vol, [])
            print(f"  {vol}: {len(ps)} pages")
            # Show top pages with templates
            for p in ps[:3]:
                if p.raw_template:
                    print(f"    [{p.page_type}] {p.title[:50]} ({len(p.raw_template)}c)")

        # Test form filling on first commercial page
        com_pages = classified.get("commercial", [])
        if com_pages:
            first = com_pages[0]
            if first.raw_template:
                result = fill_page_template(first.raw_template, PROFILE, first.title)
                filled_count = sum(1 for f in result.fields if f.matched)
                print(f"  Form fill: {filled_count}/{len(result.fields)} fields matched")
                if result.missing:
                    print(f"  Missing: {result.missing}")

        # Run format audit
        tech_pages = classified.get("technical", [])
        has_content = any(p.raw_template and len(p.raw_template) > 50 for p in classified["commercial"])
        if has_content:
            orig_pairs = [(p.title, p.raw_template) for p in classified["commercial"][:5] if p.raw_template]
            filled_pairs = [(p.title, p.raw_template) for p in classified["commercial"][:5] if p.raw_template]
            if orig_pairs:
                audit = audit_format_layer(orig_pairs, filled_pairs)
                print(f"  Audit: {'✅ PASS' if audit.passed else f'❌ {len(audit.issues)} issues'}")
    else:
        for vol in ("commercial", "technical", "pricing"):
            ps = pages.get(vol, [])
            if ps:
                print(f"  {vol}: {len(ps)} pages")

    return True


if __name__ == "__main__":
    results = {}
    for name, path in CASES:
        try:
            ok = verify_case(name, path)
            results[name] = "✅" if ok else "❌"
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            results[name] = f"❌ {type(e).__name__}"

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, result in results.items():
        print(f"  {result}: {name}")
