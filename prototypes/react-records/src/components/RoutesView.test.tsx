import { act } from "react";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Device, RouteDetail, RouteSummary } from "@/api/types";
import { FakeElement, FakeEvent, setupFakeDom } from "@/lib/fakeDom.test-support";

const mockApi = vi.hoisted(() => ({
  listRoutes: vi.fn(),
  getRoute: vi.fn(),
  createRoute: vi.fn(),
  updateRoute: vi.fn(),
  deleteRoute: vi.fn(),
  listDevices: vi.fn(),
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    listRoutes: mockApi.listRoutes,
    getRoute: mockApi.getRoute,
    createRoute: mockApi.createRoute,
    updateRoute: mockApi.updateRoute,
    deleteRoute: mockApi.deleteRoute,
    listDevices: mockApi.listDevices,
  };
});

vi.mock("@/components/ui/checkbox", () => ({
  Checkbox: ({ checked, onCheckedChange }: { checked: boolean; onCheckedChange?: (v: boolean) => void }) => (
    <button
      type="button"
      role="checkbox"
      data-checked={checked ? "true" : "false"}
      onClick={() => onCheckedChange?.(!checked)}
    />
  ),
}));

vi.mock("./QrCodeSvg", () => ({
  QrCodeSvg: ({ payload, label }: { payload: string; label?: string }) => (
    <div data-testid="route-qr" data-label={label} data-payload={payload} />
  ),
}));

const { doc: rootDoc } = setupFakeDom();

const { createRoot } = await import("react-dom/client");
const { RoutesView } = await import("./RoutesView");

function setInputValue(input: FakeElement, value: string) {
  const desc = Object.getOwnPropertyDescriptor(FakeElement.prototype, "value");
  if (desc?.set) desc.set.call(input, value);
  else input.value = value;
  input.dispatchEvent(new FakeEvent("input", { bubbles: true }));
  input.dispatchEvent(new FakeEvent("change", { bubbles: true }));
}

function findByText(container: FakeElement, text: string): FakeElement {
  const found = container.querySelectorAll("button").find((b) => b.textContent.trim() === text);
  if (!found) throw new Error(`Button not found: ${text}`);
  return found;
}

function byLabel(container: FakeElement, label: string): FakeElement {
  const found = container.querySelectorAll("button").find((b) => b.getAttribute("aria-label") === label);
  if (!found) throw new Error(`Button not found by aria-label: ${label}`);
  return found;
}

function formRows(container: FakeElement): FakeElement[] {
  return container.querySelectorAll("tbody")[0].querySelectorAll("tr");
}

const registeredDevices: Device[] = [
  {
    device_id: "D-01", device_name: "冷却水温", unit: null,
    min_value: null, max_value: null, tolerance_min: null, tolerance_max: null,
    provisional: false,
  },
  {
    device_id: "D-02", device_name: "ボイラー圧力", unit: "kPa",
    min_value: 0, max_value: 100, tolerance_min: 20, tolerance_max: 80,
    provisional: false,
  },
];

const routeA: RouteSummary = {
  route_id: "route-a", name: "Aライン", count: 2, updated_at: "2026-11-27T09:00:00+09:00",
};
const routeB: RouteSummary = {
  route_id: "route-b", name: "Bライン", count: 1, updated_at: "2026-11-26T18:30:00+09:00",
};

const detailA: RouteDetail = {
  v: 1,
  route_id: "route-a",
  name: "Aライン",
  devices: [
    { id: "D-01", name: "冷却水温" },
    { id: "D-02", name: "ボイラー圧力" },
  ],
  updated_at: "2026-11-27T09:00:00+09:00",
  qr_payload: "route:route-a:{\"devices\":[\"D-01\",\"D-02\"]}",
};

const detailNullQr: RouteDetail = {
  ...detailA,
  route_id: "route-b",
  name: "Bライン",
  devices: [{ id: "D-01", name: "冷却水温" }],
  qr_payload: null,
};

describe("RoutesView", () => {
  let root: Root | null = null;
  let container: FakeElement;

  beforeEach(() => {
    vi.clearAllMocks();
    rootDoc.body.childNodes = [];
    rootDoc.activeElement = null;
    container = rootDoc.createElement("div");
    rootDoc.body.appendChild(container);
    mockApi.listRoutes.mockResolvedValue([routeA, routeB]);
    mockApi.listDevices.mockResolvedValue(registeredDevices);
    mockApi.getRoute.mockResolvedValue(detailA);
    mockApi.deleteRoute.mockResolvedValue(undefined);
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
  });

  const mount = async () => {
    await act(async () => {
      root = createRoot(container as unknown as HTMLElement);
      root.render(<RoutesView />);
    });
  };

  const click = async (label: string) => {
    await act(async () => findByText(container, label).click());
  };

  const chooseRoute = async (label: string) => {
    await click(label);
  };

  const chooseDevice = async (label: string) => {
    await act(async () => {
      const btn = container.querySelectorAll("button").find((b) => b.getAttribute("aria-label") === label);
      if (!btn) throw new Error(`Device button not found: ${label}`);
      btn.click();
    });
  };

  it("ルート一覧と登録済み機器を取得し、選択肢に「新規作成」と件数付きルート名を表示する", async () => {
    await mount();
    expect(mockApi.listRoutes).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(mockApi.listDevices).toHaveBeenCalledWith(expect.any(AbortSignal));
    const options = container.querySelectorAll("button")
      .filter((b) => ["新規作成", "Aライン（2台）", "Bライン（1台）"].includes(b.textContent.trim()))
      .map((b) => b.textContent.trim());
    expect(options).toEqual(["新規作成", "Aライン（2台）", "Bライン（1台）"]);
    expect(container.textContent).toContain("ルート");
    expect(container.textContent).toContain("「機器登録」済みのメーターを巡回順に並べてルートを作成し、スマホ読み取り用のルートQRを発行します。");
  });

  it("登録済み機器が0件のときは #devices への案内を表示する", async () => {
    mockApi.listDevices.mockResolvedValue([]);
    await mount();
    expect(container.textContent).toContain("登録済みの機器がありません。「機器登録」から先に登録できます。");
    const link = container.querySelectorAll("a").find((a) => a.getAttribute("href") === "#devices");
    expect(link).toBeDefined();
  });

  it("ルートを選択すると詳細を取得し、QR・ルートID・更新時刻を表示する", async () => {
    await mount();
    await chooseRoute("Aライン（2台）");
    expect(mockApi.getRoute).toHaveBeenCalledWith("route-a", expect.any(AbortSignal));
    expect(container.textContent).toContain("スマホへ渡すルートQR（保存済みの内容）");
    expect(container.querySelector('[data-testid="route-qr"]')?.getAttribute("data-label")).toBe("点検ルート配布用QRコード");
    expect(container.querySelector('[data-testid="route-id"]')?.textContent).toBe("route-a");
    expect(container.querySelector('[data-testid="route-updated-at"]')?.textContent).toContain("2026");
    expect(container.textContent).toContain("このルートを削除することを確認しました");
  });

  it("qr_payload が null のときは Wi-Fi 取得の案内を表示する", async () => {
    mockApi.getRoute.mockResolvedValue(detailNullQr);
    await mount();
    await chooseRoute("Bライン（1台）");
    expect(container.textContent).toContain("機器の一覧が大きいため、Wi-Fiで取得してください。");
    expect(container.querySelector('[data-testid="route-qr"]')).toBeNull();
  });

  it("登録済み機器を追加し、重複時に明示的なエラーを出す", async () => {
    await mount();
    await chooseDevice("ボイラー圧力（D-02）");
    await click("選んだ機器を追加");
    expect(formRows(container)).toHaveLength(1);
    expect(formRows(container)[0].textContent).toContain("D-02");
    expect(formRows(container)[0].querySelectorAll("input")[0].value).toBe("ボイラー圧力");

    await chooseDevice("ボイラー圧力（D-02）");
    await click("選んだ機器を追加");
    expect(formRows(container)).toHaveLength(1);
    expect(container.textContent).toContain("すでにルートに追加されています");
  });

  it("手入力で追加し、ID 形式と重複を検証する", async () => {
    await mount();
    await act(async () => {
      setInputValue(container.querySelector("#route-manual-id")!, "MANUAL-1");
      setInputValue(container.querySelector("#route-manual-name")!, "手入力計器");
    });
    await click("手入力で追加");
    expect(formRows(container)).toHaveLength(1);
    expect(formRows(container)[0].textContent).toContain("MANUAL-1");

    await act(async () => {
      setInputValue(container.querySelector("#route-manual-id")!, "bad id!");
      setInputValue(container.querySelector("#route-manual-name")!, "不正ID");
    });
    await click("手入力で追加");
    expect(formRows(container)).toHaveLength(1);
    expect(container.textContent).toContain("半角英数字と . _ - の1〜32文字");
  });

  it("上へ・下へで並び順を入れ替え、削除で行を減らす", async () => {
    await mount();
    await chooseDevice("冷却水温（D-01）");
    await click("選んだ機器を追加");
    await chooseDevice("ボイラー圧力（D-02）");
    await click("選んだ機器を追加");
    expect(formRows(container).map((r) => r.textContent)).toEqual([
      expect.stringContaining("D-01"),
      expect.stringContaining("D-02"),
    ]);

    await act(async () => byLabel(container, "D-02 を上へ").click());
    expect(formRows(container).map((r) => r.textContent)).toEqual([
      expect.stringContaining("D-02"),
      expect.stringContaining("D-01"),
    ]);

    await act(async () => byLabel(container, "D-02 を下へ").click());
    expect(formRows(container)[0].textContent).toContain("D-01");

    await act(async () => byLabel(container, "D-01 を削除").click());
    expect(formRows(container)).toHaveLength(1);
    expect(formRows(container)[0].textContent).toContain("D-02");
  });

  it("新規ルートを保存し、一覧更新と選択・成功 Alert を表示する", async () => {
    const created: RouteDetail = {
      route_id: "route-new",
      name: "新ルート",
      devices: [{ id: "D-01", name: "冷却水温" }],
      updated_at: "2026-11-27T10:00:00+09:00",
      qr_payload: "route:route-new",
    };
    mockApi.createRoute.mockResolvedValue(created);
    mockApi.listRoutes.mockResolvedValueOnce([routeA, routeB]).mockResolvedValueOnce([
      routeA, routeB,
      { route_id: "route-new", name: "新ルート", count: 1, updated_at: created.updated_at },
    ]);

    await mount();
    await act(async () => setInputValue(container.querySelector("#route-name")!, "新ルート"));
    await chooseDevice("冷却水温（D-01）");
    await click("選んだ機器を追加");
    await click("ルートを保存");

    expect(mockApi.createRoute).toHaveBeenCalledWith({
      name: "新ルート",
      devices: [{ id: "D-01", name: "冷却水温" }],
    });
    expect(mockApi.listRoutes).toHaveBeenCalledTimes(2);
    expect(container.querySelectorAll("button").find((b) => b.textContent.trim() === "新ルート（1台）")?.getAttribute("aria-pressed")).toBe("true");
    expect(container.textContent).toContain("ルート「新ルート」を保存しました。");
  });

  it("既存ルートを更新し、updateRoute が呼ばれる", async () => {
    const saved: RouteDetail = {
      ...detailA,
      name: "Aライン改",
      devices: [{ id: "D-01", name: "冷却水温改" }],
      qr_payload: null,
    };
    mockApi.updateRoute.mockResolvedValue(saved);
    await mount();
    await chooseRoute("Aライン（2台）");
    await act(async () => {
      setInputValue(container.querySelector("#route-name")!, "Aライン改");
    });
    await act(async () => byLabel(container, "D-02 を削除").click());
    await click("ルートを保存");

    expect(mockApi.updateRoute).toHaveBeenCalledWith("route-a", {
      name: "Aライン改",
      devices: [{ id: "D-01", name: "冷却水温" }],
    });
    expect(container.textContent).toContain("ルート「Aライン改」を保存しました。");
    expect(container.textContent).toContain("Wi-Fiで取得してください");
  });

  it("ルート名が空または機器0台のときは保存しない", async () => {
    await mount();
    await click("ルートを保存");
    expect(mockApi.createRoute).not.toHaveBeenCalled();
    expect(container.textContent).toContain("ルート名は1〜64文字で入力してください。");

    await act(async () => setInputValue(container.querySelector("#route-name")!, "名前"));
    await click("ルートを保存");
    expect(mockApi.createRoute).not.toHaveBeenCalled();
    expect(container.textContent).toContain("ルートに登録する機器は1〜200台にしてください。");
  });

  it("削除は確認チェック後に有効になり、削除後は新規作成へ戻る", async () => {
    await mount();
    await chooseRoute("Aライン（2台）");
    const deleteButton = () => findByText(container, "ルートを削除");
    expect(deleteButton().disabled).toBe(true);

    const checkbox = container.querySelectorAll("button").find(
      (el) => el.getAttribute("role") === "checkbox",
    );
    expect(checkbox).toBeTruthy();
    await act(async () => checkbox!.click());
    expect(deleteButton().disabled).toBe(false);

    await click("ルートを削除");
    expect(mockApi.deleteRoute).toHaveBeenCalledWith("route-a");
    expect(container.querySelectorAll("button").find((b) => b.textContent.trim() === "新規作成")?.getAttribute("aria-pressed")).toBe("true");
    expect(container.textContent).toContain("ルートを削除しました。");
    expect(container.querySelector('[data-testid="route-qr"]')).toBeNull();
  });
});
