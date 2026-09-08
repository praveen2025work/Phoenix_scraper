import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useCandidates, useCapability, useEnqueueRun, useJob } from "@/api/hooks";
import { LaneBoard } from "@/components/LaneBoard";
import { RunSummary } from "@/components/RunSummary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function CapabilityDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const cap = useCapability(id);
  const candidates = useCandidates(id);
  const enqueue = useEnqueueRun(id);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(id, jobId);

  useEffect(() => {
    const data = job.data;
    if (!data) return;
    if (data.state === "done") {
      toast.success(
        data.run_id ? `Run ${data.run_id.slice(0, 16)} complete` : "Run complete",
      );
      qc.invalidateQueries({ queryKey: ["capability", id] });
      qc.invalidateQueries({ queryKey: ["candidates", id] });
      setJobId(null);
    } else if (data.state === "error") {
      toast.error(data.error ?? "Run failed");
      setJobId(null);
    }
  }, [job.data, id, qc]);

  if (cap.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (cap.error)
    return <p className="text-sm text-destructive">{(cap.error as Error).message}</p>;

  const summary = cap.data?.summary;
  const all = candidates.data ?? [];
  const rung1 = all.filter((c) => c.rung === "skill");
  const rung2 = all.filter((c) => c.rung === "deterministic");
  const running = enqueue.isPending || jobId !== null;

  function triggerRun() {
    enqueue.mutate(
      {},
      {
        onSuccess: (d) => setJobId(d.job_id),
        onError: (e) => toast.error((e as Error).message),
      },
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">
            <Link to="/" className="text-muted-foreground hover:underline">
              capabilities
            </Link>{" "}
            / {summary?.name ?? id}
          </h2>
          {summary && (
            <p className="text-sm text-muted-foreground">
              {Object.entries(summary.filter)
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ") || "all spans"}{" "}
              · window {summary.window_days}d ·{" "}
              <Badge variant={summary.status === "active" ? "default" : "warn"}>
                {summary.status}
              </Badge>
            </p>
          )}
        </div>
        <Button onClick={triggerRun} disabled={running}>
          {running ? "Running…" : "Run now"}
        </Button>
      </div>

      <RunSummary run={(summary?.last_run as Record<string, unknown>) ?? null} />

      <Tabs defaultValue="rung1">
        <TabsList>
          <TabsTrigger value="rung1">Rung 1 — promote to skill ({rung1.length})</TabsTrigger>
          <TabsTrigger value="rung2">Rung 2 — make deterministic ({rung2.length})</TabsTrigger>
          <TabsTrigger value="analytics" asChild>
            <Link to={`/c/${id}/analytics`}>Analytics</Link>
          </TabsTrigger>
        </TabsList>
        <TabsContent value="rung1">
          <LaneBoard candidates={rung1} capabilityId={id} />
        </TabsContent>
        <TabsContent value="rung2">
          <LaneBoard candidates={rung2} capabilityId={id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
