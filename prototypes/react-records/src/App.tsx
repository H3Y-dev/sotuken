import { useCallback, useEffect, useRef, useState } from "react";
import { Cog, RefreshCw, SquareX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DevicesView } from "@/components/DevicesView";
import { OverlayPreview } from "@/components/OverlayPreview";
import { RecordsView } from "@/components/RecordsView";
import { SettingsView } from "@/components/SettingsView";
import {
  ApiError,
  describeApiError,
  fetchReadings,
  fetchInspections,
  fetchInspection,
  fetchRuntime,
  fetchUsbStatus,
  downloadInspectionCsv,
} from "@/api/client";
import { download } from "@/lib/download";
import type { Filters, Reading, RuntimeStatus, UsbStatus } from "@/api/types";
import { inspectionOptions } from "@/lib/records";
import { GaugeHome } from "@/gauge/GaugeHome";
import { GaugeDetail } from "@/gauge/GaugeDetail";
import "@/gauge/gauge.css";
import { toInspection, toMeter, type Inspection } from "@/gauge/model";

type Tab = "records" | "devices" | "settings" | "gauge";

function tabFromHash(hash: string): Tab {
  if (hash.startsWith("#/gauge")) return "gauge";
  if (hash === "#settings") return "settings";
  if (hash === "#devices") return "devices";
  return "records";
}

// 旧形式 #gauge/... を #/gauge/... にそろえる。state には正規化済みだけ持つ。
const normalizeHash = (hash: string) => hash.replace(/^#gauge(?=\/|$)/, "#/gauge");

// 点検確認の hash を一覧 / 詳細 / 不正のどれかに解釈する。描画と取得で同じ結果を使う。
type GaugeRoute = { kind: "list" } | { kind: "detail"; id: string } | { kind: "invalid" };
function parseGaugeRoute(hash: string): GaugeRoute {
  if (hash === "#/gauge") return { kind: "list" };
  const match = hash.match(/^#\/gauge\/([^/]+)$/);
  if (!match) return { kind: "invalid" };
  try {
    return { kind: "detail", id: decodeURIComponent(match[1]) };
  } catch {
    return { kind: "invalid" };
  }
}

export default function App() {
  const [hash, setHash] = useState(() => normalizeHash(window.location.hash));
  const tab = tabFromHash(hash);
  const route = parseGaugeRoute(hash);
  const isDetail = route.kind === "detail";
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [gaugeError, setGaugeError] = useState("");
  const [csvBusy, setCsvBusy] = useState(false);
  const csvRequest = useRef<AbortController | null>(null);
  const [csvError, setCsvError] = useState("");
  const [csvSaved, setCsvSaved] = useState("");
  const [gaugeLoading, setGaugeLoading] = useState(false);
  const [gaugeFilter, setGaugeFilter] = useState<"all" | "action">("all");
  const [gaugeCursor, setGaugeCursor] = useState<string | undefined>();
  const loadedGaugeCursor = useRef<string | undefined>(undefined);
  const [gaugeNext, setGaugeNext] = useState<string | null>(null);
  const [gaugeTotals, setGaugeTotals] = useState({ all: 0, action: 0 });
  const [gaugeRefresh, setGaugeRefresh] = useState(0);
  const [gaugeAuto, setGaugeAuto] = useState(false);
  const [visible, setVisible] = useState(() => !document.hidden);
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
    const onVisibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const resetGaugeList = useCallback(() => {
    setInspections([]);
    setGaugeCursor(undefined);
    loadedGaugeCursor.current = undefined;
    setGaugeNext(null);
    setGaugeTotals({ all: 0, action: 0 });
  }, []);

  useEffect(() => {
    const onHash = () => {
      const nextHash = normalizeHash(window.location.hash);
      if (nextHash === hash) return;
      setSelected(null);
      csvRequest.current?.abort();
      csvRequest.current = null;
      setCsvBusy(false);
      setCsvError("");
      setCsvSaved("");
      setInspection(null);
      resetGaugeList();
      setGaugeLoading(false);
      setGaugeError("");
      setHash(nextHash);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [hash, resetGaugeList]);

  useEffect(() => {
    return () => csvRequest.current?.abort();
  }, []);

  const switchTab = (next: Tab) => {
    const target = next === "settings" ? "#settings" : next === "devices" ? "#devices" : next === "gauge" ? "#/gauge" : "#";
    if (window.location.hash !== target) {
      setSelected(null);
      window.location.hash = target;
    }
  };

  useEffect(() => {
    if (tab !== "gauge" || !visible) return;
    const target = parseGaugeRoute(hash);
    if (target.kind === "invalid") return;
    // 表示復帰時は追加済みのページを再取得しない。
    if (target.kind === "list" && gaugeCursor && gaugeCursor === loadedGaugeCursor.current) return;
    const controller = new AbortController();
    setGaugeLoading(true);
    setGaugeError("");
    const load = async () => {
      try {
        if (target.kind === "detail") {
          const data = await fetchInspection(target.id, controller.signal);
          if (!controller.signal.aborted) setInspection(toInspection(data));
        } else {
          const page = await fetchInspections(gaugeFilter, 50, gaugeCursor, controller.signal);
          if (!controller.signal.aborted) {
            const items: Inspection[] = page.items.map((item) => ({ id: item.id, name: item.name, routeId: item.route_id, routeName: item.route_name, operator: item.operator ?? "—", place: item.place ?? "—", startedAt: item.started_at, completedAt: item.completed_at, receive: item.status.state === "完了" ? "complete" : item.status.state === "不足あり" ? "short" : "receiving", missingPhotos: item.missing_photo_count, meters: item.preview.map(toMeter), summary: item.summary }));
            loadedGaugeCursor.current = gaugeCursor;
            setInspections((previous) => gaugeCursor ? [...previous, ...items] : items);
            setGaugeNext(page.next_cursor);
            setGaugeTotals({ all: page.all_total, action: page.action_total });
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          if (error instanceof ApiError && error.status === 410 && gaugeCursor) {
            resetGaugeList();
            return;
          }
          if (error instanceof ApiError && error.status === 401) setAuthExpired(true);
          setGaugeError(error instanceof ApiError && error.status === 404 ? "点検が見つかりません" : error instanceof ApiError && error.status === 410 ? "一覧の期限が切れました。更新してください" : describeApiError(error));
        }
      } finally { if (!controller.signal.aborted) setGaugeLoading(false); }
    };
    void load();
    return () => controller.abort();
  }, [tab, hash, gaugeFilter, gaugeCursor, gaugeRefresh, visible, resetGaugeList]);

  const exportCsv = async (save: boolean) => {
    if (!inspection || csvRequest.current) return;
    const controller = new AbortController();
    csvRequest.current = controller;
    const isCurrent = () => csvRequest.current === controller && !controller.signal.aborted;
    setCsvBusy(true);
    setCsvError("");
    setCsvSaved("");
    try {
      const { blob, name } = await downloadInspectionCsv(inspection.id, save, controller.signal);
      if (!isCurrent()) return;
      if (save) setCsvSaved(name);
      else download(name, blob, "text/csv;charset=utf-8");
    } catch (error) {
      if (!isCurrent()) return;
      if (error instanceof ApiError && error.status === 401) setAuthExpired(true);
      setCsvError(describeApiError(error));
    } finally {
      if (csvRequest.current === controller) {
        csvRequest.current = null;
        setCsvBusy(false);
      }
    }
  };

  useEffect(() => {
    if (tab !== "gauge" || !isDetail || !gaugeAuto || gaugeLoading) return;
    const timer = window.setTimeout(() => {
      if (!document.hidden) setGaugeRefresh((value) => value + 1);
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [tab, isDetail, gaugeAuto, gaugeLoading, gaugeRefresh]);

  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden && tab === "gauge" && isDetail && gaugeAuto) setGaugeRefresh((value) => value + 1);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [tab, isDetail, gaugeAuto]);

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
                variant={tab === "gauge" ? "secondary" : "ghost"}
                onClick={() => switchTab("gauge")}
              >点検確認</Button>
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
                variant={tab === "devices" ? "secondary" : "ghost"}
                aria-current={tab === "devices" ? "page" : undefined}
                className={
                  tab === "devices"
                    ? "border border-hairline font-bold text-ink"
                    : "text-steel"
                }
                onClick={() => switchTab("devices")}
              >
                機器登録
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

        {tab === "gauge" ? (
          <section className="gauge" aria-live="polite">
            <Button onClick={() => { setGaugeCursor(undefined); setGaugeRefresh((v) => v + 1); }}>更新</Button>
            {isDetail && <label><input type="checkbox" checked={gaugeAuto} onChange={(event) => setGaugeAuto(event.target.checked)} /> 自動更新</label>}
            {gaugeLoading && <p>点検を読み込み中…</p>}
            {gaugeError && <>
              <p role="alert">{gaugeError}</p>
              <Button onClick={() => setGaugeRefresh((v) => v + 1)}>再試行</Button>
            </>}
            {route.kind === "invalid" ? <>
              <p role="alert">点検IDが不正です</p>
              <a href="#/gauge">一覧へ戻る</a>
            </> : route.kind === "detail" ? <>
              <a href="#/gauge">一覧へ戻る</a>
              {inspection && <GaugeDetail ins={inspection} exporting={csvBusy} exportError={csvError} savedFile={csvSaved} onExport={exportCsv} />}
            </> : <>
              <GaugeHome items={inspections} filter={gaugeFilter} totals={gaugeTotals} showEmpty={!gaugeLoading && !gaugeError} onFilterChange={(value) => {
                if (value === gaugeFilter) return;
                resetGaugeList();
                setGaugeFilter(value);
              }} />
              <Button disabled={!gaugeNext || gaugeLoading || !!gaugeError} onClick={() => setGaugeCursor(gaugeNext ?? undefined)}>次のページ</Button>
            </>}
          </section>
        ) : tab === "records" ? (
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
        ) : tab === "devices" ? (
          <DevicesView onAuthExpired={() => setAuthExpired(true)} />
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
