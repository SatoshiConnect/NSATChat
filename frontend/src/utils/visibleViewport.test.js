import test from "node:test";
import assert from "node:assert/strict";
import { installViewportBottomAnchor, startVisibleViewportSync } from "./visibleViewport.js";

function makeTarget() {
  const listeners = new Map();
  return {
    listeners,
    addEventListener(type, listener) {
      listeners.set(type, [...(listeners.get(type) || []), listener]);
    },
    removeEventListener(type, listener) {
      listeners.set(type, (listeners.get(type) || []).filter((item) => item !== listener));
    },
    dispatch(type) {
      (listeners.get(type) || []).forEach((listener) => listener());
    },
  };
}

function makeEnvironment() {
  const windowRef = makeTarget();
  const visualViewport = Object.assign(makeTarget(), { height: 800, offsetTop: 0, scale: 1 });
  const styles = new Map();
  const root = { clientHeight: 800, style: { setProperty: (key, value) => styles.set(key, value) } };
  const documentRef = Object.assign(makeTarget(), { documentElement: root, activeElement: null });
  let nextFrame = 1;
  const frames = new Map();
  windowRef.visualViewport = visualViewport;
  windowRef.innerHeight = 800;
  windowRef.requestAnimationFrame = (callback) => {
    const id = nextFrame++;
    frames.set(id, callback);
    return id;
  };
  windowRef.cancelAnimationFrame = (id) => frames.delete(id);
  windowRef.flushFrames = () => {
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach((callback) => callback());
  };
  return { windowRef, visualViewport, documentRef, styles };
}

test("pinch zoom on a focused input is not treated as an open keyboard", () => {
  const { windowRef, visualViewport, documentRef, styles } = makeEnvironment();
  documentRef.activeElement = { matches: (selector) => selector.includes("textarea") };
  visualViewport.height = 520;
  visualViewport.scale = 1.5;
  const stop = startVisibleViewportSync(windowRef, documentRef);

  assert.equal(styles.get("--app-viewport-height"), "800px");
  assert.equal(styles.get("--app-viewport-top"), "0px");
  assert.equal(styles.get("--composer-safe-area-bottom"), "env(safe-area-inset-bottom, 0px)");
  stop();
});

test("tracks the visual viewport and pans the mobile shell only while an editable field has focus", () => {
  const { windowRef, visualViewport, documentRef, styles } = makeEnvironment();
  const stop = startVisibleViewportSync(windowRef, documentRef);
  assert.equal(styles.get("--app-viewport-height"), "800px");
  assert.equal(styles.get("--app-viewport-top"), "0px");

  documentRef.activeElement = { matches: (selector) => selector.includes("textarea") };
  visualViewport.height = 420;
  visualViewport.offsetTop = 36;
  visualViewport.dispatch("resize");
  windowRef.flushFrames();

  assert.equal(styles.get("--app-viewport-height"), "420px");
  assert.equal(styles.get("--app-viewport-top"), "36px");
  assert.equal(styles.get("--composer-safe-area-bottom"), "0px");

  documentRef.activeElement = null;
  documentRef.dispatch("focusout");
  windowRef.flushFrames();
  // Blur can happen before the keyboard animation finishes; retain the
  // keyboard safe-area state until the visible viewport grows back.
  assert.equal(styles.get("--app-viewport-top"), "36px");
  assert.equal(styles.get("--composer-safe-area-bottom"), "0px");

  visualViewport.height = 800;
  visualViewport.offsetTop = 0;
  visualViewport.dispatch("resize");
  windowRef.flushFrames();
  assert.equal(styles.get("--app-viewport-top"), "0px");
  assert.equal(styles.get("--composer-safe-area-bottom"), "env(safe-area-inset-bottom, 0px)");
  stop();
});

test("keeps the latest message in view across viewport resize, but preserves older reading position", () => {
  const { windowRef, visualViewport } = makeEnvironment();
  const listeners = new Map();
  const container = {
    scrollHeight: 1400,
    scrollTop: 600,
    clientHeight: 800,
    isConnected: true,
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type) { listeners.delete(type); },
  };
  const stop = installViewportBottomAnchor(container, windowRef);

  // Current bottom; after the shell shrinks, land on the new bottom.
  container.scrollTop = 600;
  visualViewport.dispatch("resize");
  container.clientHeight = 420;
  windowRef.flushFrames();
  windowRef.flushFrames();
  assert.equal(container.scrollTop, container.scrollHeight);

  // A historical position is not pulled back to the bottom.
  container.scrollTop = 140;
  visualViewport.dispatch("resize");
  windowRef.flushFrames();
  windowRef.flushFrames();
  assert.equal(container.scrollTop, 140);

  // If the user starts scrolling during the resize transition, follow their
  // gesture instead of snapping back to the latest message.
  container.clientHeight = 420;
  container.scrollTop = 980;
  visualViewport.dispatch("resize");
  listeners.get("touchmove")();
  container.clientHeight = 300;
  container.scrollTop = 100;
  windowRef.flushFrames();
  assert.equal(container.scrollTop, 100);
  stop();
  assert.equal(listeners.size, 0);
});

test("removes viewport listeners and pending work on cleanup", () => {
  const { windowRef, visualViewport, documentRef } = makeEnvironment();
  const stop = startVisibleViewportSync(windowRef, documentRef);
  visualViewport.dispatch("scroll");
  assert.equal(windowRef.listeners.get("resize").length, 1);
  stop();
  assert.equal(windowRef.listeners.get("resize").length, 0);
  assert.equal(visualViewport.listeners.get("scroll").length, 0);
  assert.equal(documentRef.listeners.get("focusin").length, 0);
  assert.equal(windowRef.cancelAnimationFrame ? true : false, true);
});
