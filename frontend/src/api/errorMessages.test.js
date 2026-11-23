import assert from "node:assert/strict";
import test from "node:test";

import { errorMessage } from "./errorMessages.js";

test("shows the curated Google Contacts error instead of a Messenger network error", () => {
  const error = Object.assign(new Error("Google did not grant Contacts permission."), { code: "GOOGLE_CONTACTS_HTTP" });
  assert.equal(errorMessage(error), "Google did not grant Contacts permission.");
});

test("classifies Messenger HTTP statuses", () => {
  assert.equal(errorMessage({ isAxiosError: true, response: { status: 401, data: {} } }), "Your session expired. Sign in again and retry.");
  assert.equal(errorMessage({ isAxiosError: true, response: { status: 403, data: {} } }), "You don't have permission to do that.");
  assert.equal(errorMessage({ isAxiosError: true, response: { status: 429, data: {} } }), "Too many requests. Wait a little, then retry.");
  assert.equal(errorMessage({ isAxiosError: true, response: { status: 503, data: {} } }), "The server isn't reachable right now (it may be restarting). Please try again.");
});

test("labels only response-less Axios failures as Messenger network failures", () => {
  assert.equal(errorMessage({ isAxiosError: true, code: "ERR_NETWORK" }), "Can't reach the Messenger server. Check the connection and try again.");
  assert.equal(errorMessage(new Error("OAuth permission was cancelled.")), "Something went wrong. Please try again.");
});
