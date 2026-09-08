import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/client";
import { useCandidate, useDecide, usePromote } from "@/api/hooks";
import { Sparkline } from "@/components/Sparkline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";

// Mirrors ladder.DECISION_TRANSITIONS: action -> statuses it is allowed from.
const ALLOWED: Record<string, string[]> = {
  accept: ["ready"],
  reject: ["accumulating", "ready", "new"],
  snooze: ["accumulating", "ready", "new"],
  reopen: ["rejected", "snoozed", "stale"],
};

const SIGNAL_KEYS = [
  "template_concentration",
  "route_invariance",
  "output_self_similarity",
  "slot_stability",
] as const;

export function CandidateDetail() {
  const { id = "", cid = "" } = useParams();
  const nav = useNavigate();
  const q = useCandidate(cid);
  const decide = useDecide(cid, id);
  const promote = usePromote(cid, id);
  const [dialogAction, setDialogAction] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<{ path: string; body: string }[] | null>(null);

  if (q.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (q.error || !q.data)
    return <p className="text-sm text-destructive">{(q.error as Error)?.message ?? "not found"}</p>;

  const { candidate, observations, decisions } = q.data;
  const isRung2 = candidate.rung === "deterministic";
  const trend = observations.map((o) => o.score ?? o.count);
  const latestSignals = (observations.at(-1)?.signals ?? {}) as Record<string, number>;

  function submitDecision(e: FormEvent) {
    e.preventDefault();
    if (!dialogAction) return;
    decide.mutate(
      { action: dialogAction, actor: actor || undefined, note },
      {
        onSuccess: () => {
          toast.success(`${dialogAction}ed`);
          setDialogAction(null);
          setNote("");
        },
        onError: (err) => toast.error((err as Error).message),
      },
    );
  }

  async function showPreview() {
    try {
      const r = await api.get<{ contents: { path: string; body: string }[] }>(
        `/candidates/${encodeURIComponent(cid)}/artifact/preview`,
      );
      setPreview(r.contents);
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  function doPromote(accept: boolean) {
    promote.mutate(accept, {
      onSuccess: (r) => {
        toast.success(`Wrote ${r.paths.length} file(s)`);
        nav(`/c/${id}`);
      },
      onError: (err) => toast.error((err as Error).message),
    });
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">
        <Link to={`/c/${id}`} className="text-muted-foreground hover:underline">
          {id}
        </Link>{" "}
        / {candidate.title || candidate.candidate_id}
      </h2>
      <div className="flex flex-wrap gap-1.5">
        <Badge>{candidate.rung}</Badge>
        {candidate.subtype && <Badge variant="outline">{candidate.subtype}</Badge>}
        <Badge variant={candidate.status === "ready" ? "ready" : "outline"}>
          {candidate.status}
        </Badge>
        {candidate.matched_skill && (
          <Badge variant="outline">→ {candidate.matched_skill}</Badge>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3 text-sm">
            Evidence trend <Sparkline values={trend} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>run</TH>
                <TH>count</TH>
                <TH>score</TH>
                <TH>met bar</TH>
              </TR>
            </THead>
            <TBody>
              {observations.map((o) => (
                <TR key={o.run_id}>
                  <TD>{o.run_id.slice(0, 16)}</TD>
                  <TD>{o.count}</TD>
                  <TD>{o.score == null ? "—" : o.score.toFixed(2)}</TD>
                  <TD>{o.met_evidence_bar ? "✓" : ""}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      {isRung2 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Determinism signals (latest run)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {SIGNAL_KEYS.map((k) => {
              const v = latestSignals[k];
              return (
                <div key={k} className="flex items-center gap-2 text-xs">
                  <span className="w-48 text-muted-foreground">{k}</span>
                  <div className="h-2 flex-1 rounded bg-muted">
                    <div
                      className="h-2 rounded bg-primary"
                      style={{ width: `${Math.round((v ?? 0) * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 text-right">
                    {v == null ? "n/a" : v.toFixed(2)}
                  </span>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Decide</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {Object.keys(ALLOWED).map((action) => (
            <Button
              key={action}
              size="sm"
              variant={action === "reject" ? "destructive" : "outline"}
              disabled={!ALLOWED[action].includes(candidate.status)}
              onClick={() => setDialogAction(action)}
            >
              {action}
            </Button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Artifact</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={showPreview}>
              Preview
            </Button>
            <Button
              size="sm"
              disabled={candidate.status !== "accepted" || promote.isPending}
              onClick={() => doPromote(false)}
            >
              Promote
            </Button>
            {candidate.status === "ready" && (
              <Button size="sm" variant="outline" onClick={() => doPromote(true)}>
                Accept &amp; promote
              </Button>
            )}
          </div>
          {preview?.map((f) => (
            <details key={f.path} className="rounded border border-border">
              <summary className="cursor-pointer px-2 py-1 text-xs text-muted-foreground">
                {f.path}
              </summary>
              <pre className="overflow-x-auto p-2 text-xs">{f.body}</pre>
            </details>
          ))}
        </CardContent>
      </Card>

      {decisions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Decision log</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-xs text-muted-foreground">
            {decisions.map((d, i) => (
              <p key={i}>
                {d.created_at.slice(0, 16)} · {d.action} by {d.actor} {d.note && `— ${d.note}`}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      <Dialog open={!!dialogAction} onOpenChange={(o) => !o && setDialogAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialogAction} candidate</DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={submitDecision}>
            <label className="block text-sm">
              actor
              <Input
                aria-label="actor"
                value={actor}
                onChange={(e) => setActor(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              note
              <Input aria-label="note" value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <div className="flex justify-end gap-2">
              <DialogClose asChild>
                <Button type="button" variant="ghost">
                  Cancel
                </Button>
              </DialogClose>
              <Button type="submit" disabled={decide.isPending}>
                Confirm
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
