import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { errorMessage } from "../api/client";
import { authApi } from "../api/endpoints";
import { LogoMark } from "../components/common/Icons";
import { Spinner } from "../components/common/ui";
import { navigate } from "../router";
import { normalizePhone } from "../utils/phone";

export default function LoginPage({ onAuthenticated }) {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [googleStatus, setGoogleStatus] = useState("loading");
  const [googleStatusMessage, setGoogleStatusMessage] = useState("");
  const googleButton = useRef(null);
  const googleCsrf = useRef("");

  useEffect(() => {
    let cancelled = false;
    let script;
    let onLoad;
    let onError;
    authApi.googleConfig().then((config) => {
      if (cancelled) return;
      if (!config.client_id) {
        setGoogleStatus("missing-client");
        return;
      }
      googleCsrf.current = config.csrf;
      setGoogleEnabled(true);
      const initialize = () => {
        let attempts = 0;
        const render = () => {
          if (cancelled) return;
          // setGoogleEnabled commits on the next React render. Wait for that
          // ref before asking GIS to render its cross-origin button iframe.
          if (!googleButton.current) {
            if (attempts++ < 30) window.requestAnimationFrame(render);
            else setGoogleStatus("blocked");
            return;
          }
          const gis = window.google?.accounts?.id;
          if (!gis) {
            setGoogleStatus("blocked");
            return;
          }
          try {
            gis.initialize({
              client_id: config.client_id,
              callback: async ({ credential }) => {
                setError("");
                setBusy(true);
                try {
                  const data = await authApi.googleLogin(credential, googleCsrf.current);
                  await onAuthenticated(data);
                } catch (err) {
                  setError(errorMessage(err, "Google sign-in failed."));
                  setBusy(false);
                }
              },
            });
            const width = Math.min(360, Math.floor(googleButton.current.getBoundingClientRect().width || 360));
            gis.renderButton(googleButton.current, { theme: "outline", size: "large", shape: "pill", text: "continue_with", width });
            setGoogleStatus("ready");
          } catch {
            setGoogleStatus("blocked");
          }
        };
        window.requestAnimationFrame(render);
      };
      script = document.querySelector('script[data-google-identity="true"]');
      if (window.google?.accounts?.id) initialize();
      else if (script) {
        onLoad = initialize;
        onError = () => !cancelled && setGoogleStatus("script-error");
        script.addEventListener("load", onLoad, { once: true });
        script.addEventListener("error", onError, { once: true });
      } else {
        script = document.createElement("script");
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.defer = true;
        script.dataset.googleIdentity = "true";
        script.addEventListener("load", initialize, { once: true });
        onLoad = initialize;
        onError = () => !cancelled && setGoogleStatus("script-error");
        script.addEventListener("error", onError, { once: true });
        document.head.appendChild(script);
      }
    }).catch((err) => {
      if (!cancelled) {
        setGoogleStatus("config-error");
        setGoogleStatusMessage(errorMessage(err, "Google sign-in configuration could not be reached. Refresh this page to try again."));
      }
    });
    return () => {
      cancelled = true;
      if (script && onLoad) script.removeEventListener("load", onLoad);
      if (script && onError) script.removeEventListener("error", onError);
    };
  }, [onAuthenticated]);

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!phone.trim() || !password) {
      setError("Enter your phone number and password.");
      return;
    }
    setBusy(true);
    try {
      const data = await authApi.login(normalizePhone(phone), password);
      await onAuthenticated(data);
    } catch (err) {
      setError(errorMessage(err, "Couldn't sign in."));
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="auth__brand">
        <LogoMark size={36} />
        <span>SatoshiCore</span>
      </div>
      <form className="auth__card" onSubmit={submit} noValidate>
        <h1>Log in to SatoshiCore</h1>
        <p className="auth__lead">Use the phone number and password of your SatoshiCore account.</p>
        {error ? <div className="form-error" role="alert">{error}</div> : null}
        <div className="field">
          <label htmlFor="login-phone">Phone number</label>
          <input
            id="login-phone"
            type="tel"
            autoComplete="tel"
            placeholder="+92 300 1234567"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="login-password">Password</label>
          <div className="field__password">
            <input
              id="login-password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button type="button" className="icon-btn" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>
        <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
          {busy ? <Spinner size={18} /> : "Log in"}
        </button>
        <div className="auth__divider"><span>or continue with</span></div>
        <div className={`auth__google${googleStatus === "ready" ? " is-ready" : ""}`}>
          {googleEnabled ? <div ref={googleButton} aria-label="Continue with Google" /> : null}
          {googleStatus === "loading" ? <span className="auth__google-status">Loading Google sign-in…</span> : null}
          {googleStatus === "blocked" || googleStatus === "script-error" || googleStatus === "config-error" || googleStatus === "missing-client" ? (
            <span className="auth__google-status" role="status">
              {googleStatus === "blocked" ? "Google sign-in could not initialize in this browser." : null}
              {googleStatus === "script-error" ? "Google sign-in could not load. Check your connection or browser content blockers." : null}
              {googleStatus === "config-error" ? googleStatusMessage : null}
              {googleStatus === "missing-client" ? "Google sign-in is not configured on this server." : null}
            </span>
          ) : null}
        </div>
        <p className="auth__switch">
          New to SatoshiCore?{" "}
          <a href="/signup" onClick={(event) => { event.preventDefault(); navigate("/signup"); }}>
            Create an account
          </a>
        </p>
      </form>
      <p className="auth__foot">Your messages sync in real time across all your open tabs and devices.</p>
    </div>
  );
}
