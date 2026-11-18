import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { ApiError, describeApiError, initSession } from "./api/client";

const root = createRoot(document.getElementById("root")!);

void initSession().then(
  () => {
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  },
  (err) => {
    const message =
      err instanceof ApiError && err.status === 401
        ? "セッションが失効しました。再起動してURLを開き直してください。"
        : describeApiError(err);
    root.render(
      <StrictMode>
        <main className="mx-auto max-w-xl px-5 py-10">
          <div
            role="alert"
            data-testid="session-error"
            className="rounded-md border border-fail bg-fail-tint px-4 py-3 text-base font-bold text-fail"
          >
            {message}
          </div>
        </main>
      </StrictMode>,
    );
  },
);
