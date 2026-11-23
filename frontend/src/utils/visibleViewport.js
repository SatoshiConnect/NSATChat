function isEditableTarget(target) {
  if (!target || target.disabled || target.readOnly) return false;
  if (target.isContentEditable) return true;
  return target.matches?.('input:not([type="button"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]), textarea, [contenteditable="true"]') || false;
}

/**
 * Preserve the latest-message anchor when the software keyboard resizes the
 * visible viewport. Readers who have scrolled up keep their current position.
 */
export function installViewportBottomAnchor(container, windowRef = window) {
  if (!container) return () => {};
  const visualViewport = windowRef.visualViewport;
  let shouldFollow = false;
  let firstFrame = 0;
  let secondFrame = 0;

  const cancelFrames = () => {
    if (firstFrame) windowRef.cancelAnimationFrame(firstFrame);
    if (secondFrame) windowRef.cancelAnimationFrame(secondFrame);
    firstFrame = 0;
    secondFrame = 0;
  };

  const isNearBottom = () => container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  const onUserScrollIntent = () => {
    if (shouldFollow) {
      shouldFollow = false;
      cancelFrames();
    }
  };

  const onViewportResize = () => {
    // Capture before the shell's next frame applies the new height. This also
    // keeps the last message anchored when the keyboard closes after blur.
    if (!shouldFollow) shouldFollow = isNearBottom();
    if (!shouldFollow) return;

    cancelFrames();
    // The viewport synchronizer updates the app shell on the first frame;
    // scroll after that reflow so the newest message stays above the composer.
    firstFrame = windowRef.requestAnimationFrame(() => {
      firstFrame = 0;
      secondFrame = windowRef.requestAnimationFrame(() => {
        secondFrame = 0;
        if (!shouldFollow || !container.isConnected) return;
        container.scrollTop = container.scrollHeight;
        shouldFollow = false;
      });
    });
  };

  container.addEventListener("wheel", onUserScrollIntent, { passive: true });
  container.addEventListener("touchmove", onUserScrollIntent, { passive: true });
  windowRef.addEventListener("resize", onViewportResize, { passive: true });
  visualViewport?.addEventListener("resize", onViewportResize, { passive: true });

  return () => {
    cancelFrames();
    container.removeEventListener("wheel", onUserScrollIntent);
    container.removeEventListener("touchmove", onUserScrollIntent);
    windowRef.removeEventListener("resize", onViewportResize);
    visualViewport?.removeEventListener("resize", onViewportResize);
  };
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
  let keyboardWasOpen = false;
  let baselineHeight = visualViewport?.height || windowRef.innerHeight;

  const sync = () => {
    frame = 0;
    const scale = visualViewport?.scale || 1;
    const pinchZoomed = Math.abs(scale - 1) > 0.01;
    const focused = isEditableTarget(documentRef.activeElement);
    const height = visualViewport && !pinchZoomed
      ? visualViewport.height
      : (root.clientHeight || windowRef.innerHeight);
    const viewportReduced = Boolean(
      visualViewport && !pinchZoomed && visualViewport.height < baselineHeight - 1,
    );

    // iOS Safari can keep visualViewport shorter than clientHeight after the
    // keyboard closes. Use a no-focus visual viewport baseline and explicitly
    // clear keyboard state on blur. Pinch zoom is not keyboard resizing.
    if (!focused) {
      keyboardWasOpen = false;
      if (visualViewport && !pinchZoomed) baselineHeight = visualViewport.height;
    } else if (viewportReduced) {
      keyboardWasOpen = true;
    } else {
      keyboardWasOpen = false;
    }
    const keyboardOpen = focused && keyboardWasOpen && viewportReduced;
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
