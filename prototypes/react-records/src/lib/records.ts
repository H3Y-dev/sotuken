import type { Filters, Reading } from "../api/types";
const rank = (r: Reading) =>
  !r.device || r.status === "low_confidence"
    ? 0
    : r.status === "failed"
      ? 1
      : 2;
export const sortReadings = (rows: Reading[]) =>
  [...rows].sort(
    (a, b) => rank(a) - rank(b) || b.timestamp.localeCompare(a.timestamp),
  );
export const filterReadings = (rows: Reading[], f: Filters) =>
  rows.filter(
    (r) =>
      (f.inspection === "all" ||
        (f.inspection === "none"
          ? !r.inspection
          : r.inspection === f.inspection)) &&
      (f.device === "all" || r.device === f.device) &&
      (!f.start || r.timestamp.slice(0, 10) >= f.start) &&
      (!f.end || r.timestamp.slice(0, 10) <= f.end),
  );
export const latestPerDevice = (rows: Reading[]) => {
  const map = new Map<string, Reading>();
  for (const r of [...rows].sort((a, b) =>
    b.timestamp.localeCompare(a.timestamp),
  )) {
    const key = r.device || `名前なし-${r.id}`;
    if (!map.has(key)) map.set(key, r);
  }
  return sortReadings([...map.values()]);
};
const fields: (keyof Reading)[] = [
  "id",
  "timestamp",
  "device",
  "inspection",
  "status",
  "value",
  "version",
  "image",
];
export const toCsv = (rows: Reading[]) =>
  [
    fields.join(","),
    ...rows.map((r) =>
      fields
        .map((k) => `"${String(r[k] ?? "").replaceAll('"', '""')}"`)
        .join(","),
    ),
  ].join("\r\n");
export const toJsonl = (rows: Reading[]) =>
  rows.map((r) => JSON.stringify(r)).join("\n");
