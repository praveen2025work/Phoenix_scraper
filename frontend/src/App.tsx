import { Suspense, lazy, useEffect } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { ApiKeyGate } from "./components/ApiKeyGate";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ProductRail } from "./components/ProductRail";
import { ThemeToggle } from "./components/ThemeToggle";
import { JourneyProvider, useJourney } from "./journey/JourneyContext";
import { CandidateDetail } from "./routes/CandidateDetail";
import { CapabilitiesIndex } from "./routes/CapabilitiesIndex";
import { CapabilityDetail } from "./routes/CapabilityDetail";

// The analytics tab pulls in recharts — load it only when visited.
const Analytics = lazy(() =>
  import("./routes/Analytics").then((m) => ({ default: m.Analytics })),
);

function AppShell() {
  const { pathname } = useLocation();
  const { setCurrent, setHandlers } = useJourney();
  const atHome = pathname === "/";
  const onCapability = pathname.startsWith("/c/");

  // Home pins the highlight to Capabilities. Keep last capabilityId so the rail
  // can deep-link Setup/Gaps/Decide/History — only clear the in-page onSelect.
  useEffect(() => {
    if (atHome) {
      setCurrent("Capabilities");
      setHandlers({});
      return;
    }
    if (!onCapability) {
      setHandlers({});
    }
  }, [atHome, onCapability, setCurrent, setHandlers]);

  return (
    <div className="relative z-0 min-h-full">
      <header className="sticky top-0 z-20 border-b border-border bg-background/90 backdrop-blur-md">
        <div className="flex w-full items-center justify-between gap-3 px-3 py-2.5 sm:px-5 lg:px-6">
          <div className="min-w-0">
            <Link
              to="/"
              className="font-display text-xl font-semibold tracking-tight text-foreground hover:opacity-90"
            >
              pheonix
            </Link>
            <p className="truncate text-xs text-muted-foreground">
              {atHome
                ? "Pick a capability → run → close skill gaps"
                : "Setup → run → gaps → decide → history"}
            </p>
          </div>
          <nav className="flex shrink-0 items-center gap-3" aria-label="App">
            {!atHome && (
              <Link
                to="/"
                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent"
              >
                All capabilities
              </Link>
            )}
            <ThemeToggle />
          </nav>
        </div>
      </header>

      <div className="relative z-0 flex w-full flex-col md:flex-row">
        <ProductRail />
        <main className="app-shell-main relative z-0 flex-1 px-3 py-4 sm:px-5 lg:px-6 lg:py-5">
          <div className="mx-auto w-full max-w-7xl">
            <ErrorBoundary>
              <Suspense
                fallback={
                  <p className="text-sm text-muted-foreground">Loading…</p>
                }
              >
                <Routes>
                  <Route path="/" element={<CapabilitiesIndex />} />
                  <Route path="/c/:id" element={<CapabilityDetail />} />
                  <Route path="/c/:id/analytics" element={<Analytics />} />
                  <Route
                    path="/c/:id/candidate/:cid"
                    element={<CandidateDetail />}
                  />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </div>
        </main>
      </div>
      <Toaster position="bottom-right" />
    </div>
  );
}

export default function App() {
  return (
    <ApiKeyGate>
      <JourneyProvider>
        <AppShell />
      </JourneyProvider>
    </ApiKeyGate>
  );
}
