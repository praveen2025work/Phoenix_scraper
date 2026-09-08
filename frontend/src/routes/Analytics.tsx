import { Link, useParams } from "react-router-dom";
import { BehaviourSection } from "./analytics/BehaviourSection";
import { CoverageSection } from "./analytics/CoverageSection";
import { Headline } from "./analytics/Headline";
import { QualitySection } from "./analytics/QualitySection";

export function Analytics() {
  const { id = "" } = useParams();
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">
        <Link to={`/c/${id}`} className="text-muted-foreground hover:underline">
          {id}
        </Link>{" "}
        / analytics
      </h2>
      <Headline id={id} />
      <CoverageSection id={id} />
      <QualitySection id={id} />
      <BehaviourSection id={id} />
    </div>
  );
}
