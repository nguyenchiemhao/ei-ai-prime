import "@ei-ai/design-tokens/tokens.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/vietnamese-400.css";
import "@fontsource/ibm-plex-sans/vietnamese-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/vietnamese-400.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import { createBrowserRouter } from "react-router";
import { App } from "./App";
import { createI18n } from "./i18n";
import { routes } from "./routes";

const root = document.getElementById("root");
if (!root) throw new Error("#root element is missing in index.html");

createRoot(root).render(
  <StrictMode>
    <I18nextProvider i18n={createI18n()}>
      <App router={createBrowserRouter(routes)} />
    </I18nextProvider>
  </StrictMode>,
);
