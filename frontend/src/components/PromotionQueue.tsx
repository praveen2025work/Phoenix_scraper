import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/client";
import { type Candidate, useCandidates } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type QueueKind = "write" | "decide" | "done";

/** Decide → Write file → Done — matches “finish in order” copy. */
const CARD_ORDER: QueueKind[] = ["decide", "write", "done"];

const CARD_META: Record<
  QueueKind,
  { title: string; subtitle: string }
> = {
  decide: {
    title: "Decide",
    subtitle: "Accept, reject, or snooze",
  },
  write: {
    title: "Write file",
    subtitle: "Materialize the draft",
  },
  done: {
    title: "Done",
    subtitle: "Already written",
  },
};

/** Accepted skill-rung candidates eligible for sequential promote (Write all). */
export function acceptedSkillCandidates(items: Candidate[]): Candidate[] {
  return items.filter((c) => c.status === "accepted" && c.rung === "skill");
}

function rowCta(kind: QueueKind, rung: string): string {
  if (kind === "write") {
    return rung === "deterministic" ? "Write draft" : "Write file";
  }
  if (kind === "decide") return "Decide";
  return "View";
}

function QueueList({
  items,
  capabilityId,
  kind,
}: {
  items: Candidate[];
  capabilityId: string;
  kind: QueueKind;
}) {
  if (items.length === 0) {
    return (
      <p className="text-xs text-muted-foreground" role="status">
        Nothing here
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border rounded border border-border/80 bg-background/60">
      {items.map((c) => (
        <li key={c.candidate_id}>
          <Link
            to={`/c/${capabilityId}/candidate/${encodeURIComponent(c.candidate_id)}`}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-2.5 py-1.5 text-sm hover:bg-muted/40"
          >
            <span className="min-w-0 flex-1 font-medium truncate">
              {c.title || c.candidate_id}
            </span>
            <span
              className={cn(
                "shrink-0 text-xs font-medium",
                kind === "done" ? "text-muted-foreground" : "text-foreground",
              )}
            >
              {rowCta(kind, c.rung)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function QueueCard({
  kind,
  items,
  capabilityId,
  footer,
}: {
  kind: QueueKind;
  items: Candidate[];
  capabilityId: string;
  footer?: ReactNode;
}) {
  const meta = CARD_META[kind];
  const empty = items.length === 0;

  return (
    <article
      className="overflow-hidden rounded-md border border-border bg-card"
      data-testid={`promotion-card-${kind}`}
      aria-labelledby={`promotion-card-${kind}-title`}
    >
      <header
        className={cn(
          "flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-primary/25",
          "border-l-4 border-l-primary bg-surface-strong px-3 py-2",
        )}
      >
        <h4
          id={`promotion-card-${kind}-title`}
          className="text-sm font-semibold text-foreground"
        >
          {meta.title}
        </h4>
        <Badge variant={empty ? "outline" : "default"}>{items.length}</Badge>
        <span className="text-xs text-muted-foreground">{meta.subtitle}</span>
      </header>
      <div className="space-y-2 p-2.5">
        {footer}
        <QueueList items={items} capabilityId={capabilityId} kind={kind} />
      </div>
    </article>
  );
}

/** Live capability promotion queue — decide, then write the skill file. */
export function PromotionQueue({ capabilityId }: { capabilityId: string }) {
  const { data, isLoading, error } = useCandidates(capabilityId);
  const [writingAll, setWritingAll] = useState(false);
  const qc = useQueryClient();

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="promotion-queue">
        Loading promotion queue…
      </p>
    );
  }
  if (error) {
    return (
      <p className="text-sm text-destructive" role="alert" data-testid="promotion-queue">
        {(error as Error).message}
      </p>
    );
  }

  const all = data ?? [];
  const byKind: Record<QueueKind, Candidate[]> = {
    write: all.filter((c) => c.status === "accepted"),
    decide: all.filter((c) => c.status === "ready"),
    done: all.filter((c) => c.status === "promoted"),
  };
  const skillWrite = acceptedSkillCandidates(byKind.write);

  async function writeAllSkillFiles() {
    if (skillWrite.length === 0 || writingAll) return;
    setWritingAll(true);
    let ok = 0;
    const total = skillWrite.length;
    const toastId = toast.loading(`Writing skill files 0/${total}…`);
    try {
      for (let i = 0; i < total; i++) {
        const c = skillWrite[i]!;
        toast.loading(`Writing skill files ${i + 1}/${total}…`, { id: toastId });
        await api.post<{ paths: string[] }>(
          `/candidates/${encodeURIComponent(c.candidate_id)}/promote`,
        );
        ok += 1;
      }
      toast.success(`Wrote ${ok} skill file(s)`, { id: toastId });
    } catch (err) {
      toast.error(
        ok > 0
          ? `Stopped after ${ok}/${total}: ${(err as Error).message}`
          : (err as Error).message,
        { id: toastId },
      );
    } finally {
      setWritingAll(false);
      void qc.invalidateQueries({ queryKey: ["candidates", capabilityId] });
    }
  }

  return (
    <section
      className="space-y-2"
      data-testid="promotion-queue"
      aria-labelledby="promotion-queue-title"
    >
      <div>
        <h3
          id="promotion-queue-title"
          className="font-display text-lg font-semibold tracking-tight"
        >
          Promotion queue
        </h3>
        <p className="text-xs text-muted-foreground">
          Finish these in order: decide → write the skill file.
        </p>
      </div>

      <div className="grid gap-2 lg:grid-cols-3">
        {CARD_ORDER.map((kind) => (
          <QueueCard
            key={kind}
            kind={kind}
            items={byKind[kind]}
            capabilityId={capabilityId}
            footer={
              kind === "write" && skillWrite.length >= 2 ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={writingAll}
                    onClick={() => void writeAllSkillFiles()}
                    data-testid="write-all-skills"
                  >
                    {writingAll
                      ? "Writing…"
                      : `Write all skill files (${skillWrite.length})`}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Writes each accepted skill draft in order.
                  </span>
                </div>
              ) : undefined
            }
          />
        ))}
      </div>
    </section>
  );
}
