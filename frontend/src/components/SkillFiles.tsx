import { useRef, useState } from "react";
import { toast } from "sonner";
import { useDeleteSkillFile, useSkillFiles, useUploadSkillFile } from "@/api/hooks";
import { Panel } from "@/components/Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** A capability's own `skills/<name>.md` files: what the miner matches asks against.
 *  Upload a file (or paste one) and the next run picks it up. */
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

  return (
    <div className="space-y-4">
      <Panel
        title="Skill files"
        subtitle="What you already handle — matched against asks on every run"
        isLoading={skills.isLoading}
        error={skills.error}
      >
        {skills.data?.length ? (
          <ul className="divide-y divide-border">
            {skills.data.map((s) => (
              <li key={s.filename} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{s.filename}</p>
                  <p className="truncate text-xs text-muted-foreground">
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
          <p className="text-sm text-muted-foreground" role="status">
            No skill files yet. Upload a{" "}
            <code className="text-xs">.md</code> below (needs a{" "}
            <code className="text-xs">name:</code> in frontmatter), then click{" "}
            <strong>Run now</strong> above. Without skills, the run can still cluster
            asks and suggest new skills — but it cannot tell you what your docs already
            cover.
          </p>
        )}
      </Panel>

      <Panel
        title="Add a skill file"
        subtitle="Markdown with YAML frontmatter — needs at least a name: field"
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInput}
              type="file"
              accept=".md,text/markdown"
              aria-label="upload skill file"
              onChange={onPick}
              className="text-sm file:mr-3 file:rounded-md file:border file:border-border
                         file:bg-muted file:px-3 file:py-1.5 file:text-sm"
            />
            {upload.isPending && (
              <span className="text-xs text-muted-foreground">uploading…</span>
            )}
          </div>

          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground">
              or paste one
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
                rows={10}
                placeholder={"---\nname: fx-recon-triage\ndescription: …\nexample_prompts:\n  - …\n---\n"}
                className="w-full rounded-md border border-border bg-background p-2
                           font-mono text-xs"
              />
              <Button
                size="lg"
                disabled={!filename.trim() || !content.trim() || upload.isPending}
                onClick={() => send(filename.trim(), content)}
              >
                Save skill file
              </Button>
            </div>
          </details>
        </div>
      </Panel>
    </div>
  );
}
