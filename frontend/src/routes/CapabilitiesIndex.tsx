import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  type CapabilitySummary,
  useCapabilities,
  useCreateCapability,
} from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

function filterSummary(f: Record<string, string | null>): string {
  const parts = Object.entries(f)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k.replace("workflow_", "")}=${v}`);
  return parts.length ? parts.join(", ") : "all spans";
}

function readyCount(by: Record<string, number> | undefined): number {
  return by?.ready ?? 0;
}

function CapabilityCard({ cap }: { cap: CapabilitySummary }) {
  const last = cap.last_run as { run_id?: string; status?: string } | null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <Link to={`/c/${cap.id}`} className="hover:underline">
            {cap.name}
          </Link>
          <Badge variant={cap.status === "active" ? "default" : "warn"}>{cap.status}</Badge>
        </CardTitle>
        <p className="text-sm text-muted-foreground">{filterSummary(cap.filter)}</p>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p className="text-muted-foreground">
          {last?.run_id
            ? `last run ${last.run_id.slice(0, 16)} · ${last.status}`
            : "no runs yet"}
        </p>
        <div className="flex gap-2">
          <Badge variant="ready">Rung 1: {readyCount(cap.candidates.skill)} ready</Badge>
          <Badge variant="ready">
            Rung 2: {readyCount(cap.candidates.deterministic)} ready
          </Badge>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to={`/c/${cap.id}`}>Open</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function NewCapabilityDialog() {
  const create = useCreateCapability();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ id: "", name: "", stage: "", window_days: "30" });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        id: form.id,
        name: form.name || form.id,
        filter: { workflow_stage: form.stage || null },
        window_days: Number(form.window_days) || 30,
      },
      {
        onSuccess: () => {
          toast.success(`Created ${form.id}`);
          setOpen(false);
          setForm({ id: "", name: "", stage: "", window_days: "30" });
        },
        onError: (err) => toast.error(String((err as Error).message)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>New capability</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New capability</DialogTitle>
        </DialogHeader>
        <form className="space-y-3" onSubmit={submit}>
          <label className="block text-sm">
            id
            <Input
              aria-label="id"
              value={form.id}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              required
            />
          </label>
          <label className="block text-sm">
            name
            <Input
              aria-label="name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label className="block text-sm">
            workflow stage
            <Input
              aria-label="workflow stage"
              value={form.stage}
              onChange={(e) => setForm({ ...form, stage: e.target.value })}
            />
          </label>
          <label className="block text-sm">
            window days
            <Input
              aria-label="window days"
              type="number"
              value={form.window_days}
              onChange={(e) => setForm({ ...form, window_days: e.target.value })}
            />
          </label>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={create.isPending}>
              Create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CapabilitiesIndex() {
  const { data, isLoading, error } = useCapabilities();
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Capabilities</h2>
        <NewCapabilityDialog />
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {error && (
        <p className="text-sm text-destructive">{(error as Error).message}</p>
      )}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No capabilities yet — create one to start.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((cap) => (
          <CapabilityCard key={cap.id} cap={cap} />
        ))}
      </div>
    </div>
  );
}
