import { createContext, useContext } from "react";

/** Precomputed Usage panels for one capability run (GET …/runs/{id}/analytics). */
export type AnalyticsPanels = Record<string, unknown>;

export interface AnalyticsSnapshotDto {
  capability_id: string;
  run_id: string;
  window_start: string | null;
  window_end: string | null;
  panels: AnalyticsPanels;
}

const AnalyticsSnapshotContext = createContext<AnalyticsSnapshotDto | null>(null);

export const AnalyticsSnapshotProvider = AnalyticsSnapshotContext.Provider;

/** Snapshot panels when Analytics is loading from a precomputed run; else null. */
export function useAnalyticsSnapshot(): AnalyticsSnapshotDto | null {
  return useContext(AnalyticsSnapshotContext);
}

/** Map a live fetch path (without ?capability=) to a snapshot panel key. */
export function snapshotKeyForPath(path: string): string | null {
  const bare = path.split("?")[0] ?? path;
  const qs = path.includes("?") ? path.slice(path.indexOf("?")) : "";
  const map: Record<string, string> = {
    "/overview": "overview",
    "/quality/overview": "quality_overview",
    "/insights/activity": "activity",
    "/skills/coverage": "skills_coverage",
    "/skills/updates": "skills_updates",
    "/skills/gaps": "skills_gaps",
    "/insights/skill-health": "skill_health",
    "/insights/questions": "questions",
    "/quality/checks": "quality_checks",
    "/quality/by-prompt": "quality_by_prompt",
    "/insights/flows": "flows",
    "/insights/efficiency": "efficiency",
    "/insights/breakdown": "breakdown",
    "/insights/tools": "tools",
    "/insights/models": "models",
    "/users": "users",
  };
  if (bare === "/quality/by") {
    if (qs.includes("dimension=user_id")) return "quality_by_user_id";
    if (qs.includes("dimension=model_name")) return "quality_by_model_name";
  }
  if (bare === "/quality/failures") return "quality_failures";
  return map[bare] ?? null;
}
