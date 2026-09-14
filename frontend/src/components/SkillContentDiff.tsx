import { useCallback, useRef, useState, type UIEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  computeLineDiff,
  toSplitRows,
  type DiffLine,
} from "@/lib/lineDiff";

type Props = {
  filename: string;
  currentContent: string | null | undefined;
  proposedContent: string;
  /** Prefer stacked layout cues (still allows unified/split toggle). */
  stacked?: boolean;
};

type ViewMode = "unified" | "split";

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function marker(type: DiffLine["type"]): string {
  if (type === "add") return "+";
  if (type === "remove") return "-";
  return " ";
}

function lineClass(type: DiffLine["type"]): string {
  if (type === "add") {
    return "border-l-2 border-success bg-status-ok/50 text-foreground";
  }
  if (type === "remove") {
    return "border-l-2 border-destructive bg-status-error/50 text-foreground";
  }
  return "border-l-2 border-transparent text-muted-foreground";
}

function markerClass(type: DiffLine["type"]): string {
  if (type === "add") return "select-none font-semibold text-success";
  if (type === "remove") return "select-none font-semibold text-destructive";
  return "select-none text-muted-foreground";
}

function DiffLineRow({
  line,
  showNewNumber = true,
}: {
  line: DiffLine;
  showNewNumber?: boolean;
}) {
  return (
    <div
      data-testid={`diff-line-${line.type}`}
      className={cn(
        "grid grid-cols-[2.5rem_1.25rem_minmax(0,1fr)] gap-x-1 px-2 py-0.5 leading-relaxed",
        lineClass(line.type),
      )}
    >
      <span className="select-none text-right text-[10px] text-muted-foreground tabular-nums">
        {showNewNumber
          ? (line.newLine ?? line.oldLine ?? "")
          : (line.oldLine ?? "")}
      </span>
      <span className={markerClass(line.type)} aria-hidden>
        {marker(line.type)}
      </span>
      <span className="min-w-0 whitespace-pre-wrap break-words">{line.text || " "}</span>
    </div>
  );
}

/** Current uploaded skill MD vs proposed full file, with line-level highlighting. */
export function SkillContentDiff({
  filename,
  currentContent,
  proposedContent,
  stacked = false,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [view, setView] = useState<ViewMode>("unified");
  const current = currentContent ?? "";
  const hasCurrent = current.trim().length > 0;
  const identical =
    hasCurrent && current.replace(/\r\n/g, "\n") === proposedContent.replace(/\r\n/g, "\n");
  const lines = computeLineDiff(hasCurrent ? current : "", proposedContent);
  const splitRows = toSplitRows(lines);

  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const syncing = useRef<"left" | "right" | null>(null);

  const onScroll = useCallback((side: "left" | "right") => {
    return (e: UIEvent<HTMLDivElement>) => {
      if (syncing.current && syncing.current !== side) return;
      syncing.current = side;
      const other = side === "left" ? rightRef.current : leftRef.current;
      if (other) {
        other.scrollTop = e.currentTarget.scrollTop;
        other.scrollLeft = e.currentTarget.scrollLeft;
      }
      requestAnimationFrame(() => {
        syncing.current = null;
      });
    };
  }, []);

  async function copyProposed() {
    try {
      await navigator.clipboard.writeText(proposedContent);
      setCopied(true);
      toast.success(`Copied ${filename}`);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      toast.error((e as Error).message || "Copy failed");
    }
  }

  return (
    <div className="space-y-2" data-testid="skill-content-diff">
      <div className="sticky top-0 z-10 -mx-1 flex flex-wrap items-center gap-2 border-b border-border bg-background/95 px-1 py-2 backdrop-blur-sm">
        <span className="mr-auto text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          <span className="text-foreground">Current (uploaded)</span>
          <span className="mx-1.5 font-normal text-muted-foreground">→</span>
          <span className="text-foreground">Proposed (latest)</span>
        </span>
        <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
          <Button
            size="sm"
            variant={view === "unified" ? "default" : "ghost"}
            className="h-7 px-2 text-xs"
            onClick={() => setView("unified")}
            aria-pressed={view === "unified"}
          >
            Unified
          </Button>
          <Button
            size="sm"
            variant={view === "split" ? "default" : "ghost"}
            className="h-7 px-2 text-xs"
            onClick={() => setView("split")}
            aria-pressed={view === "split"}
          >
            Side-by-side
          </Button>
        </div>
        <Button size="sm" variant="outline" onClick={copyProposed}>
          {copied ? "Copied" : "Copy proposed"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => downloadText(filename, proposedContent)}
        >
          Download {filename}
        </Button>
      </div>

      {!hasCurrent ? (
        <p
          data-testid="diff-empty-new"
          className="text-xs text-muted-foreground"
          role="status"
        >
          No current skill file — this is a new skill. Proposed content shown as additions.
        </p>
      ) : null}

      {identical ? (
        <p
          data-testid="diff-empty-identical"
          className="text-xs text-muted-foreground"
          role="status"
        >
          Current and proposed content are identical.
        </p>
      ) : null}

      {view === "unified" ? (
        <div
          data-testid="diff-view-unified"
          className="max-h-80 overflow-auto rounded-md border border-border bg-background font-mono text-[11px]"
          role="region"
          aria-label="unified skill diff"
        >
          {lines.map((line, idx) => (
            <DiffLineRow key={`${line.type}-${idx}-${line.oldLine}-${line.newLine}`} line={line} />
          ))}
        </div>
      ) : (
        <div
          data-testid="diff-view-split"
          className={cn("grid gap-2", stacked ? "grid-cols-1" : "lg:grid-cols-2")}
        >
          <div className="min-w-0 space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Current (uploaded)
            </p>
            <div
              ref={leftRef}
              onScroll={onScroll("left")}
              aria-label="current uploaded"
              className="max-h-80 overflow-auto rounded-md border border-border bg-muted/30 font-mono text-[11px]"
            >
              {splitRows.map((row, idx) =>
                row.left ? (
                  <DiffLineRow
                    key={`l-${idx}`}
                    line={row.left}
                    showNewNumber={false}
                  />
                ) : (
                  <div
                    key={`l-${idx}`}
                    className="grid grid-cols-[2.5rem_1.25rem_minmax(0,1fr)] gap-x-1 px-2 py-0.5 leading-relaxed opacity-40"
                  >
                    <span />
                    <span />
                    <span>&nbsp;</span>
                  </div>
                ),
              )}
            </div>
          </div>
          <div className="min-w-0 space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Proposed (latest)
            </p>
            <div
              ref={rightRef}
              onScroll={onScroll("right")}
              aria-label="proposed latest"
              className="max-h-80 overflow-auto rounded-md border border-border bg-background font-mono text-[11px]"
            >
              {splitRows.map((row, idx) =>
                row.right ? (
                  <DiffLineRow key={`r-${idx}`} line={row.right} />
                ) : (
                  <div
                    key={`r-${idx}`}
                    className="grid grid-cols-[2.5rem_1.25rem_minmax(0,1fr)] gap-x-1 px-2 py-0.5 leading-relaxed opacity-40"
                  >
                    <span />
                    <span />
                    <span>&nbsp;</span>
                  </div>
                ),
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
