import type { Reading } from "../api/types";
export const data: Reading[] = Array.from({ length: 180 }, (_, i) => ({
  id: i + 1,
  timestamp: new Date(
    Date.UTC(2026, 10, 1 + Math.floor(i / 48), (i % 48) / 2, (i % 2) * 30),
  ).toISOString(),
  device:
    i % 31 === 0 ? "" : `メーター ${String((i % 12) + 1).padStart(2, "0")}`,
  inspection: i % 5 === 0 ? "" : ["定期点検", "日常点検", "設備点検"][i % 3],
  status: i % 11 === 0 ? "failed" : i % 7 === 0 ? "low_confidence" : "ok",
  value: i % 11 === 0 ? null : Math.round((20 + (i % 12) + i / 10) * 10) / 10,
  version: `v${1 + (i % 3)}`,
  image: `dummy-${String(i + 1).padStart(3, "0")}.svg`,
}));
