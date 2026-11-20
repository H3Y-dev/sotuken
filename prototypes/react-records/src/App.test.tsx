import { act } from "react";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, downloadInspectionCsv, fetchInspection, fetchInspections } from "@/api/client";
import type { InspectionListItem, InspectionProgress } from "@/api/types";
import { download } from "@/lib/download";
import { FakeElement, FakeEvent, setupFakeDom } from "@/lib/fakeDom.test-support";

vi.mock("@/api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/client")>(),
  fetchInspections: vi.fn(),
  fetchInspection: vi.fn(),
  downloadInspectionCsv: vi.fn(),
  fetchReadings: vi.fn(async () => ({ items: [], total: 0 })),
  fetchRuntime: vi.fn(async () => ({ receiver_running: false })),
  fetchUsbStatus: vi.fn(async () => ({ enabled: false, devices: [] })),
}));
vi.mock("@/lib/download", () => ({ download: vi.fn() }));

const { doc, win } = setupFakeDom();
const location = { hash: "" };
Object.assign(win, {
  location,
  addEventListener: doc.addEventListener.bind(doc),
  removeEventListener: doc.removeEventListener.bind(doc),
  setTimeout,
  clearTimeout,
});
const { createRoot } = await import("react-dom/client");
const { default: App } = await import("./App");

function progress(id: string): InspectionProgress {
  return {
    id, name: `点検 ${id}`, route_id: "deleted", route_name: null,
    operator: null, place: null, started_at: null, completed_at: null,
    status: { state: "完了", matched: 1, missing_photos: [] },
    devices: [{
      key: "device:1", seq: null, off_route: false, device_id: "1", name: "テスト計器",
      unit: null, scale: null, tolerance: null, stage: 4, value: 1,
      read_status: "ok", sources: [], photos: 1, captured_at: null,
    }],
  };
}

function page(id: string, next_cursor: string | null = null) {
  const { devices, ...meta } = progress(id);
  const item: InspectionListItem = {
    ...meta, count: 1, missing_photo_count: 0, preview: devices,
    summary: {
      route_total: 0, route_captured: 0, route_recorded: 0, captured: 1, recorded: 1,
      missing: 0, off_route: 0, off_route_recorded: 0, warn: 0, fail: 0, wait: 0,
      out_of_tolerance: 0, all_ok: true, needs_action: false,
    },
  };
  return { items: [item], next_cursor, total: 2, all_total: 2, action_total: 1 };
}

function deferredCsv() {
  type Result = Awaited<ReturnType<typeof downloadInspectionCsv>>;
  let resolve!: (value: Result) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Result>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

describe("点検確認", () => {
  let root: Root;
  let container: FakeElement;

  beforeEach(() => {
    vi.resetAllMocks();
    location.hash = "#/gauge";
    Object.assign(doc, { hidden: false });
    vi.mocked(fetchInspection).mockImplementation(async (id) => progress(id));
    container = doc.createElement("div");
    doc.body.appendChild(container);
    root = createRoot(container as unknown as HTMLElement);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    doc.body.removeChild(container);
  });

  const render = () => act(async () => root.render(<App />));
  const hashChanged = () => act(async () => { doc.dispatchEvent(new FakeEvent("hashchange")); });
  const go = async (hash: string) => {
    location.hash = hash;
    await hashChanged();
  };
  const button = (label: string | RegExp) => {
    const found = container.querySelectorAll("button").find((el) =>
      typeof label === "string" ? el.textContent.trim() === label : label.test(el.textContent));
    if (!found) throw new Error(`Button not found: ${label}`);
    return found;
  };
  const click = (label: string | RegExp) => act(async () => button(label).click());

  it("表示復帰で取得済みのページを追加せず、画面タブに戻ると先頭から取得する", async () => {
    vi.mocked(fetchInspections).mockImplementation(async (_filter, _limit, cursor) =>
      cursor ? page("B") : page("A", "page-2"));
    await render();
    await click("次のページ");
    for (const hidden of [true, false]) {
      await act(async () => {
        Object.assign(doc, { hidden });
        doc.dispatchEvent(new FakeEvent("visibilitychange"));
      });
    }
    expect(container.textContent.match(/点検 B/g)).toHaveLength(1);
    expect(fetchInspections).toHaveBeenCalledTimes(2);
    await click("接続・設定");
    await hashChanged();
    await click("点検確認");
    await hashChanged();
    expect(fetchInspections).toHaveBeenLastCalledWith("all", 50, undefined, expect.any(AbortSignal));
    expect(container.textContent).not.toContain("点検 B");
    await click("次のページ");
    expect(container.textContent.match(/点検 B/g)).toHaveLength(1);
  });

  it("次ページの失敗後は同じカーソルで再試行し、成功したページだけを追加する", async () => {
    vi.mocked(fetchInspections)
      .mockResolvedValueOnce(page("A", "page-2"))
      .mockRejectedValueOnce(new Error("connection lost"))
      .mockResolvedValueOnce(page("B"));
    await render();
    await click("次のページ");
    expect(container.textContent).toContain("点検 A");
    await click("再試行");
    expect(vi.mocked(fetchInspections).mock.calls.map((args) => args[2])).toEqual([undefined, "page-2", "page-2"]);
    expect(container.textContent.match(/点検 [AB]/g)).toEqual(["点検 A", "点検 B"]);
  });

  it("続きのカーソルが失効したときは古い一覧を捨てて先頭から取得する", async () => {
    vi.mocked(fetchInspections)
      .mockResolvedValueOnce(page("A", "page-2"))
      .mockRejectedValueOnce(new ApiError(410, "cursor_expired"))
      .mockResolvedValueOnce(page("C"));
    await render();
    await click("次のページ");
    expect(vi.mocked(fetchInspections).mock.calls.map((args) => args[2])).toEqual([undefined, "page-2", undefined]);
    expect(container.textContent.match(/点検 [AC]/g)).toEqual(["点検 C"]);
  });

  it("フィルター変更先の取得が失敗しても以前の行とカーソルを表示しない", async () => {
    vi.mocked(fetchInspections)
      .mockResolvedValueOnce(page("A", "page-2"))
      .mockRejectedValueOnce(new Error("connection lost"))
      .mockResolvedValueOnce(page("C"));
    await render();
    await click(/対処が必要/);
    expect(container.textContent).not.toContain("点検 A");
    expect(container.textContent).not.toContain("点検はありません");
    expect(button("次のページ").disabled).toBe(true);
    await click("再試行");
    expect(fetchInspections).toHaveBeenLastCalledWith("action", 50, undefined, expect.any(AbortSignal));
    expect(container.textContent).toContain("点検 C");
  });

  it.each(["success", "error"])("点検AのCSV結果（%s）を点検Bに引き継がない", async (outcome) => {
    location.hash = "#/gauge/A";
    if (outcome === "success") vi.mocked(downloadInspectionCsv).mockResolvedValue({ blob: new Blob(), name: "A.csv" });
    else vi.mocked(downloadInspectionCsv).mockRejectedValue(new Error("connection lost"));
    await render();
    await click("CSVを保存");
    const result = outcome === "success" ? "A.csv" : container.querySelector('[role="alert"]')?.textContent;
    expect(result).toBeTruthy();
    expect(container.textContent).toContain(result);
    await go("#/gauge/B");
    expect(container.textContent).toContain("点検 B");
    expect(container.textContent).not.toContain(result);
  });

  it.each(["CSVを保存", "CSVをダウンロード", "401"] as const)("点検Aの処理中にBを開いても遅延応答（%s）が影響しない", async (outcome) => {
    location.hash = "#/gauge/A";
    const a = deferredCsv();
    const b = deferredCsv();
    vi.mocked(downloadInspectionCsv).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    await render();
    await click(outcome === "401" ? "CSVを保存" : outcome);
    const signal = vi.mocked(downloadInspectionCsv).mock.calls[0][2];
    await go("#/gauge/B");
    expect(signal?.aborted).toBe(true);
    expect(button("CSVを保存").disabled).toBe(false);
    await click("CSVを保存");
    expect(downloadInspectionCsv).toHaveBeenLastCalledWith("B", true, expect.any(AbortSignal));
    await act(async () => {
      if (outcome === "401") a.reject(new ApiError(401, "unauthenticated"));
      else a.resolve({ blob: new Blob(), name: "A.csv" });
    });
    expect(download).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("A.csv");
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(button("CSVを保存").disabled).toBe(true);
    await act(async () => b.resolve({ blob: new Blob(), name: "B.csv" }));
    expect(container.textContent).toContain("B.csv");
  });

  it("削除済みルートは一覧と詳細でルート未取得と表示し、通常の集計を出す", async () => {
    vi.mocked(fetchInspections).mockResolvedValue(page("A"));
    await render();
    expect(container.textContent).toContain("ルート未取得");
    expect(container.textContent).toContain("記録1/1台");
    await go("#/gauge/A");
    expect(container.textContent).toContain("ルート未取得");
    expect(container.textContent).toContain("撮影1/1台");
    expect(container.textContent).toContain("撮影した機器 1台");
    expect(container.textContent).not.toContain("ルート外を含む");
  });

  it.each(["#gauge", "#/gauge"])("%s形式の直リンクから詳細へ進み、戻ると一覧になる", async (baseHash) => {
    vi.mocked(fetchInspections).mockResolvedValue(page("A"));
    location.hash = `${baseHash}/A`;
    await render();
    expect(container.textContent).toContain("点検 A");
    const back = container.querySelectorAll("a").find((el) => el.textContent.trim() === "一覧へ戻る");
    expect(back?.getAttribute("href")).toBe("#/gauge");
    await go(back!.getAttribute("href")!);
    expect(location.hash).toBe("#/gauge");
    expect(container.textContent).toContain("点検確認");
    expect(container.textContent).not.toContain("撮影した機器 1台");
  });

  it.each(["#gauge/A", "#/gauge/A"])('%s CSV result and busy state', async (hash) => {
    for (const save of [true, false]) {
      for (const success of [true, false]) {
        location.hash = hash;
        const request = deferredCsv();
        vi.mocked(downloadInspectionCsv).mockReturnValueOnce(request.promise);
        await render();
        await click(save ? "CSV\u3092\u4fdd\u5b58" : "CSV\u3092\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9");
        expect(downloadInspectionCsv).toHaveBeenLastCalledWith("A", save, expect.any(AbortSignal));
        expect(button("CSV\u3092\u4fdd\u5b58").disabled).toBe(true);
        expect(button("CSV\u3092\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9").disabled).toBe(true);
        const blob = new Blob();
        await act(async () => {
          if (success) request.resolve({ blob, name: "A.csv" });
          else request.reject(new Error("connection lost"));
        });
        expect(container.textContent).toContain("\u70b9\u691c A");
        expect(button("CSV\u3092\u4fdd\u5b58").disabled).toBe(false);
        expect(button("CSV\u3092\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9").disabled).toBe(false);
        if (!success) expect(download).not.toHaveBeenCalled();
        if (!success) expect(container.querySelector('[role="alert"]')?.textContent).toBeTruthy();
        else if (save) expect(container.textContent).toContain("A.csv");
        else expect(download).toHaveBeenCalledWith("A.csv", blob, "text/csv;charset=utf-8");
        await act(async () => root.unmount());
        root = createRoot(container as unknown as HTMLElement);
        vi.mocked(download).mockClear();
      }
    }
  });

  it("seventh failure with six preview devices", async () => {
    const result = page("A");
    const item = result.items[0];
    item.count = 7;
    item.preview = Array.from({ length: 6 }, (_, i) => ({ ...item.preview[0], key: `device:${i + 1}`, device_id: `${i + 1}` }));
    Object.assign(item.summary, { captured: 7, recorded: 6, fail: 1, all_ok: false, needs_action: true });
    vi.mocked(fetchInspections).mockResolvedValue(result);
    await render();
    const row = container.querySelector('[data-kind="fail"]');
    expect(row).not.toBeNull();
    expect(row?.textContent).toContain("\u5931\u6557 1");
    expect(row?.textContent).not.toContain("\u70b9\u691c \u5b8c\u4e86");
  });

  it("does not mark an incomplete summary complete when the preview is normal", async () => {
    const result = page("A");
    Object.assign(result.items[0].summary, { fail: 0, missing: 0, needs_action: false, all_ok: false });
    vi.mocked(fetchInspections).mockResolvedValue(result);
    await render();
    const row = container.querySelector('[data-kind="wait"]');
    expect(row).not.toBeNull();
    expect(row?.textContent).not.toContain("\u70b9\u691c \u5b8c\u4e86");
  });

  it.each([["#gauge/A", "#/gauge/A"], ["#/gauge/A", "#gauge/A"]])("CSV\u51e6\u7406\u4e2d\u306b%s\u304b\u3089%s\u3078\u79fb\u3063\u3066\u3082\u51e6\u7406\u4e2d\u306e\u307e\u307e\u306b\u306a\u3089\u305a\u7d50\u679c\u304c\u51fa\u308b", async (from, to) => {
    location.hash = from;
    const request = deferredCsv();
    vi.mocked(downloadInspectionCsv).mockReturnValueOnce(request.promise);
    await render();
    await click("CSV\u3092\u4fdd\u5b58");
    await go(to);
    expect(button("CSV\u3092\u4fdd\u5b58").disabled).toBe(true);
    await act(async () => request.resolve({ blob: new Blob(), name: "A.csv" }));
    expect(container.textContent).toContain("A.csv");
    expect(button("CSV\u3092\u4fdd\u5b58").disabled).toBe(false);
    expect(button("CSV\u3092\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9").disabled).toBe(false);
  });

  it.each(["#/gauge/", "#/gauge/a/b", "#/gauge/%"])("\u4e0d\u6b63\u306ahash %s \u306f\u53d6\u5f97\u305b\u305a\u3001\u70b9\u691cID\u304c\u4e0d\u6b63\u3068\u4e00\u89a7\u3078\u623b\u308b\u30ea\u30f3\u30af\u3092\u51fa\u3059", async (hash) => {
    location.hash = hash;
    await render();
    expect(fetchInspections).not.toHaveBeenCalled();
    expect(fetchInspection).not.toHaveBeenCalled();
    expect(container.textContent).toContain("\u70b9\u691cID\u304c\u4e0d\u6b63\u3067\u3059");
    const back = Array.from(container.querySelectorAll("a")).find((el) => el.textContent.trim() === "\u4e00\u89a7\u3078\u623b\u308b");
    expect(back?.getAttribute("href")).toBe("#/gauge");
  });

  it("production CSS keeps the needle pivot and segmented progress rules", () => {
    const outDir = mkdtempSync(join(tmpdir(), "gauge-css-"));
    try {
      execFileSync(process.execPath, [resolve("node_modules/vite/bin/vite.js"), "build", "--outDir", outDir, "--emptyOutDir"], { stdio: "pipe" });
      const assets = join(outDir, "assets");
      const css = readdirSync(assets).filter((file) => file.endsWith(".css"))
        .map((file) => readFileSync(join(assets, file), "utf8")).join("\n");
      expect(css).toMatch(/\.g-needle\s*\{[^}]*transform-origin:\s*60px 60px/);
      expect(css).toMatch(/\.g-seg\[data-on=["']?true["']?\]\s*\{[^}]*background:\s*var\(--g-rule\)/);
      expect(css).toMatch(/\.g-seg\[data-on=["']?fail["']?\]\s*\{[^}]*background:\s*var\(--g-fail\)/);
      expect(css).toMatch(/\.g-seg\[data-on=["']?false["']?\]\s*\{[^}]*border-style:\s*dashed/);
    } finally {
      rmSync(outDir, { recursive: true, force: true });
    }
  });
});
