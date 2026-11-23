import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AppErrorBoundary from "./components/common/AppErrorBoundary";
import "./styles/index.css";
import { initTheme } from "./services/theme";
import { registerServiceWorker } from "./services/pwa";
import { startVisibleViewportSync } from "./utils/visibleViewport";

initTheme();
registerServiceWorker();

// iOS Safari can both resize and pan the visual viewport when its keyboard opens.
// Keep one viewport synchronizer for the app shell and composer safe area.
startVisibleViewportSync();

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
