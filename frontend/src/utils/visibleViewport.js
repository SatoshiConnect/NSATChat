function isEditableTarget(target) {
  if (!target || target.disabled || target.readOnly) return false;
  if (target.isContentEditable) return true;
  return target.matches?.('input:not([type="button"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]), textarea, [contenteditable="true"]') || false;
}

/**
 * Keep the mobile app shell aligned to the visible viewport while iOS pans or
 * resizes it for the software keyboard. The visual viewport is the single
 * source of dimensions; no keyboard-height estimate is applied to the shell.
 */
export function startVisibleViewportSync(windowRef = window, documentRef = document) {
  const root = documentRef.documentElement;
  const visualViewport = windowRef.visualViewport;
  let frame = 0;

  const sync = () => {
    frame = 0;
    const scale = visualViewport?.scale || 1;
    const isPinchZoomed = Math.abs(scale - 1) > 0.01;
    const height = visualViewport && !isPinchZoomed ? visualViewport.height : (root.clientHeight || windowRef.innerHeight);
    const keyboardOpen = Boolean(
      visualViewport &&
      !isPinchZoomed &&
      isEditableTarget(documentRef.activeElement) &&
      visualViewport.height < root.clientHeight,
    );
    const top = keyboardOpen ? Math.max(0, visualViewport.offsetTop || 0) : 0;

    root.style.setProperty("--app-viewport-height", `${Math.round(height)}px`);
    root.style.setProperty("--app-viewport-top", `${Math.round(top)}px`);
    root.style.setProperty("--composer-safe-area-bottom", keyboardOpen ? "0px" : "env(safe-area-inset-bottom, 0px)");
  };

  const scheduleSync = () => {
    if (frame) windowRef.cancelAnimationFrame(frame);
    frame = windowRef.requestAnimationFrame(sync);
  };

  sync();
  windowRef.addEventListener("resize", scheduleSync, { passive: true });
  windowRef.addEventListener("orientationchange", scheduleSync, { passive: true });
  documentRef.addEventListener("focusin", scheduleSync, true);
  documentRef.addEventListener("focusout", scheduleSync, true);
  visualViewport?.addEventListener("resize", scheduleSync, { passive: true });
  visualViewport?.addEventListener("scroll", scheduleSync, { passive: true });

  return () => {
    if (frame) windowRef.cancelAnimationFrame(frame);
    windowRef.removeEventListener("resize", scheduleSync);
    windowRef.removeEventListener("orientationchange", scheduleSync);
    documentRef.removeEventListener("focusin", scheduleSync, true);
    documentRef.removeEventListener("focusout", scheduleSync, true);
    visualViewport?.removeEventListener("resize", scheduleSync);
    visualViewport?.removeEventListener("scroll", scheduleSync);
  };
}
