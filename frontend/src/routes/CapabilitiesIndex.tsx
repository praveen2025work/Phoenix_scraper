import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  type CapabilitySummary,
  useCapabilities,
  useCreateCapability,
} from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { PageHeader } from "@/components/PageHeader";
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
import { useJourney } from "@/journey/JourneyContext";

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
  const skillReady = readyCount(cap.candidates.skill);
  const detReady = readyCount(cap.candidates.deterministic);
  return (
    <Card className="panel-enter flex flex-col border-border/80 bg-card transition-[transform,box-shadow] duration-150 hover:-translate-y-0.5 hover:shadow-md">
      <CardHeader className="space-y-1 pb-1 sm:p-4">
        <CardTitle className="flex items-start justify-between gap-2 font-display text-lg font-semibold tracking-tight sm:text-xl">
          <Link to={`/c/${cap.id}`} className="hover:underline">
            {cap.name}
          </Link>
          <Badge variant={cap.status === "active" ? "default" : "warn"}>
            {cap.status}
          </Badge>
        </CardTitle>
        <p className="text-xs text-muted-foreground">{filterSummary(cap.filter)}</p>
      </CardHeader>
      <CardContent className="mt-auto flex flex-1 flex-col gap-3 pt-0 sm:px-4 sm:pb-4">
        <div className="space-y-1 text-sm">
          <p className="text-xs text-muted-foreground">
            {last?.run_id
              ? `Last version ${last.run_id.slice(0, 16)} · ${last.status}`
              : "No versions yet — run once to see skill gaps"}
          </p>
          <p className="text-sm text-foreground">
            Promote to skill:{" "}
            <strong className="tabular-nums">{skillReady}</strong> ready
            <span className="mx-1.5 text-muted-foreground">·</span>
            Make deterministic:{" "}
            <strong className="tabular-nums">{detReady}</strong> ready
          </p>
        </div>
        <Button asChild size="lg" className="w-full sm:w-auto">
          <Link to={`/c/${cap.id}`}>
            {last?.run_id ? "Open & review gaps" : "Set up & run"}
          </Link>
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
        <Button size="lg">New capability</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New capability</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Scoped workflow (e.g. FOBO). Upload skills, run a window, then promote.
        </p>
        <form className="space-y-3" onSubmit={submit}>
          <label className="block text-sm font-medium">
            id
            <Input
              aria-label="id"
              value={form.id}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              required
              className="mt-1"
            />
          </label>
          <label className="block text-sm font-medium">
            name
            <Input
              aria-label="name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="mt-1"
            />
          </label>
          <label className="block text-sm font-medium">
            workflow stage
            <Input
              aria-label="workflow stage"
              value={form.stage}
              onChange={(e) => setForm({ ...form, stage: e.target.value })}
              className="mt-1"
            />
          </label>
          <label className="block text-sm font-medium">
            window days
            <Input
              aria-label="window days"
              type="number"
              value={form.window_days}
              onChange={(e) => setForm({ ...form, window_days: e.target.value })}
              className="mt-1"
            />
          </label>
          <div className="flex justify-end gap-2 pt-1">
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" size="lg" disabled={create.isPending}>
              Create &amp; open setup
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CapabilitiesIndex() {
  const { data, isLoading, error } = useCapabilities();
  const { capabilityId, setCapabilityId } = useJourney();

  // Seed rail deep-links when nothing is in context yet (e.g. fresh home load).
  useEffect(() => {
    if (capabilityId || !data?.length) return;
    setCapabilityId(data[0].id);
  }, [data, capabilityId, setCapabilityId]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Capabilities"
        outcome="Pick a scope → run a window → close skill gaps → promote."
        actions={<NewCapabilityDialog />}
      />

      <OutcomeBanner title="Loop" data-testid="home-outcome" dismissible dismissKey="home-loop">
        Choose a capability → upload skills & window → Run → promote to skill or make
        deterministic.
      </OutcomeBanner>

      <section className="space-y-3">
        <div className="flex items-end justify-between gap-3">
          <h2 className="font-display text-lg font-semibold tracking-tight">
            Your capabilities
          </h2>
          {data && (
            <p className="text-xs text-muted-foreground">
              {data.length} scoped workflow{data.length === 1 ? "" : "s"}
            </p>
          )}
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && (
          <p className="text-sm text-destructive">{(error as Error).message}</p>
        )}
        {data && data.length === 0 && (
          <div className="section-surface-strong px-4 py-8 text-center">
            <p className="font-display text-lg font-semibold text-foreground">
              No capabilities yet
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Create one to start — then set up skills and run your first version.
            </p>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data?.map((cap) => (
            <CapabilityCard key={cap.id} cap={cap} />
          ))}
        </div>
      </section>
    </div>
  );
}
