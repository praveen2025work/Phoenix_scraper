import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { DataTable } from "./DataTable";

test("renders headers and formatted cells", () => {
  render(
    <DataTable
      columns={[
        { key: "name", header: "Name" },
        {
          key: "rate",
          header: "Fail rate",
          format: (v) => `${Math.round(Number(v) * 100)}%`,
        },
      ]}
      rows={[{ name: "answer_relevance", rate: 0.05 }]}
    />,
  );
  expect(screen.getByRole("columnheader", { name: "Fail rate" })).toBeInTheDocument();
  expect(screen.getByText("5%")).toBeInTheDocument();
  expect(screen.getByText("answer_relevance")).toBeInTheDocument();
});

test("empty state when no rows", () => {
  render(<DataTable columns={[{ key: "name", header: "Name" }]} rows={[]} />);
  expect(screen.getByText(/no rows/i)).toBeInTheDocument();
});

test("renders a screen-reader caption when label is given", () => {
  render(
    <DataTable
      label="Question types by frequency"
      columns={[{ key: "name", header: "Name" }]}
      rows={[{ name: "why" }]}
    />,
  );
  expect(screen.getByText("Question types by frequency")).toBeInTheDocument();
});
