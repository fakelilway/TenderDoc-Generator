"use client";

import { memo, useEffect, useMemo } from "react";
import { FileText } from "lucide-react";
import { parseMarkdown } from "@/lib/markdown";
import type { MarkdownBlock } from "@/lib/markdown";

// Memoized per block so toggling the active line only re-renders the two
// affected blocks instead of the whole document.
const PreviewBlock = memo(function PreviewBlock({
  block,
  active
}: {
  block: MarkdownBlock;
  active: boolean;
}) {
  const baseClass = [
    "scroll-mt-24 rounded-md border-l-4 px-3 py-2",
    active ? "border-danger bg-orange-50" : "border-transparent"
  ].join(" ");

  if (block.type === "heading") {
    const size =
      block.level === 1
        ? "text-2xl"
        : block.level === 2
          ? "text-xl"
          : "text-base";
    return (
      <h3
        id={`line-${block.lineNumber}`}
        className={`${baseClass} ${size} font-semibold text-ink`}
      >
        {block.text}
      </h3>
    );
  }

  if (block.type === "list") {
    return (
      <p
        id={`line-${block.lineNumber}`}
        className={`${baseClass} text-sm leading-7 text-ink`}
      >
        <span className="mr-2 text-muted">-</span>
        {block.text}
      </p>
    );
  }

  if (block.type === "table") {
    return (
      <div
        id={`line-${block.lineNumber}`}
        className={`${baseClass} overflow-x-auto`}
      >
        <table className="w-full border-collapse text-sm">
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${block.lineNumber}-${rowIndex}`}>
                {row.map((cell, cellIndex) => {
                  const Tag = rowIndex === 0 ? "th" : "td";
                  return (
                    <Tag
                      key={cellIndex}
                      className="border border-line px-3 py-2 text-left align-top"
                    >
                      {cell}
                    </Tag>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <p
      id={`line-${block.lineNumber}`}
      className={`${baseClass} text-sm leading-7 text-ink`}
    >
      {block.text}
    </p>
  );
});

export const MarkdownPreview = memo(function MarkdownPreview({
  markdown,
  activeLine
}: {
  markdown: string;
  activeLine: number | null;
}) {
  // Re-parse only when the markdown changes, not on every poll tick or
  // activeLine update.
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown]);

  useEffect(() => {
    if (!activeLine) {
      return;
    }
    document
      .getElementById(`line-${activeLine}`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeLine]);

  return (
    <section className="ios-panel flex min-h-[560px] flex-col rounded-[26px] border">
      <div className="flex h-14 items-center justify-between border-b border-black/[0.06] px-4">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#007aff]/10 text-[#007aff]">
            <FileText className="h-4 w-4" />
          </span>
          <h2 className="text-sm font-semibold text-[#1d1d1f]">标书预览</h2>
        </div>
        <span className="rounded-full bg-black/[0.05] px-2.5 py-1 text-xs text-[#6e6e73]">
          {blocks.length} 段
        </span>
      </div>

      <div className="flex-1 overflow-auto px-6 py-5">
        {blocks.length === 0 ? (
          <div className="grid h-full min-h-96 place-items-center rounded-[22px] border border-dashed border-black/[0.08] bg-white/54 text-sm text-[#8e8e93]">
            等待生成稿
          </div>
        ) : (
          <article className="mx-auto max-w-4xl space-y-3">
            {blocks.map((block) => (
              <PreviewBlock
                key={block.lineNumber}
                block={block}
                active={block.lineNumber === activeLine}
              />
            ))}
          </article>
        )}
      </div>
    </section>
  );
});
