import { useEffect, useState } from "react";
import { Eye, EyeOff, Smartphone, Users } from "lucide-react";
import { errorMessage, tokens } from "../api/client";
import { authApi, contactsApi } from "../api/endpoints";
import { LogoMark } from "../components/common/Icons";
import { Spinner } from "../components/common/ui";
import { navigate } from "../router";
import { normalizePhone } from "../utils/phone";
import { clearGoogleContactsToken, prepareGoogleContacts, requestGoogleContactsAccess, syncGooglePeople } from "../services/googleContacts";
import { toast } from "../services/toast";

function deviceContactPickerAvailable() {
  return window.isSecureContext && typeof navigator.contacts?.select === "function";
}

function selectedDeviceContacts(rows) {
  const unique = new Map();
  for (const row of rows || []) {
    const names = Array.isArray(row.name) ? row.name : [row.name];
    const name = String(names.find(Boolean) || "").trim().slice(0, 100);
    const phones = Array.isArray(row.tel) ? row.tel : [row.tel];
    for (const raw of phones) {
      const value = String(raw || "").trim();
      // Do not guess a country code for national-format device contacts.
      const phone = value.startsWith("+")
        ? `+${value.slice(1).replace(/\D/g, "")}`
        : value.startsWith("00")
          ? `+${value.slice(2).replace(/\D/g, "")}`
          : "";
      if (/^\+[1-9]\d{1,14}$/.test(phone)) unique.set(phone, { name, phone });
    }
  }
  return [...unique.values()].slice(0, 100);
}

async function syncSignupContacts({ googleToken, deviceContacts }) {
  const outcomes = [];
  if (deviceContacts.length) {
    try {
      await contactsApi.sync(deviceContacts);
      outcomes.push("Phone contacts checked");
    } catch {
      outcomes.push("Phone contact matching can be retried from Add friends");
    }
  }
  if (googleToken) {
    try {
      await contactsApi.googleSync({ consent_accepted: true });
      const syncId = crypto.randomUUID();
      const nextSyncToken = await syncGooglePeople(googleToken, "", async (contacts) => {
        await contactsApi.googleSync({ contacts: contacts.filter((item) => !item.deleted), full_sync: true, full_sync_id: syncId });
      });
      await contactsApi.googleSync({ contacts: [], full_sync: true, full_sync_id: syncId, complete: true, sync_token: nextSyncToken });
      outcomes.push("Google Contacts checked");
    } catch {
      outcomes.push("Google Contacts can be connected from Add friends");
    }
  }
  return outcomes;
}

/** Field-level errors from DRF ({field: [messages]}) */
function fieldErrors(error) {
  const data = error?.response?.data;
  if (!data || typeof data !== "object") return {};
  return Object.fromEntries(
    Object.entries(data).map(([field, value]) => [field, Array.isArray(value) ? value.join(" ") : String(value)]),
  );
}

export default function SignupPage({ onAuthenticated }) {
  const [form, setForm] = useState({ display_name: "", phone: "", email: "", password: "", confirm: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [contactsConsent, setContactsConsent] = useState(false);
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleConfigState, setGoogleConfigState] = useState("loading");
  const [googleToken, setGoogleToken] = useState("");
  const [deviceContacts, setDeviceContacts] = useState([]);
  const [permissionBusy, setPermissionBusy] = useState("");
  const [permissionMessage, setPermissionMessage] = useState("");

  useEffect(() => {
    prepareGoogleContacts().catch(() => {});
    authApi.googleConfig().then((config) => {
      const clientId = config.client_id || "";
      setGoogleClientId(clientId);
      setGoogleConfigState(clientId ? "ready" : "unavailable");
    }).catch(() => setGoogleConfigState("unavailable"));
  }, []);

  const update = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));

  function validate() {
    const next = {};
    if (!form.display_name.trim()) next.display_name = "Enter your name.";
    const phone = normalizePhone(form.phone);
    if (!/^\+\d{8,15}$/.test(phone)) next.phone_number = "Enter a valid number with country code, e.g. +92 300 1234567.";
    if (form.email && !/^\S+@\S+\.\S+$/.test(form.email)) next.email = "Enter a valid email address.";
    if (form.password.length < 8) next.password = "Use at least 8 characters.";
    if (form.password !== form.confirm) next.confirm = "Passwords don't match.";
    return next;
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    const local = validate();
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      const data = await authApi.register({
        display_name: form.display_name.trim(),
        phone_number: normalizePhone(form.phone),
        email: form.email.trim() || undefined,
        password: form.password,
      });
      const session = data.access ? data : await authApi.login(normalizePhone(form.phone), form.password);
      // Keep the optional signup-time contact sync authenticated, but never
      // block account creation if an external contacts provider is unavailable.
      tokens.set({ access: session.access, refresh: session.refresh });
      let outcomes = [];
      try { outcomes = await syncSignupContacts({ googleToken, deviceContacts }); }
      finally { if (googleToken) clearGoogleContactsToken(); }
      await onAuthenticated(session);
      if (outcomes.length) toast(outcomes.join(" · "));
    } catch (err) {
      const fields = fieldErrors(err);
      setErrors(fields);
      setError(Object.keys(fields).length ? "" : errorMessage(err, "Couldn't create your account."));
      setBusy(false);
    }
  }

  async function connectGoogleDuringSignup() {
    if (!contactsConsent) return;
    setPermissionBusy("google");
    setPermissionMessage("");
    try {
      if (!googleClientId) throw new Error("Google Contacts is not configured for this service.");
      const token = await requestGoogleContactsAccess(googleClientId);
      setGoogleToken(token);
      setPermissionMessage("Google Contacts access granted. Selected contacts will be checked after account creation.");
    } catch (err) {
      setPermissionMessage(errorMessage(err, "Google Contacts permission was not granted."));
    } finally { setPermissionBusy(""); }
  }

  async function chooseDeviceContacts() {
    if (!contactsConsent || !deviceContactPickerAvailable()) return;
    setPermissionBusy("device");
    setPermissionMessage("");
    try {
      // Contact Picker must be called directly from a user gesture. It only
      // shares entries explicitly selected in the OS picker; access is not persistent.
      const rows = await navigator.contacts.select(["name", "tel"], { multiple: true });
      const selected = selectedDeviceContacts(rows);
      setDeviceContacts(selected);
      setPermissionMessage(selected.length
        ? `${selected.length} selected phone contact${selected.length === 1 ? "" : "s"} will be checked after account creation.`
        : "No contacts with full international phone numbers were selected.");
    } catch (err) {
      if (err?.name !== "AbortError") setPermissionMessage("Phone contacts were not selected. You can still create your account.");
    } finally { setPermissionBusy(""); }
  }

  return (
    <div className="auth">
      <div className="auth__brand">
        <LogoMark size={36} />
        <span>SatoshiCore</span>
      </div>
      <form className="auth__card" onSubmit={submit} noValidate>
        <h1>Create your account</h1>
        <p className="auth__lead">People can find you on SatoshiCore by this phone number.</p>
        {error ? <div className="form-error" role="alert">{error}</div> : null}

        <div className="field">
          <label htmlFor="su-name">Your name</label>
          <input id="su-name" value={form.display_name} onChange={update("display_name")} autoComplete="name" maxLength={100} autoFocus />
          {errors.display_name ? <span className="field__error">{errors.display_name}</span> : null}
        </div>
        <div className="field">
          <label htmlFor="su-phone">Phone number</label>
          <input id="su-phone" type="tel" placeholder="+92 300 1234567" value={form.phone} onChange={update("phone")} autoComplete="tel" />
          {errors.phone_number ? <span className="field__error">{errors.phone_number}</span> : <span className="field__hint">Local numbers like 0300 1234567 are converted to +92 automatically.</span>}
        </div>
        <div className="field">
          <label htmlFor="su-email">Email (optional)</label>
          <input id="su-email" type="email" value={form.email} onChange={update("email")} autoComplete="email" />
          {errors.email ? <span className="field__error">{errors.email}</span> : null}
        </div>
        <div className="field">
          <label htmlFor="su-password">Password</label>
          <div className="field__password">
            <input id="su-password" type={showPassword ? "text" : "password"} value={form.password} onChange={update("password")} autoComplete="new-password" />
            <button type="button" className="icon-btn" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {errors.password ? <span className="field__error">{errors.password}</span> : null}
        </div>
        <div className="field">
          <label htmlFor="su-confirm">Confirm password</label>
          <input id="su-confirm" type={showPassword ? "text" : "password"} value={form.confirm} onChange={update("confirm")} autoComplete="new-password" />
          {errors.confirm ? <span className="field__error">{errors.confirm}</span> : null}
        </div>

        <section className="signup-contacts" aria-labelledby="signup-contacts-title">
          <h2 id="signup-contacts-title">Find friends during sign-up</h2>
          <p>Choose whether to check contacts now. We use phone numbers and selected names only to match members; unmatched details are discarded. Device contacts are shared only after you select them, and the browser does not grant lasting access. This is optional.</p>
          <label className="signup-contacts__consent">
            <input type="checkbox" checked={contactsConsent} onChange={(event) => setContactsConsent(event.target.checked)} />
            <span>I agree to use the contacts I choose for friend matching.</span>
          </label>
          <div className="signup-contacts__actions">
            <button type="button" className="btn btn--ghost" onClick={connectGoogleDuringSignup} disabled={!contactsConsent || permissionBusy !== "" || Boolean(googleToken) || googleConfigState !== "ready"}>
              {permissionBusy === "google" || googleConfigState === "loading" ? <Spinner size={16} /> : <><Users size={16} /> {googleToken ? "Google Contacts connected" : googleConfigState === "unavailable" ? "Google unavailable" : "Allow Google Contacts"}</>}
            </button>
            {deviceContactPickerAvailable() ? (
              <button type="button" className="btn btn--ghost" onClick={chooseDeviceContacts} disabled={!contactsConsent || permissionBusy !== ""}>
                {permissionBusy === "device" ? <Spinner size={16} /> : <><Smartphone size={16} /> {deviceContacts.length ? `${deviceContacts.length} phone contacts selected` : "Choose phone contacts"}</>}
              </button>
            ) : <span className="signup-contacts__unsupported">This browser cannot open the phone contact picker. Google Contacts or Add friends remains available.</span>}
          </div>
          <p className="signup-contacts__status" role="status">{permissionMessage}</p>
        </section>

        <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
          {busy ? <Spinner size={18} /> : "Create account"}
        </button>
        <p className="auth__switch">
          Already have an account?{" "}
          <a href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>
            Log in
          </a>
        </p>
      </form>
    </div>
  );
}
