import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/** Move keyboard focus after lazy page content arrives, without interrupting typing. */
export function NavigationRecovery() {
  const { pathname } = useLocation();
  useEffect(() => {
    let disposed = false;
    const focus = () => {
      const heading = document.querySelector<HTMLElement>(
        "main h1, .auth-page h1",
      );
      if (!heading || disposed) return false;
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      return true;
    };
    if (focus()) return;
    const observer = new MutationObserver(() => {
      if (focus()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const timeout = setTimeout(() => observer.disconnect(), 10000);
    return () => {
      disposed = true;
      observer.disconnect();
      clearTimeout(timeout);
    };
  }, [pathname]);
  return null;
}
