import type { Reading } from "../api/types";

export const UNKNOWN_DEVICE = "未設定";

export type StatusLabel = "正常" | "要確認" | "失敗";

export type LatestReading = Reading & {
  display_name: string;
  status_label: StatusLabel;
};

export interface InspectionOption {
  id: string;
  name: string;
  count: number;
}

export function readingTimestamp(r: Pick<Reading, "captured_at" | "received_at" | "timestamp">): string {
  return r.captured_at ?? r.received_at ?? r.timestamp ?? "";
}

/** manager/export.py:_reading_time と同じ比較用ミリ秒（タイムゾーンなしはローカル/JST相当として比較） */
export function readingTimeMs(r: Pick<Reading, "captured_at" | "received_at" | "timestamp">): number {
  const iso = readingTimestamp(r);
  if (!iso) return 0;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : 0;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return iso;
  return new Date(ms).toLocaleString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Tokyo",
  });
}

export function isUnnamedDevice(deviceName: string | null | undefined): boolean {
  const name = (deviceName ?? "").trim();
  return !name || name === UNKNOWN_DEVICE;
}

export function displayNameOf(r: Pick<Reading, "device_name">): string {
  return isUnnamedDevice(r.device_name) ? "名前なし" : r.device_name.trim();
}

export function statusLabelOf(r: Pick<Reading, "device_name" | "status">): StatusLabel {
  const unnamed = isUnnamedDevice(r.device_name);
  const label: StatusLabel =
    r.status === "ok" ? "正常" : r.status === "failed" ? "失敗" : "要確認";
  return unnamed && label !== "失敗" ? "要確認" : label;
}

const PRIORITY: Record<StatusLabel, number> = {
  失敗: 0,
  要確認: 1,
  正常: 2,
};

function compareRecencyDesc(a: Reading, b: Reading): number {
  const timeDiff = readingTimeMs(b) - readingTimeMs(a);
  if (timeDiff !== 0) return timeDiff;
  return (Number(b.id) || 0) - (Number(a.id) || 0);
}

/** manager/export.py:latest_per_device と同等の採用・並び順 */
export function latestPerDevice(rows: Reading[]): LatestReading[] {
  const named = new Map<string, LatestReading>();
  const unnamed: LatestReading[] = [];

  for (const r of rows) {
    const row: LatestReading = {
      ...r,
      display_name: displayNameOf(r),
      status_label: statusLabelOf(r),
    };
    if (isUnnamedDevice(r.device_name)) {
      unnamed.push(row);
    } else {
      const key = r.device_name.trim();
      const prev = named.get(key);
      if (!prev || compareRecencyDesc(row, prev) < 0) {
        named.set(key, row);
      }
    }
  }

  const out = [...named.values(), ...unnamed];
  out.sort((a, b) => PRIORITY[a.status_label] - PRIORITY[b.status_label] || compareRecencyDesc(a, b));
  return out;
}

/** manager/export.py:inspection_options と同等 */
export function inspectionOptions(rows: Reading[]): InspectionOption[] {
  const groups = new Map<string, { name: string | null; count: number }>();
  for (const r of rows) {
    if (!r.inspection_id) continue;
    const g = groups.get(r.inspection_id) ?? { name: null, count: 0 };
    g.name = g.name || r.inspection_name;
    g.count += 1;
    groups.set(r.inspection_id, g);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([id, g]) => ({ id, name: g.name || id, count: g.count }));
}

function safeCsvCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  const safe = /^[=+\-@]/.test(s) ? `'${s}` : s;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function toHistoryCsv(rows: Reading[]): string {
  const header = [
    "id",
    "reading_id",
    "captured_at",
    "received_at",
    "timestamp",
    "device_name",
    "device_id",
    "value",
    "unit",
    "status",
    "stage",
    "confidence",
    "failure_stage",
    "inspection_id",
    "inspection_name",
    "route_id",
  ];
  const lines = rows.map((r) =>
    [
      r.id,
      r.reading_id,
      r.captured_at,
      r.received_at,
      r.timestamp,
      r.device_name,
      r.device_id,
      r.value,
      r.unit,
      r.status,
      r.stage,
      r.confidence,
      r.failure_stage,
      r.inspection_id,
      r.inspection_name,
      r.route_id,
    ]
      .map(safeCsvCell)
      .join(","),
  );
  return [header.join(","), ...lines].join("\r\n");
}

export function toLatestCsv(rows: LatestReading[]): string {
  const header = ["メーター名称", "読み取り値", "状態", "撮影・取込時刻", "記録ID"];
  const lines = rows.map((r) =>
    [r.display_name, r.value, r.status_label, readingTimestamp(r), r.id]
      .map(safeCsvCell)
      .join(","),
  );
  return [header.join(","), ...lines].join("\r\n");
}

export function toJsonl(rows: Reading[]): string {
  return rows.map((r) => JSON.stringify(r)).join("\n");
}
