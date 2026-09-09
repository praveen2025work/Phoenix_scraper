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
}

export interface Observation {
  run_id: string;
  count: number;
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
  state: "queued" | "running" | "done" | "error";
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

/** Enqueue a background capability run — returns a job_id to poll with useJob. */
export function useEnqueueRun(id: string) {
  return useMutation({
    mutationFn: (body: { from?: string; to?: string; replace_today?: boolean }) =>
      api.post<{ job_id: string; state: string }>(`/capabilities/${enc(id)}/jobs`, body),
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
