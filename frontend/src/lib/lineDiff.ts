export type DiffLineType = "equal" | "add" | "remove";

export type DiffLine = {
  type: DiffLineType;
  text: string;
  oldLine: number | null;
  newLine: number | null;
};

/** Split into lines without a trailing empty line from a final newline. */
export function splitLines(text: string): string[] {
  if (text.length === 0) return [];
  const normalized = text.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n");
  if (parts.length > 0 && parts[parts.length - 1] === "") {
    parts.pop();
  }
  return parts;
}

/**
 * Line-level LCS diff. Good enough for skill markdown files (typically small).
 */
export function computeLineDiff(oldText: string, newText: string): DiffLine[] {
  const a = splitLines(oldText);
  const b = splitLines(newText);
  const n = a.length;
  const m = b.length;

  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows: DiffLine[] = [];
  let i = 0;
  let j = 0;
  let oldLine = 1;
  let newLine = 1;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: "equal", text: a[i], oldLine, newLine });
      i++;
      j++;
      oldLine++;
      newLine++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "remove", text: a[i], oldLine, newLine: null });
      i++;
      oldLine++;
    } else {
      rows.push({ type: "add", text: b[j], oldLine: null, newLine });
      j++;
      newLine++;
    }
  }
  while (i < n) {
    rows.push({ type: "remove", text: a[i], oldLine, newLine: null });
    i++;
    oldLine++;
  }
  while (j < m) {
    rows.push({ type: "add", text: b[j], oldLine: null, newLine });
    j++;
    newLine++;
  }
  return rows;
}

export type SplitRow = {
  left: DiffLine | null;
  right: DiffLine | null;
};

/** Pair remove/add into side-by-side rows; equals span both panes. */
export function toSplitRows(lines: DiffLine[]): SplitRow[] {
  const out: SplitRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.type === "equal") {
      out.push({ left: line, right: line });
      i++;
      continue;
    }
    const removes: DiffLine[] = [];
    const adds: DiffLine[] = [];
    while (i < lines.length && lines[i].type === "remove") {
      removes.push(lines[i]);
      i++;
    }
    while (i < lines.length && lines[i].type === "add") {
      adds.push(lines[i]);
      i++;
    }
    const max = Math.max(removes.length, adds.length);
    for (let k = 0; k < max; k++) {
      out.push({
        left: removes[k] ?? null,
        right: adds[k] ?? null,
      });
    }
  }
  return out;
}
