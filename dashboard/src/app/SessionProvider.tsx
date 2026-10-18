import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { sessionSchema, type Session } from "../contracts/schemas";
import { ApiError } from "../lib/api";
import { sessionService, validate } from "../services/platform";
import { queryClient } from "./queryClient";

type Status = "loading" | "authenticated" | "anonymous" | "unavailable";
type SessionState = {
  status: Status;
  session: Session | null;
  setupRequired: boolean;
  setupTokenRequired: boolean;
  error: string;
  reload: () => void;
  setSession: (value: unknown) => void;
  logout: () => Promise<void>;
};
const Context = createContext<SessionState | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, update] = useState<Session | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [setupRequired, setSetup] = useState(false);
  const [setupTokenRequired, setToken] = useState(false);
  const [error, setError] = useState("");
  const [reloadKey, reload] = useState(0);
  const channel = useRef<BroadcastChannel | null>(null);
  const epoch = useRef(0);
  const identity = useRef("");
  const clear = useCallback(() => {
    epoch.current++;
    void queryClient.cancelQueries();
    queryClient.clear();
    identity.current = "";
    update(null);
    setStatus("anonymous");
    window.dispatchEvent(new Event("session-cleared"));
  }, []);
  const announce = useCallback((type: "logout" | "login") => {
    channel.current?.postMessage(type);
    // Only a random notification marker is stored; no account data or token.
    try {
      localStorage.setItem(
        "pulsemux-session-event",
        JSON.stringify({ type, nonce: crypto.randomUUID() }),
      );
    } catch {}
  }, []);
  const setSession = useCallback(
    (value: unknown) => {
      if (!value) {
        clear();
        return;
      }
      const next = validate(sessionSchema, value);
      if (session?.user.id !== next.user.id) {
        void queryClient.cancelQueries();
        queryClient.clear();
      }
      identity.current = `${next.user.id}:${next.user.role}`;
      update(next);
      setStatus("authenticated");
      setError("");
      setSetup(false);
      if (session?.user.id !== next.user.id) announce("login");
    },
    [announce, clear, session?.user.id],
  );
  useEffect(() => {
    const abort = new AbortController();
    const currentEpoch = epoch.current;
    setStatus("loading");
    setError("");
    (async () => {
      try {
        const bootstrap = await sessionService.bootstrap(abort.signal);
        if (abort.signal.aborted || currentEpoch !== epoch.current) return;
        setSetup(bootstrap.setup_required);
        setToken(bootstrap.setup_token_required);
        if (bootstrap.setup_required) {
          update(null);
          setStatus("anonymous");
          return;
        }
        const restored = await sessionService.me(abort.signal);
        if (!abort.signal.aborted && currentEpoch === epoch.current) {
          identity.current = `${restored.user.id}:${restored.user.role}`;
          update(restored);
          setStatus("authenticated");
        }
      } catch (cause) {
        if (abort.signal.aborted || currentEpoch !== epoch.current) return;
        if (cause instanceof ApiError && cause.status === 401) clear();
        else {
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to restore your session.",
          );
          setStatus("unavailable");
        }
      }
    })();
    return () => abort.abort();
  }, [reloadKey, clear]);
  useEffect(() => {
    const expire = () => {
      clear();
      announce("logout");
      setError("Your session ended. Sign in to continue.");
    };
    const receive = (type: unknown) => {
      if (type === "logout") clear();
      else if (type === "login") {
        clear();
        reload((key) => key + 1);
      }
    };
    if (typeof BroadcastChannel !== "undefined") {
      channel.current = new BroadcastChannel("pulsemux-session");
      channel.current.onmessage = (event) => receive(event.data);
    }
    const storage = (event: StorageEvent) => {
      if (event.key === "pulsemux-session-event" && event.newValue) {
        try {
          receive(JSON.parse(event.newValue).type);
        } catch {}
      }
    };
    window.addEventListener("session-expired", expire);
    window.addEventListener("storage", storage);
    return () => {
      window.removeEventListener("session-expired", expire);
      window.removeEventListener("storage", storage);
      channel.current?.close();
    };
  }, [announce, clear]);
  useEffect(() => {
    if (status !== "authenticated") return;
    const abort = new AbortController();
    let pending = false;
    const verify = async () => {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      try {
        const next = await sessionService.me(abort.signal);
        if (!abort.signal.aborted) {
          const nextIdentity = `${next.user.id}:${next.user.role}`;
          if (identity.current && identity.current !== nextIdentity) {
            void queryClient.cancelQueries();
            queryClient.clear();
          }
          identity.current = nextIdentity;
          update(next);
        }
      } catch (error) {
        if (
          !abort.signal.aborted &&
          error instanceof ApiError &&
          error.status === 401
        ) {
          clear();
          announce("logout");
        }
      } finally {
        pending = false;
      }
    };
    const timer = setInterval(() => void verify(), 60000);
    const focus = () => void verify();
    window.addEventListener("focus", focus);
    return () => {
      clearInterval(timer);
      abort.abort();
      window.removeEventListener("focus", focus);
    };
  }, [status, clear, announce]);
  const logout = async () => {
    try {
      await sessionService.logout();
      setError("");
    } catch {
      setError(
        "Signed out on this screen. The server could not confirm sign-out; reconnect and sign out again to revoke the browser session.",
      );
    } finally {
      clear();
      announce("logout");
    }
  };
  return (
    <Context.Provider
      value={{
        status,
        session,
        setupRequired,
        setupTokenRequired,
        error,
        reload: () => reload((key) => key + 1),
        setSession,
        logout,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useSession() {
  const state = useContext(Context);
  if (!state) throw new Error("SessionProvider is required");
  return state;
}
