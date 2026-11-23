import api from "../../api/client";

/** Public read operations exposed by the Wallet Integration API. */
export const walletApi = {
  read: (address) => api.get("wallet/read/", { params: { address }, timeout: 25_000 }).then((r) => r.data),
  linkState: () => api.get("wallet/link/me/").then((r) => r.data),
  startLink: () => api.post("wallet/link/start/").then((r) => r.data),
  confirmLink: (payload) => api.post("wallet/link/confirm/", payload).then((r) => r.data),
  disconnect: () => api.delete("wallet/link/me/").then((r) => r.data),
  chatRecipient: (roomId) => api.get("wallet/chat/recipient/", { params: { room_id: roomId } }).then((r) => r.data),
};
