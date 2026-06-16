export type MarkdownBlock =
  | {
      type: "heading";
      lineNumber: number;
      level: number;
      text: string;
    }
  | {
      type: "paragraph" | "list";
      lineNumber: number;
      text: string;
    }
  | {
      type: "table";
      lineNumber: number;
      rows: string[][];
    };

export type MarkdownVolumeKey = "commercial" | "technical" | "pricing" | "notes";

export type MarkdownVolumeSlice = {
  key: MarkdownVolumeKey;
  markdown: string;
  // 0-based index of the slice's first line inside the combined doc; pass to
  // parseMarkdown(slice, lineOffset) so block lineNumbers stay absolute.
  lineOffset: number;
  startLine: number; // 1-based first line of the slice (inclusive)
  endLine: number; // 1-based last line of the slice (inclusive)
};

// Mirrors backend utils/docx_exporter.VOLUME_MARKERS. The combined delivery
// markdown carries one HTML-comment marker per volume; splitting on them lets
// us show each卷 on its own preview tab while keeping absolute line numbers
// (so risk/strategy jump-to-line still lands on the right block).
const VOLUME_MARKER_RE =
  /^<!--\s*tdg:volume:(commercial|technical|pricing|notes)\s*-->$/;

export function splitCombinedMarkdownByVolume(
  combined: string
): Partial<Record<MarkdownVolumeKey, MarkdownVolumeSlice>> {
  const lines = combined.split(/\r?\n/);
  const marks: Array<{ key: MarkdownVolumeKey; idx: number }> = [];
  lines.forEach((raw, idx) => {
    const m = raw.trim().match(VOLUME_MARKER_RE);
    if (m) {
      marks.push({ key: m[1] as MarkdownVolumeKey, idx });
    }
  });

  const out: Partial<Record<MarkdownVolumeKey, MarkdownVolumeSlice>> = {};
  marks.forEach((mark, i) => {
    const start = mark.idx + 1; // content begins on the line after the marker
    const end = i + 1 < marks.length ? marks[i + 1].idx : lines.length; // exclusive
    if (end <= start) {
      return;
    }
    out[mark.key] = {
      key: mark.key,
      markdown: lines.slice(start, end).join("\n"),
      lineOffset: start,
      startLine: start + 1,
      endLine: end // last content line is 0-based end-1 → 1-based end
    };
  });
  return out;
}

// Build the 标书预览 sub-tab slices (技术 / 商务) from the combined draft markdown.
// Normal generated drafts carry tdg:volume markers → clean per-volume slices with
// ABSOLUTE line numbers (jump-to-line stays accurate). If a draft has NO markers
// (legacy, or a human deleted the marker comments while editing), we cannot split
// by volume, so we fall back to the WHOLE combined doc at offset 0 under the
// technical tab — identical to the pre-split single-preview behavior, which keeps
// jump-to-line aligned to the combined-doc line numbers and reflects live edits
// (never reaches for stale backend-split content).
export function buildVolumePreviewSlices(
  combined: string
): Partial<Record<"commercial" | "technical", MarkdownVolumeSlice>> {
  const sliced = splitCombinedMarkdownByVolume(combined);
  const out: Partial<Record<"commercial" | "technical", MarkdownVolumeSlice>> =
    {};
  for (const key of ["technical", "commercial"] as const) {
    const slice = sliced[key];
    if (slice && slice.markdown.trim()) {
      out[key] = slice;
    }
  }
  if (!out.technical && !out.commercial && combined.trim()) {
    out.technical = {
      key: "technical",
      markdown: combined,
      lineOffset: 0,
      startLine: 1,
      endLine: combined.split(/\r?\n/).length
    };
  }
  return out;
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isSeparatorRow(row: string[]) {
  return row.every((cell) => /^:?-{3,}:?$/.test(cell));
}

// ``lineOffset`` lets a caller render a *slice* of a larger document while
// keeping each block's ``lineNumber`` aligned to the original (e.g. one volume
// sliced out of the combined delivery markdown), so jump-to-line / activeLine
// scrolling still targets the right anchor. Defaults to 0 (no offset).
export function parseMarkdown(
  markdown: string,
  lineOffset = 0
): MarkdownBlock[] {
  const lines = markdown.split(/\r?\n/);
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const raw = lines[index];
    const line = raw.trim();
    const lineNumber = index + 1 + lineOffset;

    if (!line) {
      index += 1;
      continue;
    }

    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        const row = splitTableRow(lines[index]);
        if (!isSeparatorRow(row)) {
          rows.push(row);
        }
        index += 1;
      }
      blocks.push({ type: "table", lineNumber, rows });
      continue;
    }

    if (line.startsWith("#")) {
      const hashes = line.match(/^#+/)?.[0] ?? "#";
      blocks.push({
        type: "heading",
        lineNumber,
        level: Math.min(hashes.length, 3),
        text: line.replace(/^#+/, "").trim()
      });
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line) || /^\d+[.、]\s+/.test(line)) {
      blocks.push({
        type: "list",
        lineNumber,
        text: line.replace(/^[-*]\s+/, "").replace(/^\d+[.、]\s+/, "")
      });
      index += 1;
      continue;
    }

    blocks.push({ type: "paragraph", lineNumber, text: raw.trim() });
    index += 1;
  }

  return blocks;
}
