import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { ProductConfigProvider } from "./branding";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ProductConfigProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ProductConfigProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
