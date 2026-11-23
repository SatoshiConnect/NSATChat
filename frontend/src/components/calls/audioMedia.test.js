import test from "node:test";
import assert from "node:assert/strict";
import { addRemoteTrack, callAudioConstraints, readAudioProcessing } from "./audioMedia.js";

test("requests WebRTC echo and noise processing when support is unknown", () => {
  assert.deepEqual(callAudioConstraints(), {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  });
});

test("only requests processing constraints advertised by the browser", () => {
  assert.deepEqual(callAudioConstraints({ echoCancellation: true, noiseSuppression: false }), { echoCancellation: true });
});

test("keeps one remote stream and ignores repeated track events", () => {
  const streams = new Map();
  const track = { kind: "audio" };
  let created = 0;
  const createStream = () => {
    created += 1;
    const tracks = [];
    return { getTracks: () => tracks, addTrack: (newTrack) => tracks.push(newTrack) };
  };
  const first = addRemoteTrack(streams, 9, track, createStream);
  const second = addRemoteTrack(streams, 9, track, createStream);
  assert.equal(first, second);
  assert.equal(created, 1);
  assert.deepEqual(first.getTracks(), [track]);
});

test("reports effective browser processing settings without guessing", () => {
  assert.deepEqual(readAudioProcessing({ getSettings: () => ({ echoCancellation: true, autoGainControl: false }) }), {
    echoCancellation: true,
    noiseSuppression: null,
    autoGainControl: false,
  });
});
