import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AppErrorBoundary from "./components/common/AppErrorBoundary";
import "./styles/index.css";
import { initTheme } from "./services/theme";
import { registerServiceWorker } from "./services/pwa";

initTheme();
registerServiceWorker();

// iOS Safari's layout viewport does not always follow the on-screen keyboard.
// Keep the app shell sized to the visible viewport while preserving scrolling
// inside chat lists and message panes.
function syncVisibleViewport() {
  const height = window.visualViewport?.height || window.innerHeight;
  document.documentElement.style.setProperty("--app-viewport-height", `${Math.round(height)}px`);
}
syncVisibleViewport();
window.addEventListener("resize", syncVisibleViewport, { passive: true });
window.visualViewport?.addEventListener("resize", syncVisibleViewport, { passive: true });

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
