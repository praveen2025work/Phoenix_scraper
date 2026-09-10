import { Link, useParams } from "react-router-dom";
import { useEffect } from "react";
import { useCapability } from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { PageHeader } from "@/components/PageHeader";
import { useJourney } from "@/journey/JourneyContext";
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
    ? `${from} → ${to} (this version's window)`
    : `last ${windowDays} days (no run yet)`;
}

export function Analytics() {
  const { id = "" } = useParams();
  const { setCapabilityId } = useJourney();
  const cap = useCapability(id);
  const summary = cap.data?.summary;
  const name = summary?.name ?? id;

  useEffect(() => {
    setCapabilityId(id);
  }, [id, setCapabilityId]);

  return (
    <div className="space-y-8">
      <PageHeader
        breadcrumb={
          <Link to={`/c/${id}`} className="hover:underline">
            {name}
          </Link>
        }
        title="Usage for this version"
        outcome="Cost, quality, and coverage for the same window as your last run — secondary to the promotion loop."
        meta={
          <p>
            Showing{" "}
            {periodLabel(
              (summary?.last_run as Record<string, unknown>) ?? null,
              summary?.window_days ?? 30,
            )}
          </p>
        }
        actions={
          <Link
            to={`/c/${id}`}
            className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
          >
            ← Back to results
          </Link>
        }
      />

      <OutcomeBanner title="How to use this page">
        Check whether volume and quality support promoting a candidate. When you&apos;re
        ready to decide, return to Results and open a promote-to-skill or
        make-deterministic card.
      </OutcomeBanner>

      <section className="space-y-4">
        <h2 className="text-base font-semibold tracking-tight">At a glance</h2>
        <Headline id={id} />
      </section>
      <CoverageSection id={id} />
      <QualitySection id={id} />
      <BehaviourSection id={id} />
    </div>
  );
}
