import api, { API_BASE, asList } from "./client";
import { contactLookupType, normalizePublicIdQuery } from "../utils/contactLookup";

/**
 * Every backend call used by the UI lives here, grouped by feature, so
 * components never build URLs themselves. Paths match the Django URLConfs
 * under /api/accounts, /api/chat, /api/status and /api/calls.
 */

const form = (fields) => {
  const data = new FormData();
  Object.entries(fields).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    if (Array.isArray(value)) value.forEach((item) => data.append(key, item));
    else data.append(key, value);
  });
  return data;
};

export const authApi = {
  googleConfig: async () => {
    const response = await fetch(`${API_BASE}accounts/google/config/`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`Google sign-in configuration returned ${response.status}.`);
    return response.json();
  },
  googleLogin: (credential, csrf) =>
    api.post("accounts/google/login/", { credential }, { headers: { "X-CSRFToken": csrf } }).then((r) => r.data),
  login: (phone_number, password) =>
    api.post("accounts/login/", { phone_number, password }).then((r) => r.data),
  register: (payload) => api.post("accounts/register/", payload).then((r) => r.data),
  logout: (refresh) => api.post("accounts/logout/", { refresh }),
  me: () => api.get("accounts/me/", { timeout: 8000 }).then((r) => r.data),
  updateProfile: (fields) =>
    api.patch("accounts/profile/update/", form(fields)).then((r) => r.data),
  setPublicId: (public_id) => api.post("accounts/profile/public-id/", { public_id }).then((r) => r.data),
  createContact: (name, phone_number) => api.post("accounts/contacts/", { name, phone_number }).then((r) => r.data),
  privacy: () => api.get("accounts/privacy/").then((r) => r.data),
  updatePrivacy: (fields) => api.patch("accounts/privacy/", fields).then((r) => r.data),
  deleteAccount: (phone_number, password) =>
    api.post("accounts/delete/", { phone_number, password }).then((r) => r.data),
};

export const contactsApi = {
  list: () => api.get("accounts/contacts/").then((r) => asList(r.data)),
  create: (name, phone_number) =>
    api.post("accounts/contacts/", { name, phone_number }).then((r) => r.data),
  createByPublicId: (name, public_id) => api.post("accounts/contacts/", { name, public_id }).then((r) => r.data),
  createSuggestion: (name, suggested_user_id) => api.post("accounts/contacts/", { name, suggested_user_id }).then((r) => r.data),
  suggestions: () => api.get("accounts/contacts/suggestions/").then((r) => asList(r.data)),
  sync: (contacts) => api.post("accounts/contacts/sync/", { contacts }).then((r) => r.data),
  googleStatus: () => api.get("accounts/contacts/google/").then((r) => r.data),
  googleSync: (payload) => api.post("accounts/contacts/google/", payload).then((r) => r.data),
  googleDisconnect: () => api.delete("accounts/contacts/google/"),
  addGroupMember: (userId, groupId, name) => api.post(`accounts/users/${userId}/add-contact-from-group/`, { group_id: groupId, name }).then((r) => r.data),
  addFromChat: (userId, roomId, name) => api.post(`accounts/users/${userId}/add-contact-from-chat/`, { room_id: roomId, name }).then((r) => r.data),
  update: (id, fields) => api.patch(`accounts/contacts/${id}/`, fields).then((r) => r.data),
  remove: (id) => api.delete(`accounts/contacts/${id}/`),
  lookup: (term) => {
    const value = String(term || "").trim();
    const type = contactLookupType(value);
    const params = type === "public_id"
      ? { public_id: normalizePublicIdQuery(value) }
      : type === "email"
        ? { email: value }
        : { phone: value };
    return api.get("accounts/users/lookup/", { params }).then((r) => r.data);
  },
  commonGroups: (userId) => api.get(`accounts/users/${userId}/common-groups/`).then((r) => r.data),
};

export const chatApi = {
  recentGifs: () => api.get("chat/gifs/recent/").then((r) => r.data.results || []),
  recentStickers: () => api.get("chat/stickers/recent/").then((r) => r.data.results || []),
  gifs: (q = "", offset = 0) => api.get("chat/gifs/", { params: { q, offset } }).then((r) => r.data),
  rooms: () => api.get("chat/rooms/", { params: { archived: "all" } }).then((r) => asList(r.data)),
  roomInfo: (roomId) => api.get(`chat/rooms/${roomId}/info/`).then((r) => r.data),
  openPrivate: (userId) => api.post("chat/rooms/private/", { user_id: userId }).then((r) => r.data),
  createGroup: ({ name, description, photo, participants }) =>
    api.post("chat/rooms/group/", form({ name, description, photo, participants })).then((r) => r.data),
  updateGroup: (roomId, fields) => api.patch(`chat/rooms/${roomId}/info/`, form(fields)).then((r) => r.data),
  addMembers: (roomId, userIds) =>
    api.post(`chat/rooms/${roomId}/participants/`, { user_ids: userIds }).then((r) => r.data),
  removeMember: (roomId, userId) => api.delete(`chat/rooms/${roomId}/participants/${userId}/`),
  setAdmin: (roomId, userId, isAdmin) =>
    api.patch(`chat/rooms/${roomId}/participants/${userId}/admin/`, { is_admin: isAdmin }).then((r) => r.data),
  leaveGroup: (roomId) => api.post(`chat/rooms/${roomId}/leave/`),
  setGroupPermissions: (roomId, fields) => api.patch(`chat/rooms/${roomId}/permissions/`, fields).then((r) => r.data),
  inviteLink: (roomId) => api.get(`chat/rooms/${roomId}/invite-link/`).then((r) => r.data),
  resetInviteLink: (roomId) => api.post(`chat/rooms/${roomId}/invite-link/reset/`).then((r) => r.data),
  invitePreview: (code) => api.get(`chat/invite/${encodeURIComponent(code)}/`).then((r) => r.data),
  joinViaInvite: (code) => api.post(`chat/invite/${encodeURIComponent(code)}/join/`).then((r) => r.data),
  archive: (roomId, isArchived) => api.post("chat/rooms/archive/", { room: roomId, is_archived: isArchived }),
  archiveMany: (roomIds, isArchived) =>
    api.post("chat/rooms/archive/", { rooms: roomIds, is_archived: isArchived }),
  pin: (roomId, isPinned) => api.post("chat/rooms/pin/", { room: roomId, is_pinned: isPinned }),
  favorite: (roomId, isFavorite) => api.post("chat/rooms/favorite/", { room: roomId, is_favorite: isFavorite }),
  mute: (roomId, duration) => api.post("chat/rooms/mute/", { room: roomId, duration }).then((r) => r.data),
  markRead: (roomId) => api.post(`chat/rooms/${roomId}/read/`).then((r) => r.data),
  markAllRead: () => api.post("chat/rooms/read-all/").then((r) => r.data),
  clear: (roomId) => api.post(`chat/rooms/${roomId}/clear/`),
  deleteForMe: (roomId) => api.delete(`chat/rooms/${roomId}/delete/`),
  pinned: (roomId) => api.get(`chat/rooms/${roomId}/pinned/`).then((r) => asList(r.data)),
  allMedia: (kind) => api.get("chat/media/", { params: { kind } }).then((r) => r.data),
  sharedMedia: (roomId, kind) =>
    api.get(`chat/rooms/${roomId}/media/`, { params: { kind } }).then((r) => r.data),
  setDisappearing: (roomId, seconds) => api.post(`chat/rooms/${roomId}/disappearing/`, { seconds }).then((r) => r.data),
  linkPreview: (url, config) => api.get("chat/link-preview/", { params: { url }, ...config }).then((r) => r.data.preview),
  block: (userId) => api.post("chat/users/block/", { user: userId }),
  unblock: (userId) => api.post("chat/users/unblock/", { user: userId }),
  blocked: () => api.get("chat/users/blocked/").then((r) => asList(r.data)),
};

export const messageApi = {
  list: (roomId, { before, limit = 60 } = {}) =>
    api.get(`chat/rooms/${roomId}/messages/`, { params: { before, limit } }).then((r) => asList(r.data)),
  send: ({ room, content, reply_to, client_message_id, message_type = "TEXT", mentions, link_preview, status_id }) =>
    api
      .post("chat/messages/", { room, content, reply_to, client_message_id, message_type, mentions: mentions?.length ? mentions : undefined, link_preview, status_id })
      .then((r) => r.data.data),
  upload: ({ room, file, message_type, content, reply_to, client_message_id, view_once, mentions, status_id, trim_start, trim_end }, onUploadProgress) =>
    api
      .post(
        "chat/messages/upload/",
        form({
          room,
          file,
          message_type,
          content,
          reply_to,
          client_message_id,
          view_once: view_once ? "true" : undefined,
          mentions: mentions?.length ? mentions.join(",") : undefined,
          status_id,
          trim_start,
          trim_end,
        }),
        { onUploadProgress },
      )
      .then((r) => r.data.data),
  liveLocation: (id, body) => api.post(`chat/messages/${id}/live-location/`, body).then((r) => r.data),
  vote: (id, optionIds) => api.post(`chat/messages/${id}/poll/vote/`, { option_ids: optionIds }).then((r) => r.data),
  /** View once media is only served once, with the JWT: fetch it as a blob. */
  openViewOnce: (id) => api.get(`chat/messages/${id}/view-once/`, { responseType: "blob" }).then((r) => r.data),
  voice: ({ room, audio, duration, waveform, viewOnce, statusId }, onUploadProgress) =>
    api
      .post("chat/messages/voice/", form({ room, audio, duration, waveform: JSON.stringify(waveform || []), ...(viewOnce ? { view_once: "true" } : {}), ...(statusId ? { status_id: statusId } : {}) }), {
        onUploadProgress,
      })
      .then((r) => r.data),
  edit: (id, content) => api.patch(`chat/messages/${id}/`, { content }).then((r) => r.data.data),
  react: (id, emoji) => api.post("chat/messages/react/", { message: id, emoji }),
  star: (id, isStarred) => api.post("chat/messages/star/", { message: id, is_starred: isStarred }),
  starred: () => api.get("chat/messages/starred/").then((r) => asList(r.data)),
  pin: (id, isPinned) => api.post("chat/messages/pin/", { message: id, is_pinned: isPinned }),
  forward: (id, roomId) => api.post("chat/messages/forward/", { message: id, room: roomId }).then((r) => r.data.data),
  deleteForMe: (ids) => api.post("chat/messages/delete-many-for-me/", { messages: ids }),
  deleteForEveryone: (roomId, ids) =>
    api.post("chat/messages/delete-for-everyone/", { room: roomId, messages: ids }),
  info: (id) => api.get(`chat/messages/${id}/info/`).then((r) => r.data),
  search: (roomId, q) => api.get(`chat/rooms/${roomId}/messages/search/`, { params: { q } }).then((r) => asList(r.data)),
  searchAll: (q) => api.get("chat/messages/search/", { params: { q } }).then((r) => asList(r.data)),
};

export const statusApi = {
  feed: () => api.get("status/").then((r) => asList(r.data)),
  mine: () => api.get("status/me/").then((r) => asList(r.data)),
  contacts: () => api.get("status/contacts/").then((r) => asList(r.data)),
  upload: (fields, onUploadProgress) =>
    api.post("status/upload/", form(fields), { onUploadProgress }).then((r) => r.data.data),
  view: (id) => api.post(`status/${id}/view/`),
  viewers: (id) => api.get(`status/${id}/viewers/`).then((r) => asList(r.data)),
  report: (id, payload) => api.post(`status/${id}/report/`, payload).then((r) => r.data),
  edit: (id, payload) => api.patch(`status/${id}/edit/`, payload).then((r) => r.data),
  share: (id, room_id) => api.post(`status/${id}/share/`, { room_id }).then((r) => r.data),
  react: (id, emoji) => api.post(`status/${id}/react/`, { emoji }).then((r) => r.data),
  reply: (id, text) => api.post(`status/${id}/react/`, { text }).then((r) => r.data),
  remove: (id) => api.delete(`status/${id}/delete/`),
  highlights: (ownerId) => api.get("status/highlights/", { params: ownerId ? { owner_id: ownerId } : undefined }).then((r) => asList(r.data)),
  createHighlight: (title) => api.post("status/highlights/", { title }).then((r) => r.data),
  updateHighlight: (id, payload) => api.patch(`status/highlights/${id}/`, payload).then((r) => r.data),
  removeHighlight: (id) => api.delete(`status/highlights/${id}/`),
  addHighlightItem: (id, status_id) => api.post(`status/highlights/${id}/items/`, { status_id }).then((r) => r.data),
  removeHighlightItem: (id, status_id) => api.delete(`status/highlights/${id}/items/${status_id}/`),
  reorderHighlights: (ids) => api.post("status/highlights/reorder/", { ids }).then((r) => r.data),
};

export const socialApi = {
  posts: (params = {}) => api.get("social/posts/", { params }).then((r) => r.data),
  post: (id) => api.get(`social/posts/${id}/`).then((r) => r.data),
  followStatus: (userId) => api.get(`social/users/${userId}/follow/`).then((r) => r.data),
  follow: (userId) => api.post(`social/users/${userId}/follow/`).then((r) => r.data),
  unfollow: (userId) => api.delete(`social/users/${userId}/follow/`),
  muteStatus: (userId) => api.get(`social/users/${userId}/mute/`).then((r) => r.data),
  muteUser: (userId) => api.post(`social/users/${userId}/mute/`).then((r) => r.data),
  unmuteUser: (userId) => api.delete(`social/users/${userId}/mute/`).then((r) => r.data),
  followRequests: () => api.get("social/follow-requests/").then((r) => asList(r.data)),
  answerFollowRequest: (id, action) => api.post("social/follow-requests/", { id, action }).then((r) => r.data),
  followers: (userId, params = {}) => api.get(`social/users/${userId}/followers/`, { params }).then((r) => r.data),
  following: (userId, params = {}) => api.get(`social/users/${userId}/following/`, { params }).then((r) => r.data),
  createPost: (payload, onUploadProgress) => api.post("social/posts/", payload, { onUploadProgress }).then((r) => r.data),
  toggleLike: (id, reaction = "LIKE") => api.post(`social/posts/${id}/`, { reaction }).then((r) => r.data),
  removePost: (id) => api.delete(`social/posts/${id}/`),
  sharePost: (id, room_id) => api.post(`social/posts/${id}/share/`, { room_id }).then((r) => r.data),
  updatePost: (id, payload) => api.patch(`social/posts/${id}/`, payload).then((r) => r.data),
  savePost: (id) => api.post(`social/posts/${id}/save/`).then((r) => r.data),
  unsavePost: (id) => api.delete(`social/posts/${id}/save/`),
  reportPost: (id, payload) => api.post(`social/posts/${id}/report/`, payload).then((r) => r.data),
  comments: (id) => api.get(`social/posts/${id}/comments/`).then((r) => asList(r.data)),
  addComment: (id, text, parent_id) => api.post(`social/posts/${id}/comments/`, { text, ...(parent_id ? { parent_id } : {}) }).then((r) => r.data),
  editComment: (postId, commentId, text) => api.patch(`social/posts/${postId}/comments/${commentId}/`, { text }).then((r) => r.data),
  removeComment: (postId, commentId) => api.delete(`social/posts/${postId}/comments/${commentId}/`),
};

/** The catalog pages by cursor, so only the cursor is reused, never a row offset. */
function cursorFrom(next) {
  if (!next) return "";
  try {
    const base = globalThis.location?.origin || "http://localhost";
    return new URL(next, base).searchParams.get("cursor") || "";
  } catch {
    return "";
  }
}

export const marketplaceApi = {
  /** One bounded page of the catalog plus the cursor for the next one. */
  catalogPage: (params = {}) =>
    api.get("marketplace/items/", { params }).then((r) => ({
      items: asList(r.data),
      nextCursor: cursorFrom(r.data?.next),
    })),
  catalog: (params = {}) => marketplaceApi.catalogPage(params).then((page) => page.items),
  inventory: () => api.get("marketplace/inventory/").then((r) => asList(r.data)),
  stickerPacks: () => api.get("marketplace/stickers/mine/").then((r) => asList(r.data)),
  purchases: () => api.get("marketplace/purchases/").then((r) => asList(r.data)),
  config: () => api.get("marketplace/config/").then((r) => r.data),
  entitlements: () => api.get("marketplace/entitlements/").then((r) => asList(r.data)),
  createOrder: (itemId, idempotencyKey, gift = null) =>
    api
      .post(`marketplace/items/${itemId}/orders/`, { idempotency_key: idempotencyKey, ...(gift || {}) })
      .then((r) => r.data),
  orders: () => api.get("marketplace/orders/").then((r) => asList(r.data)),
  order: (orderId) => api.get(`marketplace/orders/${orderId}/`).then((r) => r.data),
  payOrder: (orderId, role, envelopeXdr) =>
    api.post(`marketplace/orders/${orderId}/payments/${role}/`, { envelope_xdr: envelopeXdr }, { timeout: 30_000 }).then((r) => r.data),
  simulatePurchase: (itemId, idempotencyKey) =>
    api.post(`marketplace/items/${itemId}/purchase-simulation/`, { idempotency_key: idempotencyKey }).then((r) => r.data),
  dispute: (purchaseId, reason) => api.post(`marketplace/purchases/${purchaseId}/dispute/`, { reason }).then((r) => r.data),
  submit: (fields) => api.post("marketplace/items/submit/", form(fields)).then((r) => r.data),
  creatorDashboard: () => api.get("marketplace/creator/dashboard/").then((r) => r.data),
  updateCreatorProfile: (fields) => api.patch("marketplace/creator/profile/", fields).then((r) => r.data),
  creators: () => api.get("marketplace/creators/").then((r) => asList(r.data)),
  gifts: () => api.get("marketplace/gifts/").then((r) => r.data),
  report: (itemId, reason, details = "") => api.post(`marketplace/items/${itemId}/report/`, { reason, details }).then((r) => r.data),
  sendGift: ({ item_id, recipient_id, status_id }) => api.post("marketplace/gifts/", { item_id, recipient_id, status_id }).then((r) => r.data),
};

export const callApi = {
  start: (room, call_type) => api.post("calls/start/", { room, call_type }).then((r) => r.data),
  accept: (id) => api.post(`calls/${id}/accept/`),
  reject: (id) => api.post(`calls/${id}/reject/`),
  end: (id) => api.post(`calls/${id}/end/`).then((r) => r.data),
  history: () => api.get("calls/history/").then((r) => asList(r.data)),
  active: () => api.get("calls/active/").then((r) => asList(r.data)),
  current: () => api.get("calls/current/").then((r) => asList(r.data)),
  missed: () => api.get("calls/missed/").then((r) => r.data),
  iceServers: () => api.get("calls/ice-servers/").then((r) => r.data),
  acknowledgeMissed: () => api.post("calls/missed/").then((r) => r.data),
};

export const assistantApi = {
  status: () => api.get("chat/ai/").then((r) => r.data),
  send: (payload) => api.post("chat/ai/", payload, { timeout: 120000 }).then((r) => r.data),
};
