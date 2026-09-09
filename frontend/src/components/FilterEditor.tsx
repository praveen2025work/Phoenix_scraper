import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  type SpanFilter,
  useFilterPreview,
  usePatchCapability,
} from "@/api/hooks";
import { Panel } from "@/components/Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const TEXT_FIELDS: { key: keyof SpanFilter; label: string; hint: string }[] = [
  { key: "project", label: "project", hint: "pnl-agent" },
  { key: "workflow_stage", label: "workflow stage", hint: "fobo_recon" },
  { key: "asset_class", label: "asset class", hint: "fx" },
  { key: "model_name", label: "model", hint: "claude-sonnet" },
  { key: "search", label: "search (must contain)", hint: "recon" },
];

/** Debounce so every keystroke doesn't fire a preview request. */
function useDebounced<T>(value: T, ms = 400): T {
  const [held, setHeld] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setHeld(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return held;
}

export function FilterEditor({
  capabilityId,
  initial,
  windowDays,
}: {
  capabilityId: string;
  initial: SpanFilter;
  windowDays: number;
}) {
  const [filter, setFilter] = useState<SpanFilter>(initial);
  const [anyText, setAnyText] = useState((initial.search_any ?? []).join("\n"));
  const patch = usePatchCapability(capabilityId);

  const searchAny = anyText
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const draft: SpanFilter = { ...filter, search_any: searchAny };
  const preview = useFilterPreview(useDebounced(draft), windowDays);
  const p = preview.data;

  function set(key: keyof SpanFilter, value: string) {
    setFilter((f) => ({ ...f, [key]: value.trim() ? value : null }));
  }

  function save() {
    patch.mutate(
      { filter: draft },
      {
        onSuccess: () => toast.success("Filter saved — run it to see the effect"),
        onError: (e) => toast.error((e as Error).message),
      },
    );
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Span filter"
        subtitle="what this capability looks at — edit, watch the match count, then save"
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {TEXT_FIELDS.map((f) => (
            <label key={f.key} className="text-xs text-muted-foreground">
              {f.label}
              <Input
                value={(filter[f.key] as string | null) ?? ""}
                onChange={(e) => set(f.key, e.target.value)}
                placeholder={f.hint}
                aria-label={f.label}
                className="mt-1"
              />
            </label>
          ))}
          <label className="text-xs text-muted-foreground sm:col-span-2">
            search any of these (one per line — a span matches if it contains ANY)
            <textarea
              value={anyText}
              onChange={(e) => setAnyText(e.target.value)}
              aria-label="search any patterns"
              rows={4}
              placeholder={"recon break\nunmatched trade"}
              className="mt-1 w-full rounded-md border border-border bg-background p-2
                         font-mono text-xs"
            />
          </label>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <Button onClick={save} disabled={patch.isPending}>
            {patch.isPending ? "Saving…" : "Save filter"}
          </Button>
          <span className="text-xs text-muted-foreground">
            saving does not run it — hit Run now afterwards
          </span>
        </div>
      </Panel>

      <Panel
        title="Preview"
        subtitle={`what this filter catches in the last ${windowDays} days — nothing is saved or run`}
        isLoading={preview.isLoading}
        error={preview.error}
      >
        {p && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-4 text-sm">
              <span>
                <strong className="tabular-nums">{p.n_spans}</strong> spans
                <span className="text-muted-foreground"> of {p.n_spans_in_store}</span>
              </span>
              <span>
                <strong className="tabular-nums">{p.n_llm_spans}</strong> LLM
              </span>
              <span>
                <strong className="tabular-nums">{p.n_users}</strong> users
              </span>
              <span>
                <strong className="tabular-nums">{p.n_sessions}</strong> sessions
              </span>
            </div>

            {p.n_spans === 0 ? (
              <p className="text-sm text-destructive" role="alert">
                Nothing matches. A run with this filter would find no spans.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-1 text-xs">
                  <span className="text-muted-foreground">stages caught:</span>
                  {p.distinct.workflow_stage.length ? (
                    p.distinct.workflow_stage.map((s) => <Badge key={s}>{s}</Badge>)
                  ) : (
                    <span className="text-muted-foreground">
                      none — these spans carry no workflow_stage
                    </span>
                  )}
                </div>
                <ul className="space-y-1">
                  {p.sample_prompts.map((s, i) => (
                    <li key={i} className="truncate font-mono text-xs text-muted-foreground">
                      {s}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
