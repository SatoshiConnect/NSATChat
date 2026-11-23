import api from "../../api/client";

/** Public read operations exposed by the Wallet Integration API. */
export const walletApi = {
  read: (address) => api.get("wallet/read/", { params: { address }, timeout: 25_000 }).then((r) => r.data),
};
