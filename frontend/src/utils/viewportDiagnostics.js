const TARGETS = [
  ".app",
  ".app > .main",
  ".conversation",
  ".conversation__body",
  ".messages",
  ".msg-row",
  ".msg-row__inner",
  ".bubble--out",
  ".composer",
  ".composer__row",
  ".composer__pill",
  ".composer__input",
  ".composer__mic",
  ".composer__action",
];

const STYLE_PROPERTIES = [
  "width", "minWidth", "maxWidth", "boxSizing", "display", "position", "left", "right",
  "transform", "flexShrink", "overflowX", "fontSize", "paddingLeft", "paddingRight",
];

function isEditable(element) {
  return Boolean(element?.matches?.("input, textarea, select, [contenteditable='true']"));
}

/** Development-only console diagnostics. Deliberately excludes element text and form values. */
export function installViewportDiagnostics(windowRef = window, documentRef = document) {
  const visualViewport = windowRef.visualViewport;
  const timers = new Set();
  let frame = 0;
  let initialFrame = 0;
  let lastPhase = "initial";
  let focusViewport = null;
  let pointerViewport = null;

  const snapshot = (phase) => {
    const root = documentRef.documentElement;
    const visibleLeft = visualViewport?.offsetLeft || 0;
    const visibleTop = visualViewport?.offsetTop || 0;
    const visibleRight = visibleLeft + (visualViewport?.width || windowRef.innerWidth);
    const visibleBottom = visibleTop + (visualViewport?.height || windowRef.innerHeight);
    const elements = TARGETS.flatMap((selector) =>
      [...documentRef.querySelectorAll(selector)].slice(-3).map((element, index) => {
        const rect = element.getBoundingClientRect();
        const style = windowRef.getComputedStyle(element);
        const computed = Object.fromEntries(STYLE_PROPERTIES.map((property) => [property, style[property]]));
        const ancestors = [];
        let ancestor = element.parentElement;
        while (ancestor && ancestors.length < 6) {
          const ancestorStyle = windowRef.getComputedStyle(ancestor);
          if (ancestorStyle.transform !== "none") {
            ancestors.push({ tag: ancestor.tagName, className: String(ancestor.className || "").slice(0, 100), transform: ancestorStyle.transform });
          }
          ancestor = ancestor.parentElement;
        }
        return {
          selector,
          index,
          tag: element.tagName,
          className: String(element.className || "").slice(0, 120),
          rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height },
          computed,
          transformedAncestors: ancestors,
          outsideVisibleViewport: rect.left < visibleLeft - 1 || rect.right > visibleRight + 1 || rect.top < visibleTop - 1 || rect.bottom > visibleBottom + 1,
        };
      }),
    );
    const active = documentRef.activeElement;
    const activeStyle = active ? windowRef.getComputedStyle(active) : null;
    const report = {
      phase,
      time: Math.round(windowRef.performance.now()),
      viewport: {
        innerWidth: windowRef.innerWidth,
        innerHeight: windowRef.innerHeight,
        clientWidth: root.clientWidth,
        scrollWidth: root.scrollWidth,
        visualWidth: visualViewport?.width ?? null,
        visualHeight: visualViewport?.height ?? null,
        scale: visualViewport?.scale ?? null,
        offsetLeft: visualViewport?.offsetLeft ?? null,
        offsetTop: visualViewport?.offsetTop ?? null,
        scrollX: windowRef.scrollX,
        scrollY: windowRef.scrollY,
      },
      activeElement: active ? {
        tag: active.tagName,
        className: String(active.className || "").slice(0, 120),
        type: active.getAttribute?.("type") || null,
        fontSize: activeStyle?.fontSize || null,
      } : null,
      elements,
      overflow: elements.filter((element) => element.outsideVisibleViewport).map(({ selector, index, rect }) => ({ selector, index, rect })),
    };
    windowRef.console.info("[mhtalk-viewport-diagnostic]", report);
  };

  const logSoon = (phase) => {
    lastPhase = phase;
    if (frame) windowRef.cancelAnimationFrame(frame);
    frame = windowRef.requestAnimationFrame(() => {
      frame = 0;
      snapshot(lastPhase);
    });
  };

  const after = (phase, delay, callback = snapshot) => {
    const timer = windowRef.setTimeout(() => {
      timers.delete(timer);
      callback(phase);
    }, delay);
    timers.add(timer);
  };

  const onPointerDown = (event) => {
    if (!event.target?.closest?.("input, textarea, select, [contenteditable='true']")) return;
    pointerViewport = visualViewport ? {
      width: visualViewport.width,
      height: visualViewport.height,
      scale: visualViewport.scale,
    } : null;
    snapshot("before-focus");
  };
  const onFocusIn = (event) => {
    if (!isEditable(event.target)) return;
    focusViewport = pointerViewport || (visualViewport ? {
      width: visualViewport.width,
      height: visualViewport.height,
      scale: visualViewport.scale,
    } : null);
    pointerViewport = null;
    logSoon("focus");
    [350, 900].forEach((delay) => after(`after-focus-${delay}ms`, delay, onFocusSettled));
  };
  const onFocusOut = (event) => {
    if (!isEditable(event.target)) return;
    snapshot("blur");
    after("after-blur-350ms", 350);
  };
  const onViewportChange = (event) => {
    if (documentRef.activeElement && isEditable(documentRef.activeElement)) logSoon(`visual-viewport-${event.type}`);
  };
  const onWindowResize = () => {
    if (documentRef.activeElement && isEditable(documentRef.activeElement)) logSoon("window-resize");
  };

  const onFocusSettled = (phase) => {
    if (!visualViewport || !focusViewport) {
      snapshot(phase.replace("after-focus", "after-focus-no-visual-viewport"));
      return;
    }
    if (Math.abs(visualViewport.scale - focusViewport.scale) > 0.01) {
      snapshot(phase.replace("after-focus", "after-focus-auto-zoom"));
      return;
    }
    if (visualViewport.height < focusViewport.height - 0.5) {
      snapshot(phase.replace("after-focus", "after-keyboard-open"));
      return;
    }
    if (Math.abs(visualViewport.width - focusViewport.width) > 0.5) {
      snapshot(phase.replace("after-focus", "after-focus-viewport-change"));
      return;
    }
    snapshot(phase.replace("after-focus", "after-focus-no-viewport-change"));
  };

  initialFrame = windowRef.requestAnimationFrame(() => {
    initialFrame = 0;
    snapshot("initial");
  });
  windowRef.addEventListener("pointerdown", onPointerDown, true);
  documentRef.addEventListener("focusin", onFocusIn, true);
  documentRef.addEventListener("focusout", onFocusOut, true);
  windowRef.addEventListener("resize", onWindowResize, { passive: true });
  visualViewport?.addEventListener("resize", onViewportChange, { passive: true });
  visualViewport?.addEventListener("scroll", onViewportChange, { passive: true });

  return () => {
    if (frame) windowRef.cancelAnimationFrame(frame);
    if (initialFrame) windowRef.cancelAnimationFrame(initialFrame);
    timers.forEach((timer) => windowRef.clearTimeout(timer));
    windowRef.removeEventListener("pointerdown", onPointerDown, true);
    documentRef.removeEventListener("focusin", onFocusIn, true);
    documentRef.removeEventListener("focusout", onFocusOut, true);
    windowRef.removeEventListener("resize", onWindowResize);
    visualViewport?.removeEventListener("resize", onViewportChange);
    visualViewport?.removeEventListener("scroll", onViewportChange);
  };
}
