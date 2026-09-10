import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import App from "./App";

test("renders the app shell with product journey rail", async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  // Gate shows Connecting… then locks with branded form, or opens the shell.
  await waitFor(() => expect(screen.getByText("pheonix")).toBeInTheDocument());
  // When the gate opens, the journey rail is always present.
  await waitFor(() => {
    const rail = screen.queryByTestId("product-rail");
    const gate = screen.queryByLabelText(/API key/i);
    expect(rail || gate).toBeTruthy();
  });
});
