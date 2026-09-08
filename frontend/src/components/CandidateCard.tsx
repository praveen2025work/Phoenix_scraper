import { Link, useParams } from "react-router-dom";
import type { Candidate } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

export function CandidateCard({ candidate }: { candidate: Candidate }) {
  const { id } = useParams();
  const ev = candidate.current_evidence;
  const isRung2 = candidate.rung === "deterministic";
  return (
    <Card>
      <CardContent className="space-y-1.5 p-3 text-sm">
        <Link
          to={`/c/${id}/candidate/${encodeURIComponent(candidate.candidate_id)}`}
          className="font-medium hover:underline"
        >
          {candidate.title || candidate.candidate_id}
        </Link>
        <div className="flex flex-wrap gap-1.5">
          {candidate.subtype && <Badge variant="outline">{candidate.subtype}</Badge>}
          {candidate.matched_skill && (
            <Badge variant="outline">→ {candidate.matched_skill}</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {isRung2
            ? `determinism ${Math.round((ev.determinism_score ?? 0) * 100)}% · ` +
              `${ev.n_templates ?? "?"} templates · ${ev.n_answer_spans ?? 0} answers`
            : `${ev.count ?? 0} asks · ${ev.n_users ?? 0} users`}
        </p>
      </CardContent>
    </Card>
  );
}
