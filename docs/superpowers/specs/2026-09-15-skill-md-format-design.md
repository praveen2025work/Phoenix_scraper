# Skill Markdown format support

## Problem

Capability skills are `.md` files, but matching only reads YAML frontmatter.
Plain Markdown (title + procedure + example bullets) is skipped or rejected on
upload, so operators cannot use normal MD authoring for matching.

## Goal

Accept Markdown skill files for matching whether or not they use YAML
frontmatter. Frontmatter remains the preferred, explicit source when present.

## Approaches

1. **Markdown-native fallback (recommended)** — Keep frontmatter parsing; when
   missing or incomplete, derive `name` / `description` / `example_prompts` /
   `keywords` from MD structure (H1, first paragraph, headed lists).
2. **Body-as-blob** — Feed the entire MD body into fuzzy/BM25. Simple, but noisy
   and weak for coverage’s example-prompt checks.
3. **YAML-only (status quo)** — No change; operators must keep writing frontmatter.

## Design (option 1)

### Parse order for each `.md`

1. If YAML frontmatter parses and has `name`, use those fields.
2. Fill any empty optional fields from the Markdown body.
3. If there is no usable frontmatter `name`, derive:
   - **name**: first `# Heading` slugified, else file stem (`fx-recon-triage.md` → `fx-recon-triage`)
   - **description**: first non-empty paragraph after the title
   - **example_prompts**: bullets under headings matching
     `example` / `prompt` / `question` (case-insensitive); else lines that look
     like questions (`?` or leading `Q:`)
   - **keywords**: bullets under a `Keywords` heading, else `distinctive_words`
     from name + description + examples

### Upload / list API

- Valid when a `SkillEntry` can be built (name from frontmatter, H1, or filename).
- Reject only empty/whitespace content.
- UI copy: “`.md` with frontmatter **or** Markdown title / examples”.

### Strengthen / merge

- Frontmatter files: unchanged merge behavior.
- Plain MD: prepend a frontmatter block with merged prompts/keywords and keep
  the original body (migrates the file to the hybrid format on purpose).

### Non-goals

- Do not change the shared `skills_catalog.yaml` format.
- Do not require LLM parsing of prose.
