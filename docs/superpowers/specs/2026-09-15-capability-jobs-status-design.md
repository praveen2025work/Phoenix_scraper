# Capability Jobs status step

## Problem
Operators could not see in-flight job status in the UI. Version History only lists finished `capability_runs`. Live progress lived only on the Running step, and leaving that step dropped the tracked `jobId`.

## Decision
Add a **Jobs** wizard step (option A) between Results and History.

## Behavior
- Lists `GET /capabilities/{id}/jobs` (queued / running / done / error).
- Polls while any job is queued or running.
- Actions: **Watch** (resume Running for that jobId), **Cancel**, **Open results** (done + run_id).
- Navigating to Jobs does **not** clear `jobId`, so an in-flight run remains watchable.
- Deep link: `?step=jobs`.

## Non-goals
- Does not replace Version History.
- No global cross-capability job board.
