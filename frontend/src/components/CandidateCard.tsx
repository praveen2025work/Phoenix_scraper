import { Link, useParams } from "react-router-dom";
import type { Candidate } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

function decisionLabel(rung: string): string {
  return rung === "deterministic" ? "Make deterministic" : "Promote to skill";
}

export function CandidateCard({ candidate }: { candidate: Candidate }) {
  const { id } = useParams();
  const ev = candidate.current_evidence ?? {};
  const isDet = candidate.rung === "deterministic";
  return (
    <Card>
      <CardContent className="space-y-2 p-4 text-sm">
        <Link
          to={`/c/${id}/candidate/${encodeURIComponent(candidate.candidate_id)}`}
          className="text-base font-medium hover:underline"
        >
          {candidate.title || candidate.candidate_id}
        </Link>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">{decisionLabel(candidate.rung)}</Badge>
          {candidate.subtype && <Badge variant="outline">{candidate.subtype}</Badge>}
          {candidate.matched_skill && (
            <Badge variant="outline">→ {candidate.matched_skill}</Badge>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          {isDet
            ? `determinism ${Math.round((ev.determinism_score ?? 0) * 100)}% · ` +
              `${ev.n_templates ?? "?"} templates · ${ev.n_answer_spans ?? 0} answers`
            : `${ev.count ?? 0} asks · ${ev.n_users ?? 0} users`}
        </p>
        <p className="text-sm font-medium text-foreground">
          {candidate.status === "ready"
            ? "Ready — open to accept, then write the file"
            : candidate.status === "accepted"
              ? isDet
                ? "Accepted — open to write the deterministic draft"
                : "Accepted — open to write the skill file"
              : "Open to review evidence & decide"}
        </p>
      </CardContent>
    </Card>
  );
}
