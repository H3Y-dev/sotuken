import { act } from "react";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Device } from "@/api/types";

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

// --- Minimal DOM shim for running React + Base UI in Vitest's node environment ---
class FakeEvent {
  type: string;
  bubbles: boolean;
  cancelable: boolean;
  defaultPrevented = false;
  target: FakeNode | null = null;
  currentTarget: FakeNode | null = null;
  key?: string;

  constructor(type: string, init: { bubbles?: boolean; cancelable?: boolean; key?: string } = {}) {
    this.type = type;
    this.bubbles = Boolean(init.bubbles);
    this.cancelable = Boolean(init.cancelable);
    this.key = init.key;
  }

  preventDefault() {
    if (this.cancelable) this.defaultPrevented = true;
  }

  stopPropagation() {}
}

class FakeNode {
  nodeType: number;
  nodeName: string;
  parentNode: FakeNode | null = null;
  childNodes: FakeNode[] = [];
  ownerDocument: FakeDocument | null = null;
  listeners = new Map<string, Set<(e: FakeEvent) => void>>();

  constructor(nodeType: number, nodeName: string, doc: FakeDocument | null) {
    this.nodeType = nodeType;
    this.nodeName = nodeName;
    this.ownerDocument = doc;
  }

  appendChild<T extends FakeNode>(child: T): T {
    return this.insertBefore(child, null);
  }

  insertBefore<T extends FakeNode>(child: T, ref: FakeNode | null): T {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    if (ref === null) {
      this.childNodes.push(child);
    } else {
      const idx = this.childNodes.indexOf(ref);
      if (idx === -1) this.childNodes.push(child);
      else this.childNodes.splice(idx, 0, child);
    }
    return child;
  }

  removeChild<T extends FakeNode>(child: T): T {
    const idx = this.childNodes.indexOf(child);
    if (idx !== -1) this.childNodes.splice(idx, 1);
    child.parentNode = null;
    return child;
  }

  get firstChild(): FakeNode | null {
    return this.childNodes[0] ?? null;
  }

  get nextSibling(): FakeNode | null {
    if (!this.parentNode) return null;
    const idx = this.parentNode.childNodes.indexOf(this);
    return idx >= 0 ? (this.parentNode.childNodes[idx + 1] ?? null) : null;
  }

  get textContent(): string {
    return this.childNodes.map((c) => c.textContent).join("");
  }

  set textContent(val: string) {
    this.childNodes = [];
    if (val) {
      this.appendChild(new FakeText(val, this.ownerDocument));
    }
  }

  addEventListener(type: string, fn: (e: FakeEvent) => void) {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(fn);
  }

  removeEventListener(type: string, fn: (e: FakeEvent) => void) {
    this.listeners.get(type)?.delete(fn);
  }

  dispatchEvent(event: FakeEvent): boolean {
    if (!event.target) event.target = this;
    let cur: FakeNode | null = this;
    while (cur) {
      event.currentTarget = cur;
      const set = cur.listeners.get(event.type);
      if (set) {
        for (const fn of [...set]) fn(event);
      }
      if (!event.bubbles) break;
      cur = cur.parentNode;
    }
    return !event.defaultPrevented;
  }

  contains(other: FakeNode | null): boolean {
    let cur = other;
    while (cur) {
      if (cur === this) return true;
      cur = cur.parentNode;
    }
    return false;
  }

  getRootNode(): FakeNode {
    return this.ownerDocument ?? this;
  }
}

class FakeText extends FakeNode {
  data: string;
  constructor(data: string, doc: FakeDocument | null) {
    super(3, "#text", doc);
    this.data = data;
  }
  get textContent(): string {
    return this.data;
  }
  set textContent(val: string) {
    this.data = val;
  }
  get nodeValue(): string {
    return this.data;
  }
  set nodeValue(val: string) {
    this.data = val;
  }
}

class FakeComment extends FakeNode {
  data: string;
  constructor(data: string, doc: FakeDocument | null) {
    super(8, "#comment", doc);
    this.data = data;
  }
  get textContent(): string {
    return "";
  }
  set textContent(_val: string) {}
}

class FakeElement extends FakeNode {
  tagName: string;
  namespaceURI = "http://www.w3.org/1999/xhtml";
  attributes = new Map<string, string>();
  style: Record<string, string> = {};
  _value = "";
  _checked = false;
  disabled = false;
  readOnly = false;
  type = "";
  name = "";
  htmlFor = "";
  id = "";
  className = "";
  tabIndex = 0;
  oninput: unknown = null;

  constructor(tagName: string, doc: FakeDocument | null, ns?: string) {
    super(1, tagName.toUpperCase(), doc);
    this.tagName = tagName.toUpperCase();
    if (ns) this.namespaceURI = ns;
    if (this.tagName === "BUTTON") this.type = "submit";
    if (this.tagName === "INPUT") this.type = "text";
  }

  get value(): string {
    return this._value;
  }

  set value(v: string) {
    this._value = String(v);
  }

  get checked(): boolean {
    return this._checked;
  }

  set checked(v: boolean) {
    this._checked = Boolean(v);
  }

  setAttribute(name: string, val: string) {
    const s = String(val);
    this.attributes.set(name, s);
    if (name === "id") this.id = s;
    if (name === "class") this.className = s;
    if (name === "for") this.htmlFor = s;
    if (name === "name") this.name = s;
    if (name === "type") this.type = s;
    if (name === "disabled") this.disabled = true;
    if (name.toLowerCase() === "readonly") this.readOnly = true;
    if (name === "value") this.value = s;
  }

  removeAttribute(name: string) {
    this.attributes.delete(name);
    if (name === "disabled") this.disabled = false;
    if (name.toLowerCase() === "readonly") this.readOnly = false;
  }

  getAttribute(name: string): string | null {
    if (name === "id" && this.id) return this.id;
    if (name === "disabled") return this.disabled ? "" : null;
    if (name === "readonly") return this.readOnly ? "" : null;
    return this.attributes.get(name) ?? null;
  }

  hasAttribute(name: string): boolean {
    return this.getAttribute(name) !== null;
  }

  focus() {
    if (this.ownerDocument) {
      this.ownerDocument.activeElement = this;
    }
    this.dispatchEvent(new FakeEvent("focus", { bubbles: false }));
  }

  click() {
    if (this.disabled) return;
    this.dispatchEvent(new FakeEvent("click", { bubbles: true, cancelable: true }));
    if (this.tagName === "BUTTON" && this.type === "submit") {
      let cur: FakeNode | null = this.parentNode;
      while (cur) {
        if (cur instanceof FakeElement && cur.tagName === "FORM") {
          cur.dispatchEvent(new FakeEvent("submit", { bubbles: true, cancelable: true }));
          break;
        }
        cur = cur.parentNode;
      }
    }
  }

  querySelectorAll(selector: string): FakeElement[] {
    const results: FakeElement[] = [];
    const match = (el: FakeElement): boolean => {
      if (selector.startsWith("#")) return el.id === selector.slice(1);
      if (selector.startsWith("[")) {
        const m = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
        if (!m) return false;
        const val = el.getAttribute(m[1]);
        return m[2] !== undefined ? val === m[2] : val !== null;
      }
      return el.tagName.toLowerCase() === selector.toLowerCase();
    };
    const walk = (node: FakeNode) => {
      for (const c of node.childNodes) {
        if (c instanceof FakeElement) {
          if (match(c)) results.push(c);
          walk(c);
        }
      }
    };
    walk(this);
    return results;
  }

  querySelector(selector: string): FakeElement | null {
    return this.querySelectorAll(selector)[0] ?? null;
  }

  getBoundingClientRect() {
    return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }
}

class FakeDocument extends FakeNode {
  body: FakeElement;
  activeElement: FakeElement | null = null;
  defaultView: unknown = null;
  oninput: unknown = null;

  constructor() {
    super(9, "#document", null);
    this.ownerDocument = this;
    this.body = new FakeElement("body", this);
    this.appendChild(this.body);
  }

  createElement(tag: string): FakeElement {
    return new FakeElement(tag, this);
  }

  createElementNS(ns: string, tag: string): FakeElement {
    return new FakeElement(tag, this, ns);
  }

  createTextNode(text: string): FakeText {
    return new FakeText(text, this);
  }

  createComment(text: string): FakeComment {
    return new FakeComment(text, this);
  }

  getElementById(id: string): FakeElement | null {
    return this.body.querySelector(`#${id}`);
  }

  querySelectorAll(selector: string): FakeElement[] {
    return this.body.querySelectorAll(selector);
  }

  querySelector(selector: string): FakeElement | null {
    return this.body.querySelector(selector);
  }
}

function setupFakeDom() {
  const doc = new FakeDocument();
  class FakeIFrame extends FakeElement {}
  const win = {
    document: doc,
    Document: FakeDocument,
    Event: FakeEvent,
    MouseEvent: FakeEvent,
    KeyboardEvent: FakeEvent,
    HTMLElement: FakeElement,
    HTMLInputElement: FakeElement,
    HTMLButtonElement: FakeElement,
    HTMLFormElement: FakeElement,
    HTMLSelectElement: FakeElement,
    HTMLTextAreaElement: FakeElement,
    HTMLIFrameElement: FakeIFrame,
    SVGElement: FakeElement,
    Element: FakeElement,
    Node: FakeNode,
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    requestAnimationFrame: (cb: () => void) => setTimeout(cb, 0),
    cancelAnimationFrame: (id: ReturnType<typeof setTimeout>) => clearTimeout(id),
    navigator: { userAgent: "node" },
  };
  doc.defaultView = win;

  Object.assign(globalThis, {
    window: win,
    document: doc,
    Document: FakeDocument,
    Event: FakeEvent,
    MouseEvent: FakeEvent,
    KeyboardEvent: FakeEvent,
    HTMLElement: FakeElement,
    HTMLInputElement: FakeElement,
    HTMLButtonElement: FakeElement,
    HTMLFormElement: FakeElement,
    HTMLSelectElement: FakeElement,
    HTMLTextAreaElement: FakeElement,
    HTMLIFrameElement: FakeIFrame,
    SVGElement: FakeElement,
    Element: FakeElement,
    Node: FakeNode,
    IS_REACT_ACT_ENVIRONMENT: true,
  });

  return { doc, win };
}

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
