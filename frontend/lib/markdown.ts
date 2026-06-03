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

export function parseMarkdown(markdown: string): MarkdownBlock[] {
  const lines = markdown.split(/\r?\n/);
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const raw = lines[index];
    const line = raw.trim();
    const lineNumber = index + 1;

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
