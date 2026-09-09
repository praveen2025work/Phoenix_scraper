import { Link, useParams } from "react-router-dom";
import { useCapability } from "@/api/hooks";
import { BehaviourSection } from "./analytics/BehaviourSection";
import { CoverageSection } from "./analytics/CoverageSection";
import { Headline } from "./analytics/Headline";
import { QualitySection } from "./analytics/QualitySection";

const DAY = /^(\d{4}-\d{2}-\d{2})/;

/** The API scopes every panel to the last run's window, so say which one that is —
 *  an unlabelled date range is how "the dashboard is empty" becomes unanswerable. */
function periodLabel(run: Record<string, unknown> | null, windowDays: number): string {
  const from = DAY.exec(String(run?.window_start ?? ""))?.[1];
  const to = DAY.exec(String(run?.window_end ?? ""))?.[1];
  return from && to
    ? `${from} → ${to} (the last run's window)`
    : `last ${windowDays} days (no run yet)`;
}

export function Analytics() {
  const { id = "" } = useParams();
  const cap = useCapability(id);
  const summary = cap.data?.summary;
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">
        <Link to={`/c/${id}`} className="text-muted-foreground hover:underline">
          {id}
        </Link>{" "}
        / analytics
      </h2>
      <p className="-mt-4 text-sm text-muted-foreground">
        showing{" "}
        {periodLabel(
          (summary?.last_run as Record<string, unknown>) ?? null,
          summary?.window_days ?? 30,
        )}
      </p>
      <Headline id={id} />
      <CoverageSection id={id} />
      <QualitySection id={id} />
      <BehaviourSection id={id} />
    </div>
  );
}
