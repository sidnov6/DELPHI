import { createRoot } from "react-dom/client";
import "@fontsource-variable/newsreader/index.css";
import "@fontsource-variable/newsreader/wght-italic.css";
import "@fontsource-variable/geist/index.css";
import "@fontsource-variable/geist-mono/index.css";
import "./styles.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(<App />);
