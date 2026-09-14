import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

type Props = {
  filename: string;
  currentContent: string | null | undefined;
  proposedContent: string;
  /** Compact single-column when space is tight (e.g. nested panels). */
  stacked?: boolean;
};

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Left = current uploaded skill MD; right = proposed full file (copy / download). */
export function SkillContentDiff({
  filename,
  currentContent,
  proposedContent,
  stacked = false,
}: Props) {
  const [copied, setCopied] = useState(false);
  const current = (currentContent ?? "").trim();
  const hasCurrent = current.length > 0;

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
      <div className="flex flex-wrap items-center gap-2">
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
      <div
        className={
          stacked
            ? "grid gap-2"
            : "grid gap-2 lg:grid-cols-2"
        }
      >
        <div className="min-w-0 space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Current uploaded
          </p>
          <pre
            aria-label="current uploaded"
            className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap"
          >
            {hasCurrent ? currentContent : "No uploaded skill file yet — right side is a new file."}
          </pre>
        </div>
        <div className="min-w-0 space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Proposed
          </p>
          <pre
            aria-label="proposed"
            className="max-h-64 overflow-auto rounded-md border border-border bg-background p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap"
          >
            {proposedContent}
          </pre>
        </div>
      </div>
    </div>
  );
}
