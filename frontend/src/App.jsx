import { useCallback, useEffect, useRef, useState } from "react";
import { onSessionExpired, tokens } from "./api/client";
import { authApi } from "./api/endpoints";
import { Spinner, ToastHost } from "./components/common/ui";
import UpdatePrompt from "./components/common/UpdatePrompt";
import DialogHost from "./components/common/DialogHost";
import { LogoMark } from "./components/common/Icons";
import JoinGroupDialog from "./components/join/JoinGroupDialog";
import AddFriendDialog from "./components/join/AddFriendDialog";
import MainLayout from "./components/layout/MainLayout";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import { navigate, usePathname } from "./router";
import { realtime } from "./services/realtime";
import { forgetBackgroundPushOnLogout, syncBackgroundPush } from "./services/push";
import { clearOfflineData, lastOfflineUserId, readLastOfflineSnapshot, rememberOfflineUser } from "./services/offlineCache";
import { bootstrap } from "./store/actions";
import { dispatch, getState, useStore } from "./store/store";

const AFTER_LOGIN_KEY = "mhtalk:after-login";
const JOIN_PATTERN = /^\/join\/([A-Za-z0-9_-]{1,64})$/;
const ADD_PATTERN = /^\/add\/([a-z0-9._-]{4,20})$/i;

/** Where to go after signing in (e.g. back to a /join/<code> link). */
function takeAfterLogin() {
  try {
    const path = sessionStorage.getItem(AFTER_LOGIN_KEY);
    sessionStorage.removeItem(AFTER_LOGIN_KEY);
    return path && (JOIN_PATTERN.test(path) || ADD_PATTERN.test(path)) ? path : "/";
  } catch {
    return "/";
  }
}

/**
 * Auth gate + routing.
 *   /login        sign in
 *   /signup       create an account
 *   /join/<code>  group invite link (signed out: log in first, then come back)
 *   /             the app (protected)
 */
export default function App() {
  const path = usePathname();
  const joinCode = JOIN_PATTERN.exec(path)?.[1] || null;
  const addPublicId = ADD_PATTERN.exec(path)?.[1] || null;
  const me = useStore((state) => state.me);
  const [checking, setChecking] = useState(Boolean(tokens.access || tokens.refresh));
  const offlineSession = useRef(false);
  const resumeInFlight = useRef(false);

  const signOutLocally = useCallback(() => {
    const userId = getState().me?.id || lastOfflineUserId();
    offlineSession.current = false;
    realtime.stop();
    tokens.clear();
    if (userId) clearOfflineData(userId);
    dispatch({ type: "reset" });
    navigate("/login", { replace: true });
  }, []);

  const startSession = useCallback(async (user) => {
    dispatch({ type: "me", me: user });
    offlineSession.current = false;
    rememberOfflineUser(user.id);
    realtime.start({ onSessionExpired: signOutLocally });
    syncBackgroundPush().catch(() => {});
    await bootstrap();
  }, [signOutLocally]);

  const showOfflineSnapshot = useCallback((snapshot) => {
    if (!snapshot?.me?.id || Number(snapshot.userId) !== Number(snapshot.me.id)) return false;
    dispatch({ type: "offline/hydrate", snapshot });
    dispatch({ type: "me", me: snapshot.me });
    dispatch({ type: "connection", status: "offline" });
    offlineSession.current = true;
    return true;
  }, []);

  // Restore an existing session on load.
  useEffect(() => {
    let cancelled = false;
    if (!tokens.access && !tokens.refresh) return undefined;
    let authResolved = false;
    resumeInFlight.current = true;
    const snapshotTask = readLastOfflineSnapshot().then((snapshot) => {
      if (!cancelled && !authResolved && snapshot && showOfflineSnapshot(snapshot)) setChecking(false);
      return snapshot;
    });
    const restoreSession = async () => {
      try {
        const user = await authApi.me();
        authResolved = true;
        if (!cancelled) {
          realtime.stop();
          await startSession(user);
        }
      } catch (error) {
        // Never use a cached identity after the server explicitly rejected the
        // session. A network/server outage can still open the last local copy.
        authResolved = true;
        if (!cancelled && (!error?.response || error.response.status >= 500)) {
          const snapshot = await snapshotTask;
          if (!offlineSession.current && !showOfflineSnapshot(snapshot)) {
            offlineSession.current = true;
            dispatch({ type: "connection", status: "offline" });
          }
        } else if (!cancelled) signOutLocally();
      } finally {
        resumeInFlight.current = false;
        if (!cancelled) setChecking(false);
      }
    };
    if (navigator.onLine === false) {
      snapshotTask.then((snapshot) => {
        if (cancelled) return;
        if (!offlineSession.current && !showOfflineSnapshot(snapshot)) {
          offlineSession.current = true;
          dispatch({ type: "connection", status: "offline" });
        }
      }).finally(() => {
        resumeInFlight.current = false;
        if (!cancelled) setChecking(false);
      });
    } else {
      restoreSession();
    }
    return () => {
      cancelled = true;
      resumeInFlight.current = false;
    };
  }, [startSession, showOfflineSnapshot, signOutLocally]);

  // If the app started from a saved snapshot, authenticate and sync as soon
  // as connectivity returns (also check again when the app becomes visible).
  useEffect(() => {
    const resume = async () => {
      if (!offlineSession.current || resumeInFlight.current || navigator.onLine === false) return;
      resumeInFlight.current = true;
      try {
        const user = await authApi.me();
        realtime.stop();
        await startSession(user);
      } catch {
        // Keep the saved, read-only view until the server can be reached.
      } finally {
        resumeInFlight.current = false;
      }
    };
    const onVisibility = () => { if (document.visibilityState === "visible") resume(); };
    window.addEventListener("online", resume);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("online", resume);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [startSession]);

  useEffect(() => onSessionExpired(signOutLocally), [signOutLocally]);

  // Account deleted (this tab or another one): back to the login page.
  useEffect(() => {
    window.addEventListener("mhtalk:signed-out", signOutLocally);
    return () => window.removeEventListener("mhtalk:signed-out", signOutLocally);
  }, [signOutLocally]);

  // Keep "me" fresh when the profile changes in another tab/device.
  useEffect(() => {
    const reload = () => authApi.me().then((user) => dispatch({ type: "me", me: user })).catch(() => {});
    window.addEventListener("mhtalk:me-changed", reload);
    return () => window.removeEventListener("mhtalk:me-changed", reload);
  }, []);

  // Route guards.
  useEffect(() => {
    if (checking) return;
    const isAuthRoute = path === "/login" || path === "/signup";
    if (!me && !isAuthRoute) {
      if (JOIN_PATTERN.test(path)) {
        try {
          sessionStorage.setItem(AFTER_LOGIN_KEY, path);
        } catch {
          /* storage unavailable */
        }
      }
      navigate("/login", { replace: true });
    }
    if (me && isAuthRoute) navigate(takeAfterLogin(), { replace: true });
  }, [checking, me, path]);

  const handleAuthenticated = useCallback(
    async ({ access, refresh, user }) => {
      tokens.set({ access, refresh });
      await startSession(user);
      // The route guard may already have moved on (e.g. back to /join/<code>).
      if (["/login", "/signup"].includes(window.location.pathname)) navigate(takeAfterLogin(), { replace: true });
    },
    [startSession],
  );

  const handleLogout = useCallback(async () => {
    const userId = getState().me?.id;
    await forgetBackgroundPushOnLogout();
    try {
      if (tokens.refresh) await authApi.logout(tokens.refresh);
    } catch {
      /* the token may already be invalid */
    }
    if (userId) await clearOfflineData(userId);
    signOutLocally();
  }, [signOutLocally]);

  let content;
  if (checking) {
    content = (
      <div className="splash">
        <LogoMark size={64} />
        <Spinner size={28} />
        <p>Loading your chats…</p>
      </div>
    );
  } else if (!me) {
    content = path === "/signup" ? <SignupPage onAuthenticated={handleAuthenticated} /> : <LoginPage onAuthenticated={handleAuthenticated} />;
  } else {
    content = (
      <>
        <MainLayout onLogout={handleLogout} />
        {joinCode ? <JoinGroupDialog key={joinCode} code={joinCode} /> : null}
        {addPublicId ? <AddFriendDialog key={addPublicId} publicId={decodeURIComponent(addPublicId)} /> : null}
      </>
    );
  }

  return (
    <>
      {content}
      <DialogHost />
      <ToastHost />
      <UpdatePrompt />
    </>
  );
}
