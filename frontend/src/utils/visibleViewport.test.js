import test from "node:test";
import assert from "node:assert/strict";
import { startVisibleViewportSync } from "./visibleViewport.js";

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
  const visualViewport = Object.assign(makeTarget(), { height: 800, offsetTop: 0 });
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
  assert.equal(styles.get("--app-viewport-top"), "0px");
  assert.equal(styles.get("--composer-safe-area-bottom"), "env(safe-area-inset-bottom, 0px)");
  stop();
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
