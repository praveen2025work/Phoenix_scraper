/** Classify candidate/gap text as skill-shaped vs deterministic payloads. */

const USER_QUERY_RE =
  /USER\s+QUERY\s*:\s*(?:"([^"]+)"|'([^']+)'|([^\n"{}]+))/im;
const MCP_TOOL_RE = /\bmcp__[a-z0-9_-]+__[a-z0-9_-]+\b/i;
const SELECT_MCP_RE = /\bselect\s*:\s*mcp__/i;
const SQL_HEAD_RE =
  /^\s*(?:with\b.+\bselect\b|select\b|insert\b|update\b|delete\b|create\b|drop\b|alter\b|pragma\b|explain\b)\b/is;
const FILE_PATH_RE =
  /\b(?:file_path|filepath|document_id|documentid|s3:\/\/|s3_uri|object_key)\b/i;
const BEDROCK_RE =
  /\b(?:anthropic_version|bedrock|inferenceConfig|"messages"\s*:)/i;
const PARAM_KEYS_RE =
  /\b(?:endpoint|query|tool_name|toolName|parameters|params|arguments|input_schema|content_type)\b/i;

function matchUserQuery(text: string): string | null {
  const m = text.match(USER_QUERY_RE);
  if (!m) return null;
  const found = (m[1] || m[2] || m[3] || "").trim();
  return found || null;
}

function looksStructured(text: string): boolean {
  const s = text.trimStart();
  return (
    s.startsWith("{") ||
    s.startsWith("[") ||
    s.startsWith("'{") ||
    (s.includes("{") && (s.includes("'") || s.includes('"')))
  );
}

function looksLikeSqlBlob(text: string): boolean {
  const lower = text.toLowerCase();
  if (lower.includes("session_id") && (lower.includes("select") || lower.includes("from "))) {
    return true;
  }
  return lower.includes(" from ") && lower.includes(" where ") && text.includes(";");
}

function tryParseJson(text: string): unknown | null {
  const s = text.trim();
  if (!s) return null;
  const candidates = [s];
  if (s.startsWith("'") && s.endsWith("'")) candidates.push(s.slice(1, -1));
  for (const cand of candidates) {
    try {
      return JSON.parse(cand) as unknown;
    } catch {
      /* continue */
    }
  }
  return null;
}

function contentToText(content: unknown): string | null {
  if (typeof content === "string") {
    return (matchUserQuery(content) || content).trim() || null;
  }
  if (!Array.isArray(content)) return null;
  const parts: string[] = [];
  for (const block of content) {
    if (typeof block === "string") parts.push(block);
    else if (block && typeof block === "object") {
      const rec = block as Record<string, unknown>;
      const text = rec.text ?? rec.content;
      if (typeof text === "string") parts.push(text);
    }
  }
  const joined = parts.join("\n").trim();
  if (!joined) return null;
  return matchUserQuery(joined) || joined;
}

function userTextFromPayload(payload: unknown): string | null {
  if (typeof payload === "string") {
    return matchUserQuery(payload);
  }
  if (Array.isArray(payload)) {
    for (let i = payload.length - 1; i >= 0; i--) {
      const item = payload[i];
      if (item && typeof item === "object") {
        const rec = item as Record<string, unknown>;
        if (String(rec.role ?? "").toLowerCase() === "user") {
          return contentToText(rec.content);
        }
      }
    }
    return null;
  }
  if (!payload || typeof payload !== "object") return null;
  const obj = payload as Record<string, unknown>;
  for (const key of ["user_query", "userQuery", "question", "prompt"]) {
    const val = obj[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  const messages = obj.messages;
  if (Array.isArray(messages)) {
    for (let i = messages.length - 1; i >= 0; i--) {
      const item = messages[i];
      if (item && typeof item === "object") {
        const rec = item as Record<string, unknown>;
        if (String(rec.role ?? "").toLowerCase() === "user") {
          const text = contentToText(rec.content);
          if (text) return text;
        }
      }
    }
  }
  for (const key of ["system", "instructions", "input"]) {
    const val = obj[key];
    if (typeof val === "string") {
      const marker = matchUserQuery(val);
      if (marker) return marker;
    }
  }
  return null;
}

function payloadMarkers(text: string): boolean {
  const s = text.trim();
  if (!s) return false;
  if (SELECT_MCP_RE.test(s) || MCP_TOOL_RE.test(s)) return true;
  if (SQL_HEAD_RE.test(s) || looksLikeSqlBlob(s)) return true;
  if (FILE_PATH_RE.test(s) && looksStructured(s)) return true;
  if (BEDROCK_RE.test(s) && looksStructured(s)) return true;
  if (looksStructured(s) && PARAM_KEYS_RE.test(s)) {
    const parsed = tryParseJson(s);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const keys = new Set(
        Object.keys(parsed as Record<string, unknown>).map((k) => k.toLowerCase()),
      );
      const hit = [
        "query",
        "tool_name",
        "toolname",
        "parameters",
        "params",
        "arguments",
        "endpoint",
        "file_path",
        "filepath",
        "document_id",
        "input",
      ].some((k) => keys.has(k));
      if (hit) return true;
    }
    if (s.trimStart().startsWith("{") || s.trimStart().startsWith("'{")) return true;
  }
  return false;
}

/** Pull USER QUERY / last user message out of Bedrock-style wrappers. */
export function extractUserPrompt(text: string): string {
  const raw = (text || "").trim();
  if (!raw) return "";
  const marker = matchUserQuery(raw);
  if (marker) return marker;
  const parsed = tryParseJson(raw);
  if (parsed != null) {
    const fromJson = userTextFromPayload(parsed);
    if (fromJson) return fromJson.trim();
  }
  if (looksStructured(raw)) {
    const scraped = matchUserQuery(raw);
    if (scraped) return scraped;
  }
  return raw;
}

export function displayCandidateTitle(text: string, maxLen = 200): string {
  const cleaned = extractUserPrompt(text).trim();
  if (!cleaned) return "";
  if (cleaned.length <= maxLen) return cleaned;
  return `${cleaned.slice(0, maxLen - 1).trimEnd()}…`;
}

export function isDeterministicShaped(text: string): boolean {
  const raw = (text || "").trim();
  if (!raw) return false;
  const extracted = extractUserPrompt(raw);
  if (extracted && extracted !== raw && !payloadMarkers(extracted)) {
    return false;
  }
  return payloadMarkers(extracted || raw);
}

export function isSkillShaped(text: string): boolean {
  const raw = (text || "").trim();
  if (!raw) return false;
  return !isDeterministicShaped(raw);
}

/** Effective ladder lane for UI: trusts rung, rehomes mislabeled skill payloads. */
export function effectiveRung(
  rung: string,
  title: string,
): "skill" | "deterministic" {
  if (rung === "deterministic") return "deterministic";
  if (rung === "skill" && isDeterministicShaped(title)) return "deterministic";
  if (rung === "skill" || isSkillShaped(title)) return "skill";
  return "deterministic";
}
