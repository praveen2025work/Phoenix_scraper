import { describe, expect, test } from "vitest";
import {
  displayCandidateTitle,
  effectiveRung,
  extractUserPrompt,
  isDeterministicShaped,
  isSkillShaped,
} from "./promptShape";

describe("extractUserPrompt", () => {
  test("pulls USER QUERY marker", () => {
    expect(
      extractUserPrompt("System preamble\n\nUSER QUERY: Why is recon break unmatched?\n\n"),
    ).toBe("Why is recon break unmatched?");
  });

  test("pulls last user message from Bedrock JSON", () => {
    const payload = JSON.stringify({
      anthropic_version: "bedrock-2023-05-31",
      messages: [{ role: "user", content: [{ text: "Show FX breaks over 100k" }] }],
    });
    expect(extractUserPrompt(payload)).toBe("Show FX breaks over 100k");
  });
});

describe("shape classification", () => {
  test("MCP / SQL / file_path are deterministic", () => {
    expect(
      isDeterministicShaped(
        "{'query': 'select:mcp__data-analysis__query_data', 'args': {}}",
      ),
    ).toBe(true);
    expect(
      isDeterministicShaped(
        "SELECT * FROM breaks WHERE session_id = 'x';",
      ),
    ).toBe(true);
    expect(
      isDeterministicShaped(
        JSON.stringify({ file_path: "s3://bucket/a.csv", document_id: "d1" }),
      ),
    ).toBe(true);
  });

  test("user questions are skill-shaped", () => {
    expect(isSkillShaped("Why is there a recon break of 100k?")).toBe(true);
    expect(
      isSkillShaped(
        "USER QUERY: Why is there a recon break?\n\nanthropic_version: bedrock",
      ),
    ).toBe(true);
  });

  test("effectiveRung rehomes mislabeled skill payloads", () => {
    expect(
      effectiveRung(
        "skill",
        "{'query': 'select:mcp__database__list_tables'}",
      ),
    ).toBe("deterministic");
    expect(effectiveRung("skill", "why recon break")).toBe("skill");
  });

  test("displayCandidateTitle prefers extracted query", () => {
    expect(
      displayCandidateTitle(
        "ignore\nUSER QUERY: Clean question please\n\nmore",
      ),
    ).toBe("Clean question please");
  });
});
