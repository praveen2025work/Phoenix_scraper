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

  // Home pins the highlight to Capabilities. Keep last capabilityId so the
  // left rail can deep-link Setup/Gaps/Decide/History (e.g. FOBO).
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
    <div className="relative z-0 flex min-h-full">
      <ProductRail />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur-md">
          <div className="flex w-full items-center justify-between gap-2 px-3 py-1.5 sm:gap-3 sm:px-4 lg:px-5">
            <div className="min-w-0">
              <Link
                to="/"
                className="font-display block shrink-0 text-lg font-semibold tracking-tight text-foreground hover:opacity-90 sm:text-xl"
              >
                Phoenix
              </Link>
              <p className="hidden text-[11px] text-muted-foreground sm:block">
                Capability evaluation
              </p>
            </div>

            <nav className="flex shrink-0 items-center gap-1.5 sm:gap-2" aria-label="App">
              {!atHome && (
                <Link
                  to="/"
                  className="rounded-md border border-border bg-card px-2 py-1 text-xs font-medium text-foreground hover:bg-accent sm:px-2.5 sm:text-sm"
                >
                  Capabilities
                </Link>
              )}
              <ThemeToggle />
            </nav>
          </div>
        </header>

        <main className="app-shell-main relative z-0 w-full flex-1 px-3 py-3 sm:px-4 lg:px-5 lg:py-4">
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
