"use client";

import { ArrowDown, ArrowUp, ImagePlus, Plus, Save, Trash2 } from "lucide-react";
import type {
  BidDocumentOutlineSection,
  BidOutlineSection,
  ManualImageSlot
} from "@/lib/types";

type Props = {
  outline: BidOutlineSection[];
  documentOutline?: BidDocumentOutlineSection[];
  busy: boolean;
  onChange: (outline: BidOutlineSection[]) => void;
  onBuild: () => void;
  onSave: () => void;
};

export function OutlineEditor({
  outline,
  documentOutline = [],
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

  function addImageSlot(index: number) {
    const section = outline[index];
    const nextSlots: ManualImageSlot[] = [
      ...(section.manual_image_slots ?? []),
      {
        title: `${section.title || "本章节"}插图`,
        placement: section.title,
        description: ""
      }
    ];
    update(index, { manual_image_slots: nextSlots });
  }

  function updateImageSlot(
    sectionIndex: number,
    slotIndex: number,
    patch: Partial<ManualImageSlot>
  ) {
    const slots = outline[sectionIndex].manual_image_slots ?? [];
    update(sectionIndex, {
      manual_image_slots: slots.map((slot, index) =>
        index === slotIndex ? { ...slot, ...patch } : slot
      )
    });
  }

  function removeImageSlot(sectionIndex: number, slotIndex: number) {
    const slots = outline[sectionIndex].manual_image_slots ?? [];
    update(sectionIndex, {
      manual_image_slots: slots.filter((_slot, index) => index !== slotIndex)
    });
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
      {documentOutline.length > 0 ? (
        <div className="mt-3 rounded-md border border-line bg-field p-3">
          <div className="text-xs font-semibold text-ink">完整标书目录</div>
          <div className="mt-2 space-y-2">
            {documentOutline.map((section, index) => (
              <div key={`${section.title}-${index}`} className="text-xs text-muted">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-white px-2 py-0.5 font-medium text-ink">
                    {section.volume}
                  </span>
                  <span className="text-ink">{section.title}</span>
                  {!section.required ? <span>可选/需另行确认</span> : null}
                </div>
                {section.children.length > 0 ? (
                  <div className="mt-1 grid gap-1 pl-3">
                    {section.children.slice(0, 8).map((child) => (
                      <div key={child.title}>- {child.title}</div>
                    ))}
                    {section.children.length > 8 ? (
                      <div>还有 {section.children.length - 8} 个子章节</div>
                    ) : null}
                  </div>
                ) : null}
                {section.focus_points.length > 0 ? (
                  <div className="mt-1 pl-3">{section.focus_points[0]}</div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mt-3 space-y-2">
        {outline.map((section, index) => (
          // The title is editable, so it must not be part of the key:
          // typing would remount the input and drop focus on every keystroke.
          <div key={index} className="rounded-md border border-line bg-field p-3">
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
            <div className="mt-3 rounded-md border border-dashed border-line bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-xs font-semibold text-ink">手动插图位</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted">
                    需要人工配图的施工图、现场图、流程图可先在这里预留位置。
                  </div>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-line bg-white px-2 text-xs font-medium text-ink hover:bg-field disabled:text-muted"
                  onClick={() => addImageSlot(index)}
                >
                  <ImagePlus className="h-4 w-4" />
                  添加
                </button>
              </div>
              {(section.manual_image_slots ?? []).length > 0 ? (
                <div className="mt-3 space-y-2">
                  {(section.manual_image_slots ?? []).map((slot, slotIndex) => (
                    <div
                      key={slotIndex}
                      className="grid gap-2 rounded-md border border-line bg-field p-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="shrink-0 text-[11px] font-semibold text-muted">
                          图 {slotIndex + 1}
                        </span>
                        <input
                          value={slot.title}
                          disabled={busy}
                          placeholder="图片标题，例如：施工总平面布置图"
                          onChange={(event) =>
                            updateImageSlot(index, slotIndex, {
                              title: event.target.value
                            })
                          }
                          className="h-8 min-w-0 flex-1 rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand"
                        />
                        <button
                          type="button"
                          disabled={busy}
                          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line bg-white text-danger hover:bg-field disabled:text-muted"
                          onClick={() => removeImageSlot(index, slotIndex)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                      <input
                        value={slot.placement ?? ""}
                        disabled={busy}
                        placeholder="插入位置，例如：第一章 第二节 施工准备"
                        onChange={(event) =>
                          updateImageSlot(index, slotIndex, {
                            placement: event.target.value
                          })
                        }
                        className="h-8 rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand"
                      />
                      <textarea
                        value={slot.description ?? ""}
                        disabled={busy}
                        placeholder="图片说明，例如：此处人工插入交通导改示意图"
                        onChange={(event) =>
                          updateImageSlot(index, slotIndex, {
                            description: event.target.value
                          })
                        }
                        className="min-h-14 resize-y rounded-md border border-line bg-white px-2 py-1.5 text-xs text-ink outline-none focus:border-brand"
                      />
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
