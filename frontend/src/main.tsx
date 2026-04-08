import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ReferencePage from "./ReferencePage";
import "./index.css";

function getReferenceFilename() {
  const hash = window.location.hash;
  if (!hash.startsWith("#reference")) return null;
  const queryIndex = hash.indexOf("?");
  const queryString = queryIndex >= 0 ? hash.slice(queryIndex + 1) : "";
  const params = new URLSearchParams(queryString);
  return params.get("filename");
}

function Root() {
  const [referenceFilename, setReferenceFilename] = React.useState<string | null>(
    getReferenceFilename()
  );

  React.useEffect(() => {
    const onHashChange = () => setReferenceFilename(getReferenceFilename());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  if (referenceFilename !== null) {
    return <ReferencePage filename={referenceFilename} />;
  }

  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
