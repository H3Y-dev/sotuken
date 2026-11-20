// --- Minimal DOM shim for running React + Base UI in Vitest's node environment ---
export class FakeEvent {
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

export class FakeNode {
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
    event.currentTarget = this;
    let cur: FakeNode | null = event.currentTarget;
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

export class FakeElement extends FakeNode {
  tagName: string;
  namespaceURI = "http://www.w3.org/1999/xhtml";
  attributes = new Map<string, string>();
  style = {
    setProperty(name: string, value: string) {
      Object.assign(this, { [name]: value });
    },
  };
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

export function setupFakeDom() {
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
