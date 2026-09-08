import { Suspense, lazy } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { ApiKeyGate } from "./components/ApiKeyGate";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ThemeToggle } from "./components/ThemeToggle";
import { CandidateDetail } from "./routes/CandidateDetail";
import { CapabilitiesIndex } from "./routes/CapabilitiesIndex";
import { CapabilityDetail } from "./routes/CapabilityDetail";

// The analytics tab pulls in recharts — load it only when visited.
const Analytics = lazy(() =>
  import("./routes/Analytics").then((m) => ({ default: m.Analytics })),
);

export default function App() {
  return (
    <ApiKeyGate>
      <div className="min-h-full">
        <header className="flex items-center justify-between border-b border-border px-6 py-3">
          <Link to="/" className="font-semibold">
            pheonix
          </Link>
          <ThemeToggle />
        </header>
        <main className="mx-auto max-w-6xl p-6">
          <ErrorBoundary>
            <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
              <Routes>
                <Route path="/" element={<CapabilitiesIndex />} />
                <Route path="/c/:id" element={<CapabilityDetail />} />
                <Route path="/c/:id/analytics" element={<Analytics />} />
                <Route path="/c/:id/candidate/:cid" element={<CandidateDetail />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
        <Toaster position="bottom-right" />
      </div>
    </ApiKeyGate>
  );
}
