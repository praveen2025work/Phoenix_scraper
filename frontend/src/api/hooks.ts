import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface CapabilitySummary {
  id: string;
  name: string;
  status: string;
  filter: Record<string, string | null>;
  window_days: number;
  last_run: Record<string, unknown> | null;
  candidates: Record<string, Record<string, number>>;
}

export interface Candidate {
  candidate_id: string;
  capability_id: string;
  rung: string;
  subtype: string;
  status: string;
  title: string;
  matched_skill: string | null;
  current_evidence: Record<string, number>;
  cluster_id: string;
  promoted_artifact_paths?: string[];
}

export interface Observation {
  run_id: string;
  count: number;
  n_users?: number;
  score: number | null;
  met_evidence_bar: number;
  signals: Record<string, unknown>;
}

export interface Decision {
  created_at: string;
  action: string;
  actor: string;
  note: string;
}

const enc = encodeURIComponent;

export const useCapabilities = () =>
  useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api.get<CapabilitySummary[]>("/capabilities"),
  });

export const useCapability = (id: string) =>
  useQuery({
    queryKey: ["capability", id],
    queryFn: () =>
      api.get<{
        capability: CapabilitySummary & Record<string, unknown>;
        summary: CapabilitySummary;
        skill_files: string[];
      }>(`/capabilities/${enc(id)}`),
  });

export const useCandidates = (id: string, rung?: string) =>
  useQuery({
    queryKey: ["candidates", id, rung ?? "all"],
    queryFn: () =>
      api.get<Candidate[]>(
        `/capabilities/${enc(id)}/candidates${rung ? `?rung=${rung}` : ""}`,
      ),
  });

export const useCandidate = (cid: string) =>
  useQuery({
    queryKey: ["candidate", cid],
    queryFn: () =>
      api.get<{
        candidate: Candidate;
        observations: Observation[];
        decisions: Decision[];
      }>(`/candidates/${enc(cid)}`),
  });

export interface JobDto {
  job_id?: string;
  capability_id?: string;
  state: "queued" | "running" | "done" | "error";
  stage?: "queued" | "scraping" | "analyzing" | "matching" | "done" | "error" | string;
  progress?: number;
  message?: string | null;
  run_id: string | null;
  error: string | null;
}

export interface SkillFile {
  filename: string;
  bytes: number;
  valid: boolean;
  name: string | null;
  description: string | null;
  n_example_prompts: number;
}

export const useSkillFiles = (id: string) =>
  useQuery({
    queryKey: ["skills", id],
    queryFn: () => api.get<SkillFile[]>(`/capabilities/${enc(id)}/skills`),
  });

export function useUploadSkillFile(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { filename: string; content: string }) =>
      api.post<SkillFile>(`/capabilities/${enc(id)}/skills`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skills", id] });
      qc.invalidateQueries({ queryKey: ["capability", id] });
    },
  });
}

export function useDeleteSkillFile(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) =>
      api.del(`/capabilities/${enc(id)}/skills/${enc(filename)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skills", id] });
      qc.invalidateQueries({ queryKey: ["capability", id] });
    },
  });
}

/** Enqueue a background capability run — returns a job_id to poll with useJob.
 * Requires a closed [from, to] window (backend refuses open-ended scrapes). */
export function useEnqueueRun(id: string) {
  return useMutation({
    mutationFn: (body: { from: string; to: string; replace_today?: boolean }) =>
      api.post<{
        job_id: string;
        state: string;
        stage?: string;
        progress?: number;
        message?: string | null;
      }>(`/capabilities/${enc(id)}/jobs`, body),
  });
}

/** Poll one run job every `pollMs` until its state is `done` or `error`. */
export function useJob(capabilityId: string, jobId: string | null, pollMs = 1500) {
  return useQuery({
    queryKey: ["job", capabilityId, jobId],
    queryFn: () =>
      api.get<JobDto>(`/capabilities/${enc(capabilityId)}/jobs/${enc(jobId ?? "")}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.state;
      return s === "done" || s === "error" ? false : pollMs;
    },
  });
}

export interface RunFunnel {
  n_spans: number;
  n_in_scope_spans: number;
  n_clusters: number;
  n_uncovered: number;
  n_unmatched: number;
  n_rung1_candidates: number;
  n_rung2_candidates: number;
  empty_at: string | null;
  empty_reason: string | null;
}

export interface UncoveredRow {
  skill_name?: string | null;
  source_file?: string | null;
  cluster_id: string;
  representative: string;
  count: number;
  n_users: number;
  status?: string | null;
  coverage_score?: number;
}

export interface SkillUpdateRow {
  skill_name: string;
  source_file: string;
  uncovered_asks: number;
  n_users: number;
  n_new_prompts: number;
  new_prompts: string[];
  new_keywords: string[];
  yaml_block?: string;
}

export interface RunResultsDto {
  capability_id: string;
  run_id: string;
  status: string;
  window_start: string | null;
  window_end: string | null;
  notes: string[];
  warnings: string[];
  skill_hashes: Record<string, string>;
  funnel: RunFunnel;
  uncovered: UncoveredRow[];
  suggested_skill_updates: SkillUpdateRow[];
  rung1_candidates: Candidate[];
  rung2_candidates: Candidate[];
  previous_run_id?: string | null;
}

export const useRunResults = (capabilityId: string, runId: string | null) =>
  useQuery({
    queryKey: ["run-results", capabilityId, runId],
    queryFn: () =>
      api.get<RunResultsDto>(
        `/capabilities/${enc(capabilityId)}/runs/${enc(runId ?? "")}/results`,
      ),
    enabled: !!runId,
  });

/** One row from GET /capabilities/{id}/runs (raw capability_runs frame). */
export interface CapabilityRunRow {
  capability_id: string;
  run_id: string;
  started_at?: string | null;
  finished_at?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  n_spans?: number;
  n_in_scope_spans?: number;
  n_clusters?: number;
  n_rung1_candidates?: number;
  n_rung2_candidates?: number;
  status?: string;
  notes_json?: string;
  skill_hashes_json?: string;
}

/** Past versions for a capability, newest first. */
export const useCapabilityRuns = (capabilityId: string, enabled = true) =>
  useQuery({
    queryKey: ["capability-runs", capabilityId],
    queryFn: () =>
      api.get<CapabilityRunRow[]>(`/capabilities/${enc(capabilityId)}/runs`),
    enabled: !!capabilityId && enabled,
  });

export interface GapRow {
  cluster_id: string;
  representative: string;
  count: number;
  n_users: number;
  skill_name: string | null;
  covered: boolean;
  reason: string;
}

export interface RunCompareDto {
  capability_id: string;
  from_run: {
    run_id: string;
    window_start: string | null;
    window_end: string | null;
    skill_hashes: Record<string, string>;
    n_gaps: number;
  };
  to_run: {
    run_id: string;
    window_start: string | null;
    window_end: string | null;
    skill_hashes: Record<string, string>;
    n_gaps: number;
  };
  skill_hash_changes: {
    added: string[];
    removed: string[];
    changed: { filename: string; from: string; to: string }[];
    unchanged: string[];
  };
  gaps_closed: GapRow[];
  gaps_new: GapRow[];
  candidates_advancing: {
    candidate_id: string;
    rung: string;
    title: string;
    from_status: string | null;
    to_status: string;
    change: string;
  }[];
}

export const useRunCompare = (
  capabilityId: string,
  fromRun: string | null,
  toRun: string | null,
) =>
  useQuery({
    queryKey: ["run-compare", capabilityId, fromRun, toRun],
    queryFn: () =>
      api.get<RunCompareDto>(
        `/capabilities/${enc(capabilityId)}/runs/compare?from_run=${enc(fromRun ?? "")}&to_run=${enc(toRun ?? "")}`,
      ),
    enabled: !!fromRun && !!toRun && fromRun !== toRun,
  });

export function useDecide(cid: string, capabilityId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      action: string;
      actor?: string;
      note?: string;
      snooze_runs?: number;
    }) => api.post(`/candidates/${enc(cid)}/decision`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidate", cid] });
      qc.invalidateQueries({ queryKey: ["candidates", capabilityId] });
    },
  });
}

export function usePromote(cid: string, capabilityId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accept: boolean) =>
      api.post<{ paths: string[]; contents: { path: string; body: string }[] }>(
        `/candidates/${enc(cid)}/promote${accept ? "?accept=true" : ""}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["candidate", cid] });
      qc.invalidateQueries({ queryKey: ["candidates", capabilityId] });
    },
  });
}

export const usePreview = (cid: string) =>
  useQuery({
    queryKey: ["preview", cid],
    enabled: false,
    queryFn: () =>
      api.get<{ contents: { path: string; body: string }[] }>(
        `/candidates/${enc(cid)}/artifact/preview`,
      ),
  });

export interface SpanFilter {
  project?: string | null;
  workflow_stage?: string | null;
  asset_class?: string | null;
  model_name?: string | null;
  search?: string | null;
  search_any?: string[];
}

export interface FilterPreviewDto {
  n_spans: number;
  n_llm_spans: number;
  n_users: number;
  n_sessions: number;
  n_spans_in_store: number;
  window_days: number;
  from?: string;
  to?: string;
  distinct: { workflow_stage: string[]; asset_class: string[]; project: string[] };
  sample_prompts: string[];
}

export interface PreviewWindow {
  windowDays?: number;
  from?: string;
  to?: string;
}

/** What would this filter catch? Nothing is saved or run.
 * Prefer an explicit from/to (operator-picked run window) over window_days alone. */
export function useFilterPreview(
  filter: SpanFilter,
  window: number | PreviewWindow,
  enabled = true,
) {
  const resolved: PreviewWindow =
    typeof window === "number" ? { windowDays: window } : window;
  const windowDays = resolved.windowDays ?? 30;
  return useQuery({
    queryKey: ["preview", JSON.stringify(filter), windowDays, resolved.from, resolved.to],
    queryFn: () =>
      api.post<FilterPreviewDto>("/capabilities/preview", {
        filter,
        window_days: windowDays,
        ...(resolved.from ? { from: resolved.from } : {}),
        ...(resolved.to ? { to: resolved.to } : {}),
      }),
    enabled,
    staleTime: 30_000,
  });
}

export function usePatchCapability(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch(`/capabilities/${enc(id)}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["capability", id] });
      qc.invalidateQueries({ queryKey: ["capabilities"] });
    },
  });
}

export const useCreateCapability = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post("/capabilities", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["capabilities"] }),
  });
};

export const useOverview = (capabilityId: string) =>
  useQuery({
    queryKey: ["overview", capabilityId],
    queryFn: () =>
      api.get<Record<string, number>>(`/overview?capability=${enc(capabilityId)}`),
  });

export const useCoverage = (capabilityId: string) =>
  useQuery({
    queryKey: ["coverage", capabilityId],
    queryFn: () =>
      api.get<Record<string, unknown>[]>(
        `/skills/coverage?capability=${enc(capabilityId)}`,
      ),
  });

export const useRunDeltas = (capabilityId: string) =>
  useQuery({
    queryKey: ["capdelta", capabilityId],
    queryFn: () =>
      api.get<Record<string, unknown>[]>(
        `/capabilities/${enc(capabilityId)}/runs/delta`,
      ),
  });

export type Row = Record<string, unknown>;

/** Generic scoped-analytics query: GET <path> with ?capability=<id> merged in. */
export function useScoped<T = Row[]>(key: string, path: string, capabilityId: string) {
  const sep = path.includes("?") ? "&" : "?";
  return useQuery({
    queryKey: [key, capabilityId, path],
    queryFn: () => api.get<T>(`${path}${sep}capability=${enc(capabilityId)}`),
  });
}
