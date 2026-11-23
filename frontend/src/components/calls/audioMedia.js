export const AUDIO_PROCESSING_OPTIONS = ["echoCancellation", "noiseSuppression", "autoGainControl"];

/** Request browser AEC/NS/AGC where the media stack advertises support. */
export function callAudioConstraints(supported = null) {
  const constraints = Object.fromEntries(AUDIO_PROCESSING_OPTIONS.map((name) => [name, true]));
  if (!supported) return constraints;
  return Object.fromEntries(Object.entries(constraints).filter(([name]) => supported[name]));
}

/** Keep one stable remote stream per peer and ignore duplicate ontrack events. */
export function addRemoteTrack(streams, peerId, track, createStream = () => new MediaStream()) {
  let stream = streams.get(peerId);
  if (!stream) {
    stream = createStream();
    streams.set(peerId, stream);
  }
  if (!stream.getTracks().includes(track)) stream.addTrack(track);
  return stream;
}

/** Read the browser's effective settings; null means the setting is unreported. */
export function readAudioProcessing(track) {
  const settings = track?.getSettings?.() || {};
  return Object.fromEntries(AUDIO_PROCESSING_OPTIONS.map((name) => [name, typeof settings[name] === "boolean" ? settings[name] : null]));
}
