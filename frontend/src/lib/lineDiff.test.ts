import { expect, test } from "vitest";
import { computeLineDiff, toSplitRows } from "./lineDiff";

test("marks added and removed lines", () => {
  const rows = computeLineDiff("a\nb\nc\n", "a\nx\nc\n");
  expect(rows).toEqual([
    { type: "equal", text: "a", oldLine: 1, newLine: 1 },
    { type: "remove", text: "b", oldLine: 2, newLine: null },
    { type: "add", text: "x", oldLine: null, newLine: 2 },
    { type: "equal", text: "c", oldLine: 3, newLine: 3 },
  ]);
});

test("all lines added when there is no current content", () => {
  const rows = computeLineDiff("", "hello\nworld\n");
  expect(rows).toEqual([
    { type: "add", text: "hello", oldLine: null, newLine: 1 },
    { type: "add", text: "world", oldLine: null, newLine: 2 },
  ]);
});

test("identical content yields only equal rows", () => {
  const rows = computeLineDiff("same\n", "same\n");
  expect(rows).toEqual([{ type: "equal", text: "same", oldLine: 1, newLine: 1 }]);
});

test("toSplitRows pairs removes and adds", () => {
  const rows = toSplitRows(computeLineDiff("a\nb\n", "a\nc\n"));
  expect(rows).toEqual([
    {
      left: { type: "equal", text: "a", oldLine: 1, newLine: 1 },
      right: { type: "equal", text: "a", oldLine: 1, newLine: 1 },
    },
    {
      left: { type: "remove", text: "b", oldLine: 2, newLine: null },
      right: { type: "add", text: "c", oldLine: null, newLine: 2 },
    },
  ]);
});
