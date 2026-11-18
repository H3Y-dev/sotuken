import type {
  Filters,
  Page,
  PairingStatus,
  Reading,
  RuntimeStatus,
  UsbStatus,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string;

  constructor(status: number, code: string, requestId = "") {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export function getPcToken(): string {
  if (typeof document === "undefined") return "";
  return (
    document
      .querySelector('meta[name="pc-token"]')
      ?.getAttribute("content")
      ?.trim() ?? ""
  );
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as {
      error?: { code?: string; request_id?: string };
    };
    return new ApiError(
      res.status,
      body?.error?.code ?? `http_${res.status}`,
      body?.error?.request_id ?? "",
    );
  } catch {
    return new ApiError(res.status, `http_${res.status}`);
  }
}

async function apiRequest(
  path: string,
  options: { method?: "GET" | "POST" | "DELETE"; body?: string; signal?: AbortSignal } = {},
): Promise<Response> {
  const method = options.method ?? "GET";
  const token = getPcToken();
  const maxBusyRetries = method === "GET" ? 2 : 0;

  for (let attempt = 0; ; attempt++) {
    const headers: Record<string, string> = {
      "X-PC-Token": token,
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, {
      method,
      headers,
      body: options.body,
      cache: "no-store",
      signal: options.signal,
    });
    if (res.ok) return res;

    const err = await parseError(res);
    // 503 db_busy は GET のみ Retry-After（既定 1 秒）後に再試行する。500 や更新系は再試行しない。
    if (
      method === "GET" &&
      res.status === 503 &&
      err.code === "db_busy" &&
      attempt < maxBusyRetries
    ) {
      const retrySec = Number(res.headers.get("Retry-After") ?? "1");
      const delayMs = Number.isFinite(retrySec) && retrySec > 0 ? Math.min(retrySec * 1000, 2000) : 1000;
      await wait(delayMs, options.signal);
      continue;
    }
    throw err;
  }
}

async function apiJson<T>(
  path: string,
  options: { method?: "GET" | "POST" | "DELETE"; body?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const res = await apiRequest(path, options);
  return (await res.json()) as T;
}

export function buildReadingsQuery(f: Filters): string {
  const params = new URLSearchParams();
  if (f.inspection === "none") {
    params.set("inspection_id", "");
  } else if (f.inspection !== "all") {
    params.set("inspection_id", f.inspection);
  }
  if (f.device !== "all") {
    params.set("device_name", f.device);
  }
  if (f.start) {
    params.set("date_from", f.start);
  }
  if (f.end) {
    params.set("date_to", f.end);
  }
  const q = params.toString();
  return q ? `?${q}` : "";
}

export function fetchReadings(filters: Filters, signal?: AbortSignal): Promise<Page<Reading>> {
  return apiJson<Page<Reading>>(`/api/v1/readings${buildReadingsQuery(filters)}`, { signal });
}

export function fetchReading(id: string, signal?: AbortSignal): Promise<Reading> {
  return apiJson<Reading>(`/api/v1/readings/${encodeURIComponent(id)}`, { signal });
}

export function fetchRuntime(signal?: AbortSignal): Promise<RuntimeStatus> {
  return apiJson<RuntimeStatus>("/api/v1/runtime", { signal });
}

export function fetchPairing(signal?: AbortSignal): Promise<PairingStatus> {
  return apiJson<PairingStatus>("/api/v1/pairing", { signal });
}

export function startPairing(): Promise<PairingStatus> {
  return apiJson<PairingStatus>("/api/v1/pairing", {
    method: "POST",
    body: "{}",
  });
}

export async function cancelPairing(): Promise<void> {
  await apiRequest("/api/v1/pairing", { method: "DELETE" });
}

export function fetchUsbStatus(signal?: AbortSignal): Promise<UsbStatus> {
  return apiJson<UsbStatus>("/api/v1/usb/status", { signal });
}

export async function fetchImageBlobUrl(
  imageId: string,
  signal?: AbortSignal,
): Promise<{ url: string; revoke: () => void } | null> {
  try {
    const res = await apiRequest(`/api/v1/images/${encodeURIComponent(imageId)}`, { signal });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    return {
      url,
      revoke: () => URL.revokeObjectURL(url),
    };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "unauthenticated") {
      return "画面の認証鍵が更新されました。ページを再読み込みしてください。";
    }
    if (err.code === "owner_unavailable") {
      return "受信・USBの所有プロセスに接続できません（起動状態を確認してください）。";
    }
    if (err.code === "db_busy") {
      return "取り込み処理がDBへ書き込み中です。少し待って自動または手動で再取得してください。";
    }
    if (err.code === "data_invalid") {
      return "DBに日時形式が不正な行があるため表示できません。";
    }
    if (err.code === "validation_failed") {
      return "検索条件が不正、または対象件数が上限（10,000件）を超えています。期間を絞ってください。";
    }
    if (err.code === "pairing_active") {
      return "QRコードはすでに作成済みです。作り直す場合は一度「登録を中止」を押してください。";
    }
    if (err.code === "internal_error") {
      return `サーバー内部エラーが発生しました（記録ID: ${err.requestId || "不明"}）。再試行せず状況を確認してください。`;
    }
    return `通信エラー（${err.status}: ${err.code}）`;
  }
  if (err instanceof Error && err.name === "AbortError") {
    return "";
  }
  return "PC API へ接続できません。サーバーが起動しているか確認してください。";
}
