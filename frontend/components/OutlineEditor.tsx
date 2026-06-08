"use client";

import { ArrowDown, ArrowUp, Plus, Save, Trash2 } from "lucide-react";
import type { BidOutlineSection } from "@/lib/types";

type Props = {
  outline: BidOutlineSection[];
  busy: boolean;
  onChange: (outline: BidOutlineSection[]) => void;
  onBuild: () => void;
  onSave: () => void;
};

export function OutlineEditor({
  outline,
  busy,
  onChange,
  onBuild,
  onSave
}: Props) {
  function update(index: number, patch: Partial<BidOutlineSection>) {
    onChange(
      outline.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item
      )
    );
  }

  function move(index: number, direction: -1 | 1) {
    const next = [...outline];
    const target = index + direction;
    if (target < 0 || target >= next.length) {
      return;
    }
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  function remove(index: number) {
    onChange(outline.filter((_item, itemIndex) => itemIndex !== index));
  }

  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">大纲编辑</h2>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            className="inline-flex h-8 items-center gap-2 rounded-md border border-line bg-white px-3 text-xs font-medium text-ink hover:bg-field disabled:text-muted"
            onClick={onBuild}
          >
            <Plus className="h-4 w-4" />
            生成
          </button>
          <button
            type="button"
            disabled={busy || outline.length === 0}
            className="inline-flex h-8 items-center gap-2 rounded-md bg-ok px-3 text-xs font-semibold text-white hover:bg-green-700 disabled:bg-green-300"
            onClick={onSave}
          >
            <Save className="h-4 w-4" />
            确认
          </button>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {outline.map((section, index) => (
          <div key={`${section.title}-${index}`} className="rounded-md border border-line bg-field p-3">
            <div className="flex gap-2">
              <input
                value={section.title}
                disabled={busy}
                onChange={(event) => update(index, { title: event.target.value })}
                className="h-9 min-w-0 flex-1 rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand"
              />
              <button
                type="button"
                className="grid h-9 w-9 place-items-center rounded-md border border-line bg-white text-ink hover:bg-field"
                onClick={() => move(index, -1)}
              >
                <ArrowUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="grid h-9 w-9 place-items-center rounded-md border border-line bg-white text-ink hover:bg-field"
                onClick={() => move(index, 1)}
              >
                <ArrowDown className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="grid h-9 w-9 place-items-center rounded-md border border-line bg-white text-danger hover:bg-field"
                onClick={() => remove(index)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            <textarea
              value={section.focus_points.join("\n")}
              disabled={busy}
              onChange={(event) =>
                update(index, {
                  focus_points: event.target.value
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean)
                })
              }
              className="mt-2 min-h-16 w-full resize-y rounded-md border border-line bg-white px-3 py-2 text-xs text-ink outline-none focus:border-brand"
            />
          </div>
        ))}
      </div>
    </section>
  );
}
