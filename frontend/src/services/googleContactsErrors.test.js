import test from "node:test";
import assert from "node:assert/strict";
import { googleContactsOAuthMessage } from "./googleContactsErrors.js";

test("explains that Testing status only permits configured test users", () => {
  const message = googleContactsOAuthMessage("access_denied");
  assert.match(message, /in Testing/);
  assert.match(message, /Audience → Test users/);
});

test("distinguishes an OAuth scope configuration error", () => {
  assert.match(googleContactsOAuthMessage("invalid_scope"), /scope setup/);
});

test("keeps other Google permission denials actionable", () => {
  assert.match(googleContactsOAuthMessage("other"), /Review the requested permission/);
});
