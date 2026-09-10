import { Link, useParams } from "react-router-dom";
import type { Candidate } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";

function evidenceLine(candidate: Candidate): string {
  const ev = candidate.current_evidence ?? {};
  if (candidate.rung === "deterministic") {
    return `${Math.round((ev.determinism_score ?? 0) * 100)}% determinism`;
  }
  return `${ev.count ?? 0} asks · ${ev.n_users ?? 0} users`;
}

export function CandidateCard({ candidate }: { candidate: Candidate }) {
  const { id } = useParams();
  const href = `/c/${id}/candidate/${encodeURIComponent(candidate.candidate_id)}`;
  return (
    <Card className="border-border/80 shadow-none transition-colors hover:border-primary/40">
      <CardContent className="p-0 text-sm">
        <Link
          to={href}
          className="block space-y-1 p-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
            <span className="min-w-0 flex-1 font-medium leading-snug text-foreground">
              {candidate.title || candidate.candidate_id}
            </span>
            <StatusBadge status={candidate.status} className="shrink-0 px-1.5 py-0" />
          </div>
          <p className="text-xs text-muted-foreground">{evidenceLine(candidate)}</p>
          <span className="inline-block text-xs font-medium text-primary">Review evidence</span>
        </Link>
      </CardContent>
    </Card>
  );
}
