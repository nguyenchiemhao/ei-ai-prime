import "@ei-ai/design-tokens/tokens.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/vietnamese-400.css";
import "@fontsource/ibm-plex-sans/vietnamese-600.css";
import "./styles.css";
import { render } from "preact";
import { App } from "./App";

const root = document.getElementById("root");
if (!root) throw new Error("#root element is missing in index.html");

render(<App />, root);
