import { useCallback, useEffect, useRef, useState } from "react";
import { Cog, RefreshCw, SquareX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { OverlayPreview } from "@/components/OverlayPreview";
import { RecordsView } from "@/components/RecordsView";
import { SettingsView } from "@/components/SettingsView";
import {
  ApiError,
  describeApiError,
  fetchReadings,
  fetchRuntime,
  fetchUsbStatus,
} from "@/api/client";
import type { Filters, Reading, RuntimeStatus, UsbStatus } from "@/api/types";
import { inspectionOptions } from "@/lib/records";

type Tab = "records" | "settings";

function tabFromHash(hash: string): Tab {
  return hash === "#settings" ? "settings" : "records";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(() => tabFromHash(window.location.hash));
  const [rows, setRows] = useState<Reading[]>([]);
  const [total, setTotal] = useState(0);
  const [knownDevices, setKnownDevices] = useState<string[]>([]);
  const [knownInspections, setKnownInspections] = useState<
    { id: string; name: string; count: number }[]
  >([]);
  const [filters, setFilters] = useState<Filters>({
    inspection: "all",
    device: "all",
    start: "",
    end: "",
  });
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [updatedAt, setUpdatedAt] = useState("");
  const [readingsError, setReadingsError] = useState("");
  const [authExpired, setAuthExpired] = useState(false);
  const [selected, setSelected] = useState<Reading | null>(null);

  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [usb, setUsb] = useState<UsbStatus | null>(null);
  const [runtimeError, setRuntimeError] = useState("");
  const lastRuntimeFetchRef = useRef(0);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const switchTab = (next: Tab) => {
    const target = next === "settings" ? "#settings" : "#";
    if (window.location.hash !== target) {
      window.location.hash = target;
    }
    setTab(next);
  };

  const refreshReadings = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const page = await fetchReadings(filters, signal);
        if (signal?.aborted) return;
        setRows(page.items);
        setTotal(page.total);
        setReadingsError("");
        setAuthExpired(false);
        setUpdatedAt(
          new Date().toLocaleTimeString("ja-JP", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            timeZone: "Asia/Tokyo",
          }),
        );
        const isUnfiltered =
          filters.inspection === "all" &&
          filters.device === "all" &&
          !filters.start &&
          !filters.end;
        if (isUnfiltered) {
          setKnownDevices(
            [...new Set(page.items.map((r) => r.device_name).filter(Boolean))].sort(),
          );
          setKnownInspections(inspectionOptions(page.items));
        } else {
          setKnownDevices((prev) =>
            [...new Set([...prev, ...page.items.map((r) => r.device_name).filter(Boolean)])].sort(),
          );
        }
      } catch (err) {
        if (signal?.aborted) return;
        if (err instanceof ApiError && err.code === "unauthenticated") {
          setAuthExpired(true);
        }
        const msg = describeApiError(err);
        if (msg) setReadingsError(msg);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [filters],
  );

  const refreshRuntimeAndUsb = useCallback(async (signal?: AbortSignal) => {
    lastRuntimeFetchRef.current = Date.now();
    try {
      const [rt, usbRes] = await Promise.all([
        fetchRuntime(signal),
        fetchUsbStatus(signal),
      ]);
      if (signal?.aborted) return;
      setRuntime(rt);
      setUsb(usbRes);
      setRuntimeError("");
      setAuthExpired(false);
    } catch (err) {
      if (signal?.aborted) return;
      if (err instanceof ApiError && err.code === "unauthenticated") {
        setAuthExpired(true);
      }
      const msg = describeApiError(err);
      if (msg) setRuntimeError(msg);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshReadings(controller.signal);
    return () => controller.abort();
  }, [refreshReadings]);

  useEffect(() => {
    if (!autoRefresh) return;
    const controller = new AbortController();
    const id = setInterval(() => {
      void refreshReadings(controller.signal);
    }, 5000);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [autoRefresh, refreshReadings]);

  useEffect(() => {
    const controller = new AbortController();
    if (Date.now() - lastRuntimeFetchRef.current >= 1500) {
      void refreshRuntimeAndUsb(controller.signal);
    }
    const intervalMs = tab === "settings" ? 2000 : 10000;
    const id = setInterval(() => {
      void refreshRuntimeAndUsb(controller.signal);
    }, intervalMs);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [tab, refreshRuntimeAndUsb]);

  return (
    <div className="min-h-screen bg-panel text-text">
      <header className="bg-dial">
        <div className="mx-auto flex max-w-[1760px] flex-wrap items-center justify-between gap-4 px-5 py-3">
          <div className="flex flex-wrap items-center gap-4">
            <a
              href="#/"
              onClick={(e) => {
                e.preventDefault();
                switchTab("records");
              }}
              className="flex items-center gap-2.5 text-xl font-bold text-ink no-underline"
            >
              <span className="grid size-8 place-items-center rounded bg-ink text-white">
                <Cog aria-hidden className="size-5" />
              </span>
              点検記録
            </a>
            <nav aria-label="画面切り替え" className="flex items-center gap-2">
              <Button
                type="button"
                size="field"
                variant={tab === "records" ? "secondary" : "ghost"}
                aria-current={tab === "records" ? "page" : undefined}
                className={
                  tab === "records"
                    ? "border border-hairline font-bold text-ink"
                    : "text-steel"
                }
                onClick={() => switchTab("records")}
              >
                機器の記録
              </Button>
              <Button
                type="button"
                size="field"
                variant={tab === "settings" ? "secondary" : "ghost"}
                aria-current={tab === "settings" ? "page" : undefined}
                className={
                  tab === "settings"
                    ? "border border-hairline font-bold text-ink"
                    : "text-steel"
                }
                onClick={() => switchTab("settings")}
              >
                接続・設定
              </Button>
            </nav>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-base text-steel">
            <span className="inline-flex items-center gap-2" data-testid="header-receiver-status">
              <span
                aria-hidden
                className={`size-2.5 rounded-full ${
                  runtimeError
                    ? "bg-fail"
                    : runtime?.receiver_running
                      ? "bg-ok"
                      : "bg-rule"
                }`}
              />
              {runtimeError
                ? "所有プロセス未接続"
                : runtime?.receiver_running
                  ? "受信口 待ち受け中"
                  : "受信口 停止中"}
            </span>
            {usb?.enabled && (
              <span className="g-num text-steel" data-testid="header-usb-status">
                USB {usb.running ? `動作中(${usb.devices.length}台)` : "停止"}
              </span>
            )}
          </div>
        </div>
        <div className="g-tickrule" aria-hidden="true" />
      </header>

      <main className="mx-auto flex max-w-[1760px] flex-col gap-5 px-5 py-6">
        {authExpired && (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-fail bg-fail-tint px-4 py-3 text-base font-bold text-fail"
          >
            <span className="flex items-center gap-2">
              <SquareX aria-hidden className="size-5 shrink-0" />
              サーバー再起動などにより認証鍵が更新されました。画面を再読み込みしてください。
            </span>
            <Button
              type="button"
              size="field"
              variant="outline"
              onClick={() => window.location.reload()}
            >
              <RefreshCw aria-hidden />
              再読み込み
            </Button>
          </div>
        )}

        {readingsError && tab === "records" && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-fail bg-fail-tint px-4 py-3 text-base font-bold text-fail"
          >
            <SquareX aria-hidden className="size-5 shrink-0" />
            {readingsError}
          </div>
        )}

        {tab === "records" ? (
          <RecordsView
            rows={rows}
            total={total}
            knownDevices={knownDevices}
            knownInspections={knownInspections}
            filters={filters}
            onFiltersChange={setFilters}
            onRefresh={() => void refreshReadings()}
            loading={loading}
            autoRefresh={autoRefresh}
            onAutoRefreshChange={setAutoRefresh}
            updatedAt={updatedAt}
            onSelectReading={setSelected}
          />
        ) : (
          <SettingsView
            runtime={runtime}
            runtimeError={runtimeError}
            usb={usb}
            onRefreshRuntime={() => refreshRuntimeAndUsb()}
          />
        )}
      </main>

      {selected && (
        <OverlayPreview reading={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
