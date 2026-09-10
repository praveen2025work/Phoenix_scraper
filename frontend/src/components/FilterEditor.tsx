import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  type SpanFilter,
  useFilterPreview,
  usePatchCapability,
} from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const TEXT_FIELDS: { key: keyof SpanFilter; label: string; hint: string }[] = [
  { key: "project", label: "project", hint: "pnl-agent" },
  { key: "workflow_stage", label: "workflow stage", hint: "fobo_recon" },
  { key: "asset_class", label: "asset class", hint: "fx" },
  { key: "model_name", label: "model", hint: "claude-sonnet" },
  { key: "search", label: "search", hint: "recon" },
];

const MAX_SAMPLE_PROMPTS = 3;

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
  windowFrom,
  windowTo,
}: {
  capabilityId: string;
  initial: SpanFilter;
  windowDays: number;
  /** Operator-picked run window — preview must use this when set, not only windowDays. */
  windowFrom?: string;
  windowTo?: string;
}) {
  const [filter, setFilter] = useState<SpanFilter>(initial);
  const [anyText, setAnyText] = useState((initial.search_any ?? []).join("\n"));
  const patch = usePatchCapability(capabilityId);

  const searchAny = anyText
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const draft: SpanFilter = { ...filter, search_any: searchAny };
  const preview = useFilterPreview(useDebounced(draft), {
    windowDays,
    from: windowFrom
      ? new Date(`${windowFrom}T00:00:00.000Z`).toISOString()
      : undefined,
    to: windowTo
      ? new Date(`${windowTo}T23:59:59.999Z`).toISOString()
      : undefined,
  });
  const p = preview.data;
  const samples = (p?.sample_prompts ?? []).slice(0, MAX_SAMPLE_PROMPTS);

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

  const windowLabel =
    windowFrom && windowTo
      ? `${windowFrom} → ${windowTo}`
      : `last ${windowDays}d`;

  return (
    <div className="space-y-4" data-testid="filter-editor">
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2">
          {TEXT_FIELDS.map((f) => (
            <label key={f.key} className="text-[11px] text-muted-foreground">
              {f.label}
              <Input
                value={(filter[f.key] as string | null) ?? ""}
                onChange={(e) => set(f.key, e.target.value)}
                placeholder={f.hint}
                aria-label={f.label}
                className="mt-0.5 h-8"
              />
            </label>
          ))}
          <label className="text-[11px] text-muted-foreground sm:col-span-2">
            search any (one per line)
            <textarea
              value={anyText}
              onChange={(e) => setAnyText(e.target.value)}
              aria-label="search any patterns"
              rows={3}
              placeholder={"recon break\nunmatched trade"}
              className="mt-0.5 w-full rounded-md border border-border bg-background p-2
                         font-mono text-xs"
            />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={save} disabled={patch.isPending}>
            {patch.isPending ? "Saving…" : "Save filter"}
          </Button>
          <span className="text-[11px] text-muted-foreground">
            Save only — then Run now
          </span>
        </div>
      </div>

      <div className="space-y-2 border-t border-border/70 pt-3" data-testid="filter-preview">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h4 className="text-sm font-semibold tracking-tight">Preview</h4>
          <span className="text-[11px] text-muted-foreground">{windowLabel}</span>
        </div>

        {preview.isLoading ? (
          <p className="text-xs text-muted-foreground">Loading preview…</p>
        ) : preview.error ? (
          <p className="text-sm text-destructive" role="alert">
            {(preview.error as Error).message}
          </p>
        ) : p ? (
          <div className="space-y-2">
            <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums">
              <span>
                <strong>{p.n_spans}</strong>
                <span className="text-muted-foreground"> / {p.n_spans_in_store} spans</span>
              </span>
              <span>
                <strong>{p.n_llm_spans}</strong> LLM
              </span>
              <span>
                <strong>{p.n_users}</strong> users
              </span>
              <span>
                <strong>{p.n_sessions}</strong> sessions
              </span>
            </p>

            {p.n_spans === 0 ? (
              <p className="text-xs text-destructive" role="alert">
                Nothing matches — a run would find no spans.
              </p>
            ) : (
              <>
                {p.distinct.workflow_stage.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1 text-[11px]">
                    <span className="text-muted-foreground">stages:</span>
                    {p.distinct.workflow_stage.map((s) => (
                      <Badge key={s} className="px-1.5 py-0 text-[10px]">
                        {s}
                      </Badge>
                    ))}
                  </div>
                )}
                {samples.length > 0 && (
                  <ul className="space-y-0.5">
                    {samples.map((s, i) => (
                      <li
                        key={i}
                        className="truncate font-mono text-[11px] text-muted-foreground"
                      >
                        {s}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
