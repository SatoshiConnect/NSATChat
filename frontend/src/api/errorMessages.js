/** Turn errors into short, user-safe messages without confusing provider and API failures. */
export function errorMessage(error, fallback = "Something went wrong. Please try again.") {
  // Provider SDK and People API errors are not Axios responses. Their code is
  // assigned only by the Google Contacts service and the message is curated.
  if (typeof error?.code === "string" && error.code.startsWith("GOOGLE_") && typeof error.message === "string") {
    return error.message;
  }
  const data = error?.response?.data;
  if (typeof data === "string" && data.length < 300 && !data.trim().startsWith("<")) return data;
  if (typeof data?.detail === "string") return data.detail;
  if (typeof data?.error === "string") return data.error;
  if (typeof data?.message === "string" && error?.response?.status >= 400) return data.message;
  if (data && typeof data === "object") {
    const parts = Object.entries(data).map(([field, value]) => {
      const text = Array.isArray(value) ? value.map(String).join(" ") : typeof value === "object" ? JSON.stringify(value) : String(value);
      return field === "non_field_errors" || field === "detail" ? text : `${field.replace(/_/g, " ")}: ${text}`;
    });
    if (parts.length) return parts.join(" ");
  }
  const status = error?.response?.status;
  if (status === 502 || status === 503 || status === 504) return "The server isn't reachable right now (it may be restarting). Please try again.";
  if (status >= 500) return "The service is temporarily unavailable. Please try again.";
  if (status === 413) return "This file is too large to upload.";
  if (status === 401) return "Your session expired. Sign in again and retry.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 429) return "Too many requests. Wait a little, then retry.";
  if (error?.isAxiosError && !error.response) return "Can't reach the Messenger server. Check the connection and try again.";
  return fallback;
}
