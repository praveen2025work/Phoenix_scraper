# Flow diagrams

End-to-end capability run flow and Decide lane segregation.

---

## 1. End-to-end run flow

```mermaid
sequenceDiagram
  participant SPA as SPA CapabilityDetail
  participant API as FastAPI
  participant Store as SQLite Store
  participant W as JobWorker
  participant PX as Phoenix client
  participant Eng as capability_run

  SPA->>API: POST /capabilities/{id}/jobs {from,to}
  Note over API: Requires closed window to > from
  API->>Store: enqueue_job queued
  API-->>SPA: 202 job_id
  loop poll ~1.5s
    SPA->>API: GET .../jobs/{job_id}
    API->>Store: get_job
    API-->>SPA: state stage progress
  end
  W->>Store: claim_next_job → running
  W->>Eng: run_capabilities(client, from, to)
  Eng->>Store: upsert_capability
  Eng->>PX: scrape_once per distinct filter.project
  PX-->>Eng: rows flattened → upsert_spans
  Note over Eng: Offline if client unavailable
  Eng->>Store: spans_frame capability filter + window
  Note over Eng: in-scope subset of raw store
  Eng->>Eng: costs evaluate clusters match coverage
  Eng->>Eng: detect_rung1 / detect_rung2
  Eng->>Store: update candidates lifecycle
  Eng->>Store: record_capability_run + cluster snapshots
  Eng->>Store: set_analytics_snapshot
  W->>Store: finish_job done + run_id
  SPA->>API: GET run results / candidates
  API-->>SPA: Results + Decide queues
```

### Stage map (job progress)

| Stage | Approx progress | Work |
| --- | --- | --- |
| `queued` | 0 | Waiting for worker claim |
| `scraping` | ~0.1 | Pull Phoenix (or skip offline) |
| `analyzing` | ~0.45 | In-scope filter, costs, eval, clusters |
| `matching` | ~0.7 | Skills match, coverage, ladder updates |
| `done` / `error` | 1 | Terminal |

### Promotion queue after record

```mermaid
flowchart TD
  record[record_capability_run] --> cand[Candidates in Store]
  cand --> ready{status ready?}
  ready -->|yes| decide[Decide column]
  decide --> accept[accept]
  accept --> write[Write file / Write draft]
  write --> promoted[status promoted + artifact paths]
  ready -->|reject / snooze| parked[rejected / snoozed]
```

---

## 2. Decide — skill vs deterministic lanes

```mermaid
flowchart TB
  cands[Live candidates for capability]
  cands --> eff{effectiveRung rung, title}

  eff -->|skill| skillLane[Skill lane · Rung 1]
  eff -->|deterministic| detLane[Deterministic lane · Rung 2]

  subgraph skillPath [Skill lane]
    sD[Decide ready]
    sW[Write file accepted]
    sP[Done promoted]
    sD --> sW --> sP
  end

  subgraph detPath [Deterministic lane]
    dD[Decide ready]
    dW[Write draft accepted]
    dP[Done promoted]
    dD --> dW --> dP
  end

  skillLane --> skillPath
  detLane --> detPath
```

### Classification inputs

```mermaid
flowchart LR
  text[Cluster representative / candidate title]
  text --> extract[extract_user_prompt]
  extract --> shape{is_deterministic_shaped?}
  shape -->|no| skillShaped[Skill-shaped → Rung 1 / skill gaps]
  shape -->|yes| detShaped[Deterministic-shaped → Rung 2 lane]
```

| Signal | Skill lane | Deterministic lane |
| --- | --- | --- |
| Typical text | Natural-language user questions | MCP tool selects, SQL, file_path, param dicts, unextracted Bedrock JSON |
| Detection | `detect_rung1` requires `is_skill_shaped` | `detect_rung2` scores all clusters’ answer stability |
| UI re-home | — | Skill-rung + deterministic title → deterministic lane |
| Promote | `skills/<stem>.md` draft | `deterministic/` Python + notes |

Backend and frontend share the same shape rules (`prompt_shape.py` /
`frontend/src/lib/promptShape.ts`).
