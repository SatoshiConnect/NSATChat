import api from "../../api/client";

/** Public read operations exposed by the Wallet Integration API. */
export const walletApi = {
  read: (address) => api.get("wallet/read/", { params: { address }, timeout: 25_000 }).then((r) => r.data),
  preflight: (source, destination) => api.get("wallet/preflight/", { params: { source, destination }, timeout: 25_000 }).then((r) => r.data),
  submit: (envelopeXdr) => api.post("wallet/submit/", { envelope_xdr: envelopeXdr }, { timeout: 25_000 }).then((r) => r.data),
  confirmation: (hash, submittedAt) => api.get(`wallet/confirmation/${hash}/`, { params: { submitted_at: submittedAt }, timeout: 15_000 }).then((r) => r.data),
  chatRecipient: (roomId) => api.get("wallet/chat/recipient/", { params: { room_id: roomId } }).then((r) => r.data),
  linkStart: () => api.post("wallet/link/start/").then((r) => r.data),
  linkConfirm: (token, address, signature) => api.post("wallet/link/confirm/", { token, address, signature }).then((r) => r.data),
  linkMe: () => api.get("wallet/link/me/").then((r) => r.data),
  unlink: () => api.delete("wallet/link/me/").then((r) => r.data),
};
