import { act } from "react";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import type { ManualReadingResult, Reading } from "@/api/types";
import { FakeElement, FakeEvent, setupFakeDom } from "@/lib/fakeDom.test-support";

const mockApi = vi.hoisted(() => ({
  submitManualReading: vi.fn(),
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    submitManualReading: mockApi.submitManualReading,
  };
});

const { doc } = setupFakeDom();

const { createRoot } = await import("react-dom/client");
const { ManualReadingView } = await import("./ManualReadingView");

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

function resultReading(overrides: Partial<Reading> = {}): Reading {
  return {
    id: "reading-1",
    reading_id: null,
    device_name: "Gauge_01",
    device_id: null,
    captured_at: null,
    timestamp: null,
    received_at: null,
    value: 21.5,
    unit: null,
    status: "ok",
    stage: "done",
    confidence: null,
    failure_stage: null,
    inspection_id: null,
    inspection_name: null,
    route_id: null,
    image_id: "image-1",
    overlay_image_id: "overlay-1",
    ...overrides,
  };
}

function successResult(overrides: Partial<ManualReadingResult> = {}): ManualReadingResult {
  return {
    reading: resultReading(),
    is_alert: false,
    alert_message: null,
    stage: "done",
    value: 21.5,
    ...overrides,
  };
}

function fakeFile(name = "meter.jpg"): File {
  return new File(["abc"], name, { type: "image/jpeg" });
}

function selectFile(container: FakeElement, file: File | null) {
  const input = container.querySelector("#manual-image")!;
  const desc = Object.getOwnPropertyDescriptor(FakeElement.prototype, "value");
  if (desc?.set) desc.set.call(input, file ? file.name : "");
  else input.value = file ? file.name : "";
  Object.defineProperty(input, "files", {
    configurable: true,
    value: file ? { 0: file, length: 1, item: () => file } : { length: 0 },
  });
  input.dispatchEvent(new FakeEvent("change", { bubbles: true }));
}

function byAlt(container: FakeElement, alt: string): FakeElement | undefined {
  return container.querySelectorAll("img").find((img) => img.getAttribute("alt") === alt);
}

describe("ManualReadingView", () => {
  let root: Root | null = null;
  let container: FakeElement;
  let createObjectUrl: ReturnType<typeof vi.fn>;
  let revokeObjectUrl: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    doc.body.childNodes = [];
    doc.activeElement = null;
    container = doc.createElement("div");
    doc.body.appendChild(container);
    createObjectUrl = vi.fn(() => "blob:preview");
    revokeObjectUrl = vi.fn();
    Object.assign(URL, {
      createObjectURL: createObjectUrl,
      revokeObjectURL: revokeObjectUrl,
    });
    mockApi.submitManualReading.mockResolvedValue(successResult());
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
  });

  const mount = async (onAuthExpired = vi.fn()) => {
    await act(async () => {
      root = createRoot(container as unknown as HTMLElement);
      root.render(<ManualReadingView onAuthExpired={onAuthExpired} />);
    });
    return { onAuthExpired };
  };

  const chooseFile = async (file: File | null) => {
    await act(async () => selectFile(container, file));
  };

  const submit = async () => {
    await act(async () => findByText(container, "読み取る").click());
  };

  it("既定値でフォームを表示し、画像が選ばれるまで送信ボタンを無効にする", async () => {
    await mount();
    expect(container.textContent).toContain("手動読み取り");
    expect(container.textContent).toContain("手元の画像1枚をその場でテスト読み取りし、検出オーバーレイと判定を確認します。");
    expect(container.textContent).toContain("対応形式: JPEG / PNG");
    expect((container.querySelector("#manual-device-name") as FakeElement).value).toBe("Gauge_01");
    expect((container.querySelector("#manual-threshold-min") as FakeElement).value).toBe("0");
    expect((container.querySelector("#manual-threshold-max") as FakeElement).value).toBe("40");
    const fileInput = container.querySelector("#manual-image")!;
    expect(fileInput.type).toBe("file");
    expect(fileInput.getAttribute("accept")).toBe(".jpg,.jpeg,.png,image/jpeg,image/png");
    expect(findByText(container, "読み取る").disabled).toBe(true);
  });

  it("画像を選ぶとプレビューを表示し、再選択・アンマウントで以前のURLを破棄する", async () => {
    await mount();
    await chooseFile(fakeFile());
    expect(createObjectUrl).toHaveBeenCalledWith(expect.objectContaining({ name: "meter.jpg" }));
    expect(byAlt(container, "読み取る画像")?.getAttribute("src")).toBe("blob:preview");

    createObjectUrl.mockReturnValue("blob:preview-2");
    await chooseFile(fakeFile("second.png"));
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:preview");
    expect(byAlt(container, "読み取る画像")?.getAttribute("src")).toBe("blob:preview-2");

    await act(async () => root?.unmount());
    root = null;
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:preview-2");
  });

  it.each([
    ["", "0", "40", "機器名を入力してください。"],
    ["Gauge_01", "abc", "40", "下限閾値は有限の数値で入力してください。"],
    ["Gauge_01", "0", "", "上限閾値は有限の数値で入力してください。"],
    ["Gauge_01", "50", "40", "下限閾値は上限閾値以下にしてください。"],
  ])("不正な入力（%s / %s / %s）では送信しない", async (name, min, max, message) => {
    await mount();
    await act(async () => {
      setInputValue(container.querySelector("#manual-device-name")!, name);
      setInputValue(container.querySelector("#manual-threshold-min")!, min);
      setInputValue(container.querySelector("#manual-threshold-max")!, max);
    });
    await chooseFile(fakeFile());
    await submit();
    expect(mockApi.submitManualReading).not.toHaveBeenCalled();
    expect(container.textContent).toContain(message);
  });

  it("FormData に機器名・閾値・画像を入れて送信し、結果を表示する", async () => {
    await mount();
    await act(async () => {
      setInputValue(container.querySelector("#manual-device-name")!, "計器A");
      setInputValue(container.querySelector("#manual-threshold-min")!, "1.5");
      setInputValue(container.querySelector("#manual-threshold-max")!, "30");
    });
    const file = fakeFile();
    await chooseFile(file);
    await submit();

    expect(mockApi.submitManualReading).toHaveBeenCalledTimes(1);
    const formData = mockApi.submitManualReading.mock.calls[0][0] as FormData;
    expect(formData.get("device_name")).toBe("計器A");
    expect(formData.get("threshold_min")).toBe("1.5");
    expect(formData.get("threshold_max")).toBe("30");
    expect(formData.get("image")).toBe(file);
    expect(container.textContent).toContain("読み取り結果");
    expect(container.textContent).toContain("正常");
    expect(container.textContent).toContain("21.50");
    expect(container.textContent).toContain("測定値は設定した範囲内です。");
    expect(byAlt(container, "検出結果オーバーレイ")?.getAttribute("src")).toBe(
      "/api/v1/images/overlay-1",
    );

    await act(async () => findByText(container, "クリア").click());
    expect(container.querySelector('[data-testid="manual-result"]')).toBeNull();
    expect(findByText(container, "読み取る").disabled).toBe(true);
  });

  it("送信中はボタンを無効にし「読み取り中…」を表示する", async () => {
    let resolve!: (value: ManualReadingResult) => void;
    mockApi.submitManualReading.mockReturnValueOnce(
      new Promise<ManualReadingResult>((onResolve) => { resolve = onResolve; }),
    );
    await mount();
    await chooseFile(fakeFile());
    await act(async () => { findByText(container, "読み取る").click(); });
    expect(findByText(container, "読み取り中…").disabled).toBe(true);
    await act(async () => resolve(successResult()));
    expect(findByText(container, "読み取る").disabled).toBe(false);
  });

  it("範囲外のとき警告 Alert とメッセージを表示する", async () => {
    mockApi.submitManualReading.mockResolvedValueOnce(
      successResult({
        is_alert: true,
        alert_message: "上限閾値 (40) を超過しています！",
        stage: "low_confidence",
        value: 55,
      }),
    );
    await mount();
    await chooseFile(fakeFile());
    await submit();
    expect(container.textContent).toContain("設定した範囲を外れています: 上限閾値 (40) を超過しています！");
    expect(container.textContent).not.toContain("測定値は設定した範囲内です。");
    expect(container.textContent).toContain("正常");
    expect(container.textContent).toContain("55.00");
  });

  it("alert_message が null でも警告文を表示する", async () => {
    mockApi.submitManualReading.mockResolvedValueOnce(successResult({ is_alert: true, alert_message: null }));
    await mount();
    await chooseFile(fakeFile());
    await submit();
    expect(container.textContent).toContain("設定した範囲を外れています:");
  });

  it("オーバーレイ画像IDがなければ代替メッセージを表示する", async () => {
    mockApi.submitManualReading.mockResolvedValueOnce(
      successResult({ reading: resultReading({ overlay_image_id: null }), value: null }),
    );
    await mount();
    await chooseFile(fakeFile());
    await submit();
    expect(container.textContent).toContain(
      "検出結果のオーバーレイ画像は作れませんでした（中心を検出できなかったため）。",
    );
    expect(byAlt(container, "検出結果オーバーレイ")).toBeUndefined();
    expect(container.textContent).toContain("—");
  });

  it("送信失敗時にエラー Alert を表示し、401 では認証切れを通知する", async () => {
    const { onAuthExpired } = await mount();
    await chooseFile(fakeFile());
    mockApi.submitManualReading.mockRejectedValueOnce(new ApiError(500, "internal_error"));
    await submit();
    expect(container.textContent).toContain("サーバー内部エラーが発生しました");
    expect(onAuthExpired).not.toHaveBeenCalled();

    mockApi.submitManualReading.mockRejectedValueOnce(new ApiError(401, "unauthenticated"));
    await submit();
    expect(onAuthExpired).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("セッションが失効しました");
  });
});
