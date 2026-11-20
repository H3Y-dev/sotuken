import { act } from "react";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Device } from "@/api/types";
import { FakeElement, FakeEvent, setupFakeDom, type FakeNode } from "@/lib/fakeDom.test-support";

const mockApi = vi.hoisted(() => ({
  listDevices: vi.fn(),
  createDevice: vi.fn(),
  updateDevice: vi.fn(),
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    listDevices: mockApi.listDevices,
    createDevice: mockApi.createDevice,
    updateDevice: mockApi.updateDevice,
  };
});

const { doc: rootDoc } = setupFakeDom();

const { createRoot } = await import("react-dom/client");
const { DevicesView } = await import("./DevicesView");

function setInputValue(input: FakeElement, value: string) {
  // @ts-expect-error test shim property
  FakeElement.prototype._isFake = true;
  const desc = Object.getOwnPropertyDescriptor(FakeElement.prototype, "value");
  if (desc?.set) desc.set.call(input, value);
  else input.value = value;
  input.dispatchEvent(new FakeEvent("input", { bubbles: true }));
  input.dispatchEvent(new FakeEvent("change", { bubbles: true }));
}

function findButtonByText(container: FakeElement, label: string): FakeElement {
  const btn = container
    .querySelectorAll("button")
    .find((b) => b.textContent.trim() === label);
  if (!btn) {
    throw new Error(`Button not found: ${label}`);
  }
  return btn;
}

function pressKey(el: FakeElement, key: string) {
  const ev = new FakeEvent("keydown", { bubbles: true, cancelable: true, key });
  el.dispatchEvent(ev);
  if (key === "Enter" && !ev.defaultPrevented && el.tagName === "BUTTON") {
    el.click();
  }
  if (key === "Enter" && !ev.defaultPrevented && el.tagName === "INPUT") {
    let cur: FakeNode | null = el.parentNode;
    while (cur) {
      if (cur instanceof FakeElement && cur.tagName === "FORM") {
        cur.dispatchEvent(new FakeEvent("submit", { bubbles: true, cancelable: true }));
        break;
      }
      cur = cur.parentNode;
    }
  }
}

const sampleDevices: Device[] = [
  {
    device_id: "D-02",
    device_name: "ボイラー圧力",
    unit: "kPa",
    min_value: 0,
    max_value: 100,
    tolerance_min: 20,
    tolerance_max: 80,
    provisional: false,
  },
  {
    device_id: "D-01",
    device_name: "冷却水温",
    unit: null,
    min_value: null,
    max_value: null,
    tolerance_min: null,
    tolerance_max: null,
    provisional: true,
  },
];

describe("DevicesView", () => {
  let root: Root | null = null;
  let container: FakeElement;

  beforeEach(() => {
    vi.clearAllMocks();
    rootDoc.body.childNodes = [];
    rootDoc.activeElement = null;
    container = rootDoc.createElement("div");
    rootDoc.body.appendChild(container);
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
      root = null;
    }
  });

  const mountView = async () => {
    await act(async () => {
      root = createRoot(container as unknown as HTMLElement);
      root.render(<DevicesView />);
    });
  };

  it("renders device list sorted by device_id with 未設定 for null fields", async () => {
    mockApi.listDevices.mockResolvedValueOnce(sampleDevices);
    await mountView();

    const rows = container.querySelectorAll("tbody")[0].querySelectorAll("tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("D-01");
    expect(rows[0].textContent).toContain("冷却水温");
    expect(rows[0].textContent).toContain("未設定");
    expect(rows[1].textContent).toContain("D-02");
    expect(rows[1].textContent).toContain("0 〜 100");
    expect(rows[1].textContent).toContain("20 〜 80");
  });

  it("adds a new device, updates sorted table, and closes the form", async () => {
    mockApi.listDevices.mockResolvedValueOnce([sampleDevices[0]]);
    const created: Device = {
      device_id: "D-01",
      device_name: "吸気温度",
      unit: "C",
      min_value: -10,
      max_value: 50,
      tolerance_min: 10,
      tolerance_max: 30,
      provisional: false,
    };
    mockApi.createDevice.mockResolvedValueOnce(created);

    await mountView();

    await act(async () => {
      findButtonByText(container, "新規登録").click();
    });

    const idInput = container.querySelector("#device-id")!;
    const nameInput = container.querySelector("#device-name")!;
    const unitInput = container.querySelector("#device-unit")!;
    const minInput = container.querySelector("#device-min-value")!;
    const maxInput = container.querySelector("#device-max-value")!;
    const tolMinInput = container.querySelector("#device-tolerance-min")!;
    const tolMaxInput = container.querySelector("#device-tolerance-max")!;

    await act(async () => {
      setInputValue(idInput, "D-01");
      setInputValue(nameInput, "吸気温度");
      setInputValue(unitInput, "C");
      setInputValue(minInput, "-10");
      setInputValue(maxInput, "50");
      setInputValue(tolMinInput, "10");
      setInputValue(tolMaxInput, "30");
    });

    await act(async () => {
      findButtonByText(container, "登録する").click();
    });

    expect(mockApi.createDevice).toHaveBeenCalledWith({
      device_id: "D-01",
      device_name: "吸気温度",
      unit: "C",
      min_value: -10,
      max_value: 50,
      tolerance_min: 10,
      tolerance_max: 30,
    });
    expect(container.querySelector("form")).toBeNull();

    const rows = container.querySelectorAll("tbody")[0].querySelectorAll("tr");
    expect(rows[0].textContent).toContain("D-01");
    expect(rows[1].textContent).toContain("D-02");
  });

  it("edits a device and clears optional fields to null when left blank", async () => {
    mockApi.listDevices.mockResolvedValueOnce([sampleDevices[0]]);
    const updated: Device = {
      ...sampleDevices[0],
      device_name: "ボイラー圧力改",
      unit: null,
      min_value: null,
      max_value: null,
      tolerance_min: null,
      tolerance_max: null,
    };
    mockApi.updateDevice.mockResolvedValueOnce(updated);

    await mountView();

    await act(async () => {
      findButtonByText(container, "編集").click();
    });

    const idInput = container.querySelector("#device-id")!;
    expect(idInput.readOnly).toBe(true);

    await act(async () => {
      setInputValue(container.querySelector("#device-name")!, "ボイラー圧力改");
      setInputValue(container.querySelector("#device-unit")!, "");
      setInputValue(container.querySelector("#device-min-value")!, "");
      setInputValue(container.querySelector("#device-max-value")!, "");
      setInputValue(container.querySelector("#device-tolerance-min")!, "");
      setInputValue(container.querySelector("#device-tolerance-max")!, "");
    });

    await act(async () => {
      findButtonByText(container, "保存する").click();
    });

    expect(mockApi.updateDevice).toHaveBeenCalledWith("D-02", {
      device_name: "ボイラー圧力改",
      unit: null,
      min_value: null,
      max_value: null,
      tolerance_min: null,
      tolerance_max: null,
    });
    const rowText = container.querySelectorAll("tbody")[0].querySelectorAll("tr")[0].textContent;
    expect(rowText).toContain("ボイラー圧力改");
    expect(rowText).toContain("未設定");
  });

  it("preserves form inputs when request fails", async () => {
    mockApi.listDevices.mockResolvedValueOnce([]);
    mockApi.createDevice.mockRejectedValueOnce(new Error("Network error"));

    await mountView();

    await act(async () => {
      findButtonByText(container, "新規登録").click();
    });

    await act(async () => {
      setInputValue(container.querySelector("#device-id")!, "D-99");
      setInputValue(container.querySelector("#device-name")!, "保持確認メーター");
      setInputValue(container.querySelector("#device-tolerance-min")!, "5");
      setInputValue(container.querySelector("#device-tolerance-max")!, "15");
    });

    await act(async () => {
      findButtonByText(container, "登録する").click();
    });

    expect(container.querySelector("form")).not.toBeNull();
    expect(container.querySelector("#device-id")!.value).toBe("D-99");
    expect(container.querySelector("#device-name")!.value).toBe("保持確認メーター");
    expect(container.querySelector("#device-tolerance-min")!.value).toBe("5");
    expect(container.querySelector("#device-tolerance-max")!.value).toBe("15");
    expect(container.textContent).toContain("PC API へ接続できません");
  });

  it("shows client-side error when tolerance_min exceeds tolerance_max", async () => {
    mockApi.listDevices.mockResolvedValueOnce([]);
    await mountView();

    await act(async () => {
      findButtonByText(container, "新規登録").click();
    });

    await act(async () => {
      setInputValue(container.querySelector("#device-id")!, "D-10");
      setInputValue(container.querySelector("#device-name")!, "範囲確認");
      setInputValue(container.querySelector("#device-tolerance-min")!, "30");
      setInputValue(container.querySelector("#device-tolerance-max")!, "20");
    });

    await act(async () => {
      findButtonByText(container, "登録する").click();
    });

    expect(mockApi.createDevice).not.toHaveBeenCalled();
    expect(container.querySelector("#device-tolerance-min")!.getAttribute("aria-invalid")).toBe(
      "true",
    );
    expect(container.textContent).toContain("許容最小は許容最大以下にしてください");
  });

  it("supports adding a device using keyboard only", async () => {
    mockApi.listDevices.mockResolvedValueOnce([]);
    mockApi.createDevice.mockResolvedValueOnce({
      device_id: "D-KEY",
      device_name: "キーボード登録",
      unit: null,
      min_value: null,
      max_value: null,
      tolerance_min: 10,
      tolerance_max: 10,
      provisional: false,
    });

    await mountView();

    const addBtn = findButtonByText(container, "新規登録");
    await act(async () => {
      addBtn.focus();
      pressKey(addBtn, "Enter");
    });

    const idInput = container.querySelector("#device-id")!;
    const nameInput = container.querySelector("#device-name")!;
    const tolMinInput = container.querySelector("#device-tolerance-min")!;
    const tolMaxInput = container.querySelector("#device-tolerance-max")!;

    await act(async () => {
      idInput.focus();
      setInputValue(idInput, "D-KEY");
      nameInput.focus();
      setInputValue(nameInput, "キーボード登録");
      tolMinInput.focus();
      setInputValue(tolMinInput, "10");
      tolMaxInput.focus();
      setInputValue(tolMaxInput, "10");
      pressKey(tolMaxInput, "Enter");
    });

    expect(mockApi.createDevice).toHaveBeenCalledWith({
      device_id: "D-KEY",
      device_name: "キーボード登録",
      unit: null,
      min_value: null,
      max_value: null,
      tolerance_min: 10,
      tolerance_max: 10,
    });
    expect(container.querySelectorAll("tbody")[0].textContent).toContain("D-KEY");
  });
});
