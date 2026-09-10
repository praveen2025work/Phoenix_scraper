import { useRef, useState } from "react";
import { toast } from "sonner";
import { useDeleteSkillFile, useSkillFiles, useUploadSkillFile } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Capability `skills/<name>.md` files matched against asks on every run. */
export function SkillFiles({ capabilityId }: { capabilityId: string }) {
  const skills = useSkillFiles(capabilityId);
  const upload = useUploadSkillFile(capabilityId);
  const remove = useDeleteSkillFile(capabilityId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");

  function send(name: string, body: string) {
    upload.mutate(
      { filename: name, content: body },
      {
        onSuccess: (row) => {
          toast.success(`${row.filename} saved — skill "${row.name}"`);
          setFilename("");
          setContent("");
          if (fileInput.current) fileInput.current.value = "";
        },
        onError: (e) => toast.error((e as Error).message),
      },
    );
  }

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    send(file.name, await file.text());
  }

  if (skills.isLoading) {
    return <p className="text-xs text-muted-foreground">Loading skills…</p>;
  }
  if (skills.error) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {(skills.error as Error).message}
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="skill-files">
      {skills.data?.length ? (
        <ul className="divide-y divide-border rounded-md border border-border">
          {skills.data.map((s) => (
            <li key={s.filename} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{s.filename}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {s.description || "no description"} · {s.n_example_prompts} example
                  {s.n_example_prompts === 1 ? "" : "s"}
                </p>
              </div>
              <Badge variant={s.valid ? "ready" : "warn"}>
                {s.valid ? s.name : "unreadable"}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`delete ${s.filename}`}
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(s.filename, {
                    onSuccess: () => toast.success(`${s.filename} deleted`),
                    onError: (e) => toast.error((e as Error).message),
                  })
                }
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground" role="status">
          No skill files yet — upload a <code className="text-[11px]">.md</code> with{" "}
          <code className="text-[11px]">name:</code> frontmatter.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          type="file"
          accept=".md,text/markdown"
          aria-label="upload skill file"
          onChange={onPick}
          className="text-xs file:mr-2 file:rounded-md file:border file:border-border
                     file:bg-muted file:px-2.5 file:py-1 file:text-xs"
        />
        {upload.isPending && (
          <span className="text-xs text-muted-foreground">uploading…</span>
        )}
      </div>

      <details className="group">
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          Paste skill content
        </summary>
        <div className="mt-2 space-y-2">
          <Input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="fx-recon-triage.md"
            aria-label="skill filename"
            className="max-w-xs"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            aria-label="skill file content"
            rows={6}
            placeholder={"---\nname: fx-recon-triage\ndescription: …\nexample_prompts:\n  - …\n---\n"}
            className="w-full rounded-md border border-border bg-background p-2
                       font-mono text-xs"
          />
          <Button
            size="sm"
            disabled={!filename.trim() || !content.trim() || upload.isPending}
            onClick={() => send(filename.trim(), content)}
          >
            Save skill file
          </Button>
        </div>
      </details>
    </div>
  );
}
