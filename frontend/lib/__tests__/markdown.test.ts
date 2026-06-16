import { describe, expect, it } from "vitest";

import {
  buildVolumePreviewSlices,
  parseMarkdown,
  splitCombinedMarkdownByVolume
} from "../markdown";

// 模拟后端 combine_delivery_volumes 的合并稿:标题 + 每卷一个 tdg:volume 标记。
// 行号(1 起):1 标题、3 商务标记、5 商务标题、7 商务正文、9 技术标记、
// 11 技术标题、13 施工组织设计、15 技术正文。
const combined = [
  "# 测试项目", // 1
  "", // 2
  "<!-- tdg:volume:commercial -->", // 3
  "", // 4
  "## 商务文件", // 5
  "", // 6
  "资格响应说明。", // 7
  "", // 8
  "<!-- tdg:volume:technical -->", // 9
  "", // 10
  "## 技术文件", // 11
  "", // 12
  "### 施工组织设计", // 13
  "", // 14
  "施工部署正文。" // 15
].join("\n");

describe("splitCombinedMarkdownByVolume", () => {
  it("把合并稿切成技术/商务两卷,并剥掉标记、标题、跨卷内容", () => {
    const slices = splitCombinedMarkdownByVolume(combined);

    expect(slices.commercial).toBeTruthy();
    expect(slices.technical).toBeTruthy();

    expect(slices.commercial!.markdown).toContain("商务文件");
    expect(slices.commercial!.markdown).toContain("资格响应说明");
    expect(slices.commercial!.markdown).not.toContain("技术文件");
    expect(slices.commercial!.markdown).not.toContain("tdg:volume");
    expect(slices.commercial!.markdown).not.toContain("测试项目");

    expect(slices.technical!.markdown).toContain("施工组织设计");
    expect(slices.technical!.markdown).toContain("施工部署正文");
    expect(slices.technical!.markdown).not.toContain("商务文件");
    expect(slices.technical!.markdown).not.toContain("tdg:volume");
  });

  it("报告的行区间覆盖该卷正文行(供跳转时自动切卷)", () => {
    const slices = splitCombinedMarkdownByVolume(combined);
    expect(slices.commercial!.startLine).toBe(4);
    expect(slices.commercial!.endLine).toBe(8);
    expect(slices.technical!.startLine).toBe(10);
    expect(slices.technical!.endLine).toBe(15);
  });

  it("没有分卷标记时返回空(组件回退到后端分卷预览)", () => {
    expect(splitCombinedMarkdownByVolume("# 标题\n\n正文一段。")).toEqual({});
  });
});

describe("parseMarkdown lineOffset(跳到正文行需保持绝对行号)", () => {
  it("按 lineOffset 解析切片时,block 行号仍是合并稿里的绝对行号", () => {
    const slices = splitCombinedMarkdownByVolume(combined);
    const tech = slices.technical!;
    const blocks = parseMarkdown(tech.markdown, tech.lineOffset);

    const heading = blocks.find(
      (b) => b.type === "heading" && b.text === "施工组织设计"
    );
    const body = blocks.find(
      (b) => b.type === "paragraph" && b.text === "施工部署正文。"
    );

    // 这两行在合并稿里的绝对行号是 13、15 —— 审查/评分面板按合并稿行号跳转,
    // 切片渲染后必须命中同一 #line-N 锚点,否则高亮会落空。
    expect(heading?.lineNumber).toBe(13);
    expect(body?.lineNumber).toBe(15);

    // 跳转行落在该卷区间内 → 自动切到技术卷
    expect(heading!.lineNumber).toBeGreaterThanOrEqual(tech.startLine);
    expect(heading!.lineNumber).toBeLessThanOrEqual(tech.endLine);
  });

  it("不传 lineOffset 时仍是 1 起行号(向后兼容)", () => {
    const blocks = parseMarkdown("# 顶层标题");
    expect(blocks[0]?.lineNumber).toBe(1);
  });
});

describe("buildVolumePreviewSlices(标书预览分卷源)", () => {
  it("有标记:切出技术/商务两卷,行号绝对", () => {
    const slices = buildVolumePreviewSlices(combined);
    expect(slices.technical?.markdown).toContain("施工组织设计");
    expect(slices.commercial?.markdown).toContain("资格响应说明");
    expect(slices.technical?.lineOffset).toBe(9);
    expect(slices.commercial?.lineOffset).toBe(3);
  });

  it("无标记(老稿/手改稿删了标记):退回整篇合并稿单视图(offset 0),不碰后端分卷", () => {
    // 关键回归:必须保持与拆分前一致 —— 行号绝对、跳到正文行仍准、实时反映编辑。
    const plain = "# 标书全文\n\n## 第一章\n\n正文一。\n\n## 第二章\n\n正文二。";
    const slices = buildVolumePreviewSlices(plain);
    expect(slices.technical).toBeTruthy();
    expect(slices.commercial).toBeUndefined();
    expect(slices.technical!.markdown).toBe(plain); // 整篇,未被后端重切
    expect(slices.technical!.lineOffset).toBe(0); // offset 0 → block 行号即合并稿绝对行号
    expect(slices.technical!.startLine).toBe(1);
    expect(slices.technical!.endLine).toBe(plain.split("\n").length);

    // 任一审查跳转行都落在该单视图区间 → 自动切到技术卷且锚点存在
    const blocks = parseMarkdown(
      slices.technical!.markdown,
      slices.technical!.lineOffset
    );
    const ch2 = blocks.find((b) => b.type === "heading" && b.text === "第二章");
    expect(ch2?.lineNumber).toBe(7); // 绝对行号
  });

  it("空稿:返回空", () => {
    expect(buildVolumePreviewSlices("   ")).toEqual({});
  });
});
