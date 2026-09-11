import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "@/components/StatusBadge";
import {
  candidateStatusVariant,
  jobStatusVariant,
  statusBadgeVariant,
} from "@/lib/statusStyles";

test("candidate statuses map to distinct badge variants", () => {
  expect(candidateStatusVariant("new")).toBe("new");
  expect(candidateStatusVariant("accumulating")).toBe("accumulating");
  expect(candidateStatusVariant("insufficient_data")).toBe("insufficient");
  expect(candidateStatusVariant("ready")).toBe("ready");
  expect(candidateStatusVariant("accepted")).toBe("accepted");
  expect(candidateStatusVariant("promoted")).toBe("promoted");
  expect(candidateStatusVariant("rejected")).toBe("rejected");
  expect(candidateStatusVariant("snoozed")).toBe("snoozed");
  expect(candidateStatusVariant("stale")).toBe("stale");
  expect(candidateStatusVariant("unknown")).toBe("outline");
});

test("job statuses map to ok/partial/error", () => {
  expect(jobStatusVariant("ok")).toBe("ok");
  expect(jobStatusVariant("partial")).toBe("partial");
  expect(jobStatusVariant("error")).toBe("error");
  expect(jobStatusVariant("failed")).toBe("error");
  expect(jobStatusVariant("queued")).toBe("info");
  expect(jobStatusVariant("running")).toBe("info");
  expect(jobStatusVariant("done")).toBe("ok");
  expect(jobStatusVariant(null)).toBe("outline");
});

test("statusBadgeVariant covers candidate and job keys", () => {
  expect(statusBadgeVariant("ready")).toBe("ready");
  expect(statusBadgeVariant("ok")).toBe("ok");
  expect(statusBadgeVariant("active")).toBe("default");
  expect(statusBadgeVariant("paused")).toBe("warn");
  expect(statusBadgeVariant("latest")).toBe("info");
  expect(statusBadgeVariant("older")).toBe("outline");
});

test("StatusBadge renders status text and data attribute", () => {
  render(<StatusBadge status="accepted" />);
  const el = screen.getByText("accepted");
  expect(el).toHaveAttribute("data-status", "accepted");
  expect(el.className).toMatch(/uppercase/);
  expect(el.className).toMatch(/tracking-wide/);
});
