export function googleContactsOAuthMessage(code) {
  if (code === "access_denied") {
    return "Google didn't grant Contacts access. This app is in Testing, so use a Google account listed under Google Cloud Console → Google Auth Platform → Audience → Test users.";
  }
  if (code === "invalid_scope") {
    return "Google Contacts permission isn't configured for this app yet. Ask the SatoshiCore administrator to finish OAuth scope setup.";
  }
  return "Google Contacts permission was not granted. Review the requested permission and try again.";
}
