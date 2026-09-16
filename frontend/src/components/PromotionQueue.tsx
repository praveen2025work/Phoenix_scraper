import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CircleCheck, FilePen, Scale, type LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { type Candidate, useCandidates } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { displayCandidateTitle, effectiveRung } from "@/lib/promptShape";
import { cn } from "@/lib/utils";

type QueueKind = "write" | "decide" | "done";
type Lane = "skill" | "deterministic";

/** Decide → Write file → Done — matches “finish in order” copy. */
const CARD_ORDER: QueueKind[] = ["decide", "write", "done"];

const CARD_META: Record<
  QueueKind,
  { title: string; subtitle: string; Icon: LucideIcon }
> = {
  decide: {
    title: "Decide",
    subtitle: "Accept, reject, or snooze",
    Icon: Scale,
  },
  write: {
    title: "Write file",
    subtitle: "Materialize the draft",
    Icon: FilePen,
  },
  done: {
    title: "Done",
    subtitle: "Already written",
    Icon: CircleCheck,
  },
};

const LANE_META: Record<
  Lane,
  { title: string; subtitle: string; writeLabel: string }
> = {
  skill: {
    title: "Skill lane · Rung 1",
    subtitle: "User questions → promote to skill",
    writeLabel: "Write file",
  },
  deterministic: {
    title: "Deterministic lane · Rung 2",
    subtitle: "Queries / tools / SQL / params → make deterministic",
    writeLabel: "Write draft",
  },
};

/** Accepted skill-rung candidates eligible for sequential promote (Write all). */
export function acceptedSkillCandidates(items: Candidate[]): Candidate[] {
  return items.filter(
    (c) =>
      c.status === "accepted" &&
      effectiveRung(c.rung, c.title || "") === "skill",
  );
}

/** Split live candidates into skill vs deterministic lanes (shape-aware). */
export function segregateByLane(items: Candidate[]): Record<Lane, Candidate[]> {
  const out: Record<Lane, Candidate[]> = { skill: [], deterministic: [] };
  for (const c of items) {
    out[effectiveRung(c.rung, c.title || "")].push(c);
  }
  return out;
}

function byKind(items: Candidate[]): Record<QueueKind, Candidate[]> {
  return {
    write: items.filter((c) => c.status === "accepted"),
    decide: items.filter((c) => c.status === "ready"),
    done: items.filter((c) => c.status === "promoted"),
  };
}

function rowCta(kind: QueueKind, lane: Lane): string {
  if (kind === "write") {
    return lane === "deterministic" ? "Write draft" : "Write file";
  }
  if (kind === "decide") return "Decide";
  return "View";
}

function candidateLabel(c: Candidate): string {
  return displayCandidateTitle(c.title || "") || c.title || c.candidate_id;
}

function QueueList({
  items,
  capabilityId,
  kind,
  lane,
}: {
  items: Candidate[];
  capabilityId: string;
  kind: QueueKind;
  lane: Lane;
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
      {items.map((c) => {
        const label = candidateLabel(c);
        return (
          <li key={c.candidate_id}>
            <Link
              to={`/c/${capabilityId}/candidate/${encodeURIComponent(c.candidate_id)}`}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-2.5 py-1.5 text-sm hover:bg-muted/40"
            >
              <span
                className="min-w-0 flex-1 whitespace-pre-wrap font-medium leading-snug"
                title={c.title || undefined}
              >
                {label}
              </span>
              <span
                className={cn(
                  "shrink-0 text-xs font-medium",
                  kind === "done" ? "text-muted-foreground" : "text-foreground",
                )}
              >
                {rowCta(kind, lane)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function QueueCard({
  kind,
  items,
  capabilityId,
  lane,
  footer,
}: {
  kind: QueueKind;
  items: Candidate[];
  capabilityId: string;
  lane: Lane;
  footer?: ReactNode;
}) {
  const meta = CARD_META[kind];
  const empty = items.length === 0;
  const writeTitle =
    kind === "write" ? LANE_META[lane].writeLabel : meta.title;

  return (
    <article
      className="overflow-hidden rounded-md border border-border bg-card"
      data-testid={`promotion-card-${lane}-${kind}`}
      aria-labelledby={`promotion-card-${lane}-${kind}-title`}
    >
      <header
        className={cn(
          "flex flex-wrap items-center gap-x-2 gap-y-0.5 border-b border-primary/25",
          "border-l-4 border-l-primary bg-surface-strong px-3 py-2",
        )}
      >
        <meta.Icon
          size={16}
          className="shrink-0 text-primary"
          aria-hidden="true"
        />
        <h4
          id={`promotion-card-${lane}-${kind}-title`}
          className="text-sm font-semibold text-foreground"
        >
          {writeTitle}
        </h4>
        <Badge variant={empty ? "outline" : "default"}>{items.length}</Badge>
        <span className="text-xs text-muted-foreground">{meta.subtitle}</span>
      </header>
      <div className="space-y-2 p-2.5">
        {footer}
        <QueueList items={items} capabilityId={capabilityId} kind={kind} lane={lane} />
      </div>
    </article>
  );
}

function LaneSection({
  lane,
  items,
  capabilityId,
  footer,
}: {
  lane: Lane;
  items: Candidate[];
  capabilityId: string;
  footer?: ReactNode;
}) {
  const meta = LANE_META[lane];
  const groups = byKind(items);
  return (
    <section
      className="space-y-2"
      data-testid={`promotion-lane-${lane}`}
      aria-labelledby={`promotion-lane-${lane}-title`}
    >
      <div>
        <h4
          id={`promotion-lane-${lane}-title`}
          className="text-sm font-semibold text-foreground"
        >
          {meta.title}
        </h4>
        <p className="text-xs text-muted-foreground">{meta.subtitle}</p>
      </div>
      <div className="grid gap-2 lg:grid-cols-3">
        {CARD_ORDER.map((kind) => (
          <QueueCard
            key={`${lane}-${kind}`}
            kind={kind}
            lane={lane}
            items={groups[kind]}
            capabilityId={capabilityId}
            footer={kind === "write" ? footer : undefined}
          />
        ))}
      </div>
    </section>
  );
}

/** Live capability promotion queue — skill lane and deterministic lane, segregated. */
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

  const lanes = segregateByLane(data ?? []);
  const skillWrite = acceptedSkillCandidates(lanes.skill);

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
      className="space-y-4"
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
          Skill questions and deterministic payloads stay in separate lanes —
          decide → write in each.
        </p>
      </div>

      <LaneSection
        lane="skill"
        items={lanes.skill}
        capabilityId={capabilityId}
        footer={
          skillWrite.length >= 2 ? (
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

      <LaneSection
        lane="deterministic"
        items={lanes.deterministic}
        capabilityId={capabilityId}
      />
    </section>
  );
}
