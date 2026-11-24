const DB_NAME = "satoshicore-offline";
const DB_VERSION = 2;
const SNAPSHOTS = "snapshots";
const MEDIA = "media";
const LAST_USER_KEY = "satoshicore:offline-user";
export const CHAT_MEDIA_CACHE = "satoshicore-chat-media-v1";
export const OFFLINE_VIDEO_MAX_FILE = 20 * 1024 * 1024;
const OFFLINE_VIDEO_MAX_TOTAL = 40 * 1024 * 1024;
const OFFLINE_VIDEO_MAX_ITEMS = 3;

let databasePromise;

function openDatabase() {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  if (!databasePromise) {
    databasePromise = new Promise((resolve) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(SNAPSHOTS)) db.createObjectStore(SNAPSHOTS, { keyPath: "userId" });
        if (!db.objectStoreNames.contains(MEDIA)) {
          const media = db.createObjectStore(MEDIA, { keyPath: "key" });
          media.createIndex("userId", "userId", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    });
  }
  return databasePromise;
}

export function rememberOfflineUser(userId) {
  try {
    if (userId) localStorage.setItem(LAST_USER_KEY, String(userId));
  } catch {
    // Storage may be unavailable in private browsing.
  }
}

export function lastOfflineUserId() {
  try {
    const value = Number(localStorage.getItem(LAST_USER_KEY));
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export async function readOfflineSnapshot(userId) {
  const db = await openDatabase();
  if (!db || !userId) return null;
  return new Promise((resolve) => {
    const request = db.transaction(SNAPSHOTS, "readonly").objectStore(SNAPSHOTS).get(Number(userId));
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => resolve(null);
  });
}

export async function readLastOfflineSnapshot() {
  const userId = lastOfflineUserId();
  return userId ? readOfflineSnapshot(userId) : null;
}

export async function writeOfflineSnapshot(snapshot) {
  const db = await openDatabase();
  if (!db || !snapshot?.userId) return false;
  return new Promise((resolve) => {
    const transaction = db.transaction(SNAPSHOTS, "readwrite");
    transaction.objectStore(SNAPSHOTS).put(snapshot);
    transaction.oncomplete = () => resolve(true);
    transaction.onerror = () => resolve(false);
    transaction.onabort = () => resolve(false);
  });
}

export async function clearOfflineData(userId) {
  const db = await openDatabase();
  if (db && userId) {
    await new Promise((resolve) => {
      const transaction = db.transaction([SNAPSHOTS, MEDIA], "readwrite");
      transaction.objectStore(SNAPSHOTS).delete(Number(userId));
      const media = transaction.objectStore(MEDIA);
      const cursor = media.index("userId").openKeyCursor(IDBKeyRange.only(Number(userId)));
      cursor.onsuccess = () => {
        const row = cursor.result;
        if (row) {
          media.delete(row.primaryKey);
          row.continue();
        }
      };
      transaction.oncomplete = transaction.onerror = transaction.onabort = resolve;
    });
  } else if (db) {
    await new Promise((resolve) => {
      const transaction = db.transaction([SNAPSHOTS, MEDIA], "readwrite");
      transaction.objectStore(SNAPSHOTS).clear();
      transaction.objectStore(MEDIA).clear();
      transaction.oncomplete = transaction.onerror = transaction.onabort = resolve;
    });
  }
  try {
    if (!userId || Number(localStorage.getItem(LAST_USER_KEY)) === Number(userId)) {
      localStorage.removeItem(LAST_USER_KEY);
    }
  } catch {
    // Ignore unavailable storage.
  }
  try {
    if (typeof caches !== "undefined") await caches.delete(CHAT_MEDIA_CACHE);
  } catch {
    // Cache Storage may be unavailable.
  }
}

export async function readOfflineVideoPoster(userId, src) {
  const db = await openDatabase();
  if (!db || !userId || !src) return null;
  return new Promise((resolve) => {
    const key = `${Number(userId)}:poster:${src}`;
    const request = db.transaction(MEDIA, "readonly").objectStore(MEDIA).get(key);
    request.onsuccess = () => resolve(request.result?.blob || null);
    request.onerror = () => resolve(null);
  });
}

export async function writeOfflineVideoPoster(userId, src, blob) {
  const db = await openDatabase();
  if (!db || !userId || !src || !blob || blob.size > 256 * 1024) return false;
  return new Promise((resolve) => {
    const transaction = db.transaction(MEDIA, "readwrite");
    const media = transaction.objectStore(MEDIA);
    const entry = { key: `${Number(userId)}:poster:${src}`, userId: Number(userId), src, kind: "poster", blob, savedAt: Date.now() };
    media.put(entry);
    const all = media.index("userId").getAll(IDBKeyRange.only(Number(userId)));
    all.onsuccess = () => {
      const posters = all.result.filter((row) => row.kind === "poster").sort((a, b) => b.savedAt - a.savedAt);
      const recent = posters.slice(0, 50);
      const keysToKeep = new Set(recent.map((row) => row.key));
      all.result.forEach((row) => { if (!keysToKeep.has(row.key)) media.delete(row.key); });
    };
    transaction.oncomplete = () => resolve(true);
    transaction.onerror = transaction.onabort = () => resolve(false);
  });
}

export async function readOfflineVideo(userId, src) {
  const db = await openDatabase();
  if (!db || !userId || !src) return null;
  return new Promise((resolve) => {
    const key = `${Number(userId)}:video:${src}`;
    const request = db.transaction(MEDIA, "readonly").objectStore(MEDIA).get(key);
    request.onsuccess = () => resolve(request.result?.blob || null);
    request.onerror = () => resolve(null);
  });
}

/** Full clips are stored only after an explicit user action, within a small device limit. */
export async function writeOfflineVideo(userId, src, blob) {
  const db = await openDatabase();
  if (!db || !userId || !src || !blob || blob.size > OFFLINE_VIDEO_MAX_FILE || !blob.type.startsWith("video/")) return false;
  return new Promise((resolve) => {
    const transaction = db.transaction(MEDIA, "readwrite");
    const media = transaction.objectStore(MEDIA);
    const userIndex = media.index("userId");
    const all = userIndex.getAll(IDBKeyRange.only(Number(userId)));
    all.onsuccess = () => {
      const key = `${Number(userId)}:video:${src}`;
      const videos = all.result.filter((entry) => entry.kind === "video" && entry.key !== key).sort((a, b) => a.savedAt - b.savedAt);
      let totalBytes = videos.reduce((sum, entry) => sum + Number(entry.blob?.size || 0), 0);
      let count = videos.length;
      while (videos.length && (count >= OFFLINE_VIDEO_MAX_ITEMS || totalBytes + blob.size > OFFLINE_VIDEO_MAX_TOTAL)) {
        const oldest = videos.shift();
        media.delete(oldest.key);
        totalBytes -= Number(oldest.blob?.size || 0);
        count -= 1;
      }
      media.put({ key, userId: Number(userId), src, kind: "video", blob, savedAt: Date.now() });
    };
    transaction.oncomplete = () => resolve(true);
    transaction.onerror = transaction.onabort = () => resolve(false);
  });
}

function usableMessage(message, now) {
  if (!message || message._pending || message.is_view_once) return false;
  if (message.expires_at && new Date(message.expires_at).getTime() <= now) return false;
  return true;
}

function sanitizeMessage(message, now) {
  if (!usableMessage(message, now)) return null;
  const safe = { ...message };
  // A regular message can quote a view-once message. The API includes that
  // quote's text, so remove it even though the quoted message itself is absent.
  if (safe.reply_to?.is_view_once) {
    safe.reply_to = { ...safe.reply_to, content: "", attachment: null };
  }
  return safe;
}

function sanitizeRoom(room, now) {
  const lastMessage = sanitizeMessage(room.lastMessage, now);
  let lastReaction = room.lastReaction;
  if (lastReaction?.message) {
    const message = sanitizeMessage(lastReaction.message, now);
    lastReaction = message ? { ...lastReaction, message } : null;
  }
  return { ...room, lastMessage, lastReaction };
}

/** Sanitize on both write and read so old snapshots cannot restore ephemeral content. */
export function sanitizeOfflineSnapshot(snapshot, now = Date.now()) {
  if (!snapshot?.me?.id || Number(snapshot.userId) !== Number(snapshot.me.id)) return null;
  const rooms = (snapshot.rooms || [])
    .filter((room) => room && !room._pinnedOpen)
    .map((room) => sanitizeRoom(room, now))
    .slice(0, 40);
  const roomIds = new Set(rooms.map((room) => String(room.id)));
  const messages = {};
  Object.entries(snapshot.messages || {}).forEach(([roomId, entry]) => {
    if (!roomIds.has(String(roomId)) || !entry?.loaded) return;
    const items = (entry.items || []).map((message) => sanitizeMessage(message, now)).filter(Boolean).slice(-40);
    if (items.length) messages[roomId] = { ...entry, items, loaded: true, hasMore: Boolean(entry.hasMore), loading: false, error: "" };
  });
  return {
    ...snapshot,
    rooms,
    messages,
    contacts: (snapshot.contacts || []).slice(0, 500),
  };
}

/** Keep a bounded, account-scoped snapshot; never persist credentials or view-once content. */
export function makeOfflineSnapshot(state) {
  const userId = Number(state.me?.id);
  if (!userId || !state.roomsLoaded) return null;
  const now = Date.now();
  const rooms = Object.values(state.rooms)
    .filter((room) => room && !room._pinnedOpen)
    .map((room) => sanitizeRoom(room, now))
    .sort((a, b) => new Date(b.lastMessage?.created_at || b.updated_at || 0) - new Date(a.lastMessage?.created_at || a.updated_at || 0))
    .slice(0, 40);
  const roomIds = new Set(rooms.map((room) => String(room.id)));
  const messages = {};
  Object.entries(state.messages).forEach(([roomId, entry]) => {
    if (!roomIds.has(String(roomId)) || !entry?.loaded) return;
    const items = (entry.items || []).map((message) => sanitizeMessage(message, now)).filter(Boolean).slice(-40);
    if (items.length) messages[roomId] = { items, loaded: true, hasMore: Boolean(entry.hasMore), loading: false, error: "" };
  });
  return {
    userId,
    savedAt: new Date(now).toISOString(),
    me: state.me,
    rooms,
    messages,
    contacts: (state.contacts || []).slice(0, 500),
  };
}
