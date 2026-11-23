const CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly";
const PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections";

let scriptPromise;
let tokenClient;
let cachedToken = "";
let tokenExpiresAt = 0;

function loadGoogleIdentity() {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    let script = document.querySelector('script[data-google-identity="true"]');
    const loaded = () => window.google?.accounts?.oauth2 ? resolve() : reject(new Error("Google authorization could not initialize."));
    const failed = () => reject(new Error("Google authorization could not load. Check your connection or browser content blockers."));
    if (script) {
      script.addEventListener("load", loaded, { once: true });
      script.addEventListener("error", failed, { once: true });
      return;
    }
    script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.googleIdentity = "true";
    script.addEventListener("load", loaded, { once: true });
    script.addEventListener("error", failed, { once: true });
    document.head.appendChild(script);
  }).catch((error) => {
    scriptPromise = null;
    throw error;
  });
  return scriptPromise;
}

export function prepareGoogleContacts() {
  return loadGoogleIdentity();
}

export async function requestGoogleContactsAccess(clientId, { silent = false } = {}) {
  if (!clientId) throw new Error("Google sign-in is not configured on this server.");
  if (cachedToken && tokenExpiresAt > Date.now() + 30_000) return cachedToken;
  await loadGoogleIdentity();
  const oauth = window.google.accounts.oauth2;
  return new Promise((resolve, reject) => {
    const config = {
      client_id: clientId,
      scope: CONTACTS_SCOPE,
      callback: (response) => {
        if (response.error || !response.access_token) {
          reject(new Error(response.error_description || "Google Contacts permission was not granted."));
          return;
        }
        if (oauth.hasGrantedAllScopes && !oauth.hasGrantedAllScopes(response, CONTACTS_SCOPE)) {
          reject(new Error("Google Contacts read permission was not granted."));
          return;
        }
        cachedToken = response.access_token;
        tokenExpiresAt = Date.now() + Math.max(60, Number(response.expires_in) || 3600) * 1000;
        resolve(cachedToken);
      },
      error_callback: ({ message, type }) => reject(new Error(message || (type === "popup_failed_to_open" ? "Allow pop-ups to connect Google Contacts." : "Google authorization was cancelled."))),
    };
    if (!tokenClient || tokenClient.__clientId !== clientId) {
      tokenClient = oauth.initTokenClient(config);
      tokenClient.__clientId = clientId;
    } else {
      // GIS keeps the callback from initialization, so reinitialize to bind
      // this request's promise handlers without persisting an access token.
      tokenClient = oauth.initTokenClient(config);
      tokenClient.__clientId = clientId;
    }
    try {
      tokenClient.requestAccessToken({ prompt: silent ? "none" : "" });
    } catch (error) {
      reject(error);
    }
  });
}

async function getPeoplePage(accessToken, { pageToken = "", syncToken = "" } = {}) {
  const url = new URL(PEOPLE_URL);
  url.searchParams.set("personFields", "metadata,phoneNumbers,emailAddresses");
  url.searchParams.set("pageSize", "1000");
  url.searchParams.set("requestSyncToken", "true");
  if (pageToken) url.searchParams.set("pageToken", pageToken);
  if (syncToken) url.searchParams.set("syncToken", syncToken);
  const response = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const expiredSyncToken = response.status === 410
      || (response.status === 400 && /EXPIRED_SYNC_TOKEN|sync token.*expired/i.test(JSON.stringify(body?.error || {})));
    const error = new Error(response.status === 403 ? "Google did not grant access to Contacts. You can retry and review the permission request." : "Google Contacts could not be read. Try again in a moment.");
    error.status = response.status;
    error.expiredSyncToken = expiredSyncToken;
    throw error;
  }
  return response.json();
}

function cleanPerson(person) {
  const resourceName = String(person.resourceName || "");
  if (!/^people\/[A-Za-z0-9._:-]{1,500}$/.test(resourceName)) return null;
  const phones = [...new Set((person.phoneNumbers || [])
    .map((entry) => String(entry.canonicalForm || entry.value || "").trim())
    .filter((value) => /^\+[1-9]\d{1,14}$/.test(value)))];
  const emails = [...new Set((person.emailAddresses || [])
    .map((entry) => String(entry.value || "").trim().toLowerCase())
    .filter((value) => value.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)))];
  return {
    resource_name: resourceName,
    phones,
    emails,
    deleted: person.metadata?.deleted === true,
  };
}

export async function syncGooglePeople(accessToken, syncToken, onPage) {
  let pageToken = "";
  let nextSyncToken = "";
  do {
    const page = await getPeoplePage(accessToken, { pageToken, syncToken });
    const contacts = (page.connections || []).map(cleanPerson).filter(Boolean);
    nextSyncToken = page.nextSyncToken || nextSyncToken;
    await onPage(contacts, { fullSync: !syncToken, nextPage: Boolean(page.nextPageToken) });
    pageToken = page.nextPageToken || "";
  } while (pageToken);
  if (!nextSyncToken) throw new Error("Google did not return a sync cursor. Try syncing again.");
  return nextSyncToken;
}

export async function revokeGoogleContacts(accessToken) {
  await loadGoogleIdentity();
  if (!accessToken) return false;
  const oauth = window.google.accounts.oauth2;
  return new Promise((resolve) => {
    try {
      oauth.revoke(accessToken, () => resolve(true));
    } catch {
      resolve(false);
    } finally {
      cachedToken = "";
      tokenExpiresAt = 0;
      tokenClient = null;
    }
  });
}

export function clearGoogleContactsToken() {
  cachedToken = "";
  tokenExpiresAt = 0;
  tokenClient = null;
}
