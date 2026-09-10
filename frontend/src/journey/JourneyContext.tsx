import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** App-wide guided journey: highlighted in the left product rail. */
export const JOURNEY_STEPS = [
  "Capabilities",
  "Setup",
  "Run",
  "Gaps",
  "Decide",
  "History",
] as const;

export type JourneyStep = (typeof JOURNEY_STEPS)[number];

type JourneyHandlers = {
  /** In-page step switcher when a capability detail view is mounted. */
  onSelect?: (step: JourneyStep) => void;
};

type JourneyValue = {
  current: JourneyStep;
  setCurrent: (step: JourneyStep) => void;
  /** Last capability in context — survives home so the left rail can deep-link. */
  capabilityId: string | null;
  setCapabilityId: (id: string | null) => void;
  handlers: JourneyHandlers;
  setHandlers: (next: JourneyHandlers) => void;
};

const JourneyContext = createContext<JourneyValue | null>(null);

export function JourneyProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<JourneyStep>("Capabilities");
  const [capabilityId, setCapabilityId] = useState<string | null>(null);
  const [handlers, setHandlersState] = useState<JourneyHandlers>({});

  const setHandlers = useCallback((next: JourneyHandlers) => {
    setHandlersState(next);
  }, []);

  const value = useMemo(
    () => ({
      current,
      setCurrent,
      capabilityId,
      setCapabilityId,
      handlers,
      setHandlers,
    }),
    [current, capabilityId, handlers, setHandlers],
  );

  return (
    <JourneyContext.Provider value={value}>{children}</JourneyContext.Provider>
  );
}

export function useJourney() {
  const ctx = useContext(JourneyContext);
  if (!ctx) throw new Error("useJourney requires JourneyProvider");
  return ctx;
}
