import { describe, it, expect } from "vitest";
import type { Reading } from "../api/types";
import {
  inspectionOptions,
  latestPerDevice,
  toHistoryCsv,
  toJsonl,
  toLatestCsv,
} from "./records";

const row = (over: Partial<Reading>): Reading => ({
  id: "1",
  reading_id: "R1",
  device_name: "メーター 01",
  device_id: "D1",
  captured_at: "2026-11-12T09:00:00+09:00",
  timestamp: "2026-11-12T09:00:05+09:00",
  received_at: "2026-11-12T09:00:04+09:00",
  value: 12.3,
  unit: null,
  status: "ok",
  stage: "done",
  confidence: 0.95,
  failure_stage: null,
  inspection_id: "I-1",
  inspection_name: "第1点検",
  route_id: "RT-1",
  image_id: "1-o-abc",
  overlay_image_id: "1-v-def",
  ...over,
});

describe("records helper parity with manager/export.py", () => {
  it("latestPerDevice keeps newest named device by timezone-aware time and keeps unnamed rows individually", () => {
    const rows = [
      // -02:00 の 23:30 は UTC 翌 01:30、+00:00 の 00:00 より新しい
      row({ id: "1", device_name: "A", captured_at: "2026-11-11T23:30:00-02:00", value: 10.5 }),
      row({ id: "2", device_name: "A", captured_at: "2026-11-12T00:00:00+00:00", value: 20.5 }),
      // 名前なし（空・未設定）は個別に行を残し、failed以外は要確認になる
      row({ id: "3", device_name: "", value: 30.1, status: "ok" }),
      row({ id: "4", device_name: "未設定", value: null, status: "failed" }),
      // 正常より要確認・失敗を上に並べる
      row({ id: "5", device_name: "B", value: 41.2, status: "low_confidence" }),
    ];
    const latest = latestPerDevice(rows);
    expect(latest.map((r) => [r.id, r.display_name, r.status_label])).toEqual([
      ["4", "名前なし", "失敗"],
      ["5", "B", "要確認"],
      ["3", "名前なし", "要確認"],
      ["1", "A", "正常"],
    ]);
  });

  it("inspectionOptions aggregates count and display name sorted by inspection_id", () => {
    const opts = inspectionOptions([
      row({ id: "1", inspection_id: "I-B", inspection_name: "午後" }),
      row({ id: "2", inspection_id: "I-A", inspection_name: "午前" }),
      row({ id: "3", inspection_id: "I-A", inspection_name: null }),
      row({ id: "4", inspection_id: null, inspection_name: null }),
    ]);
    expect(opts).toEqual([
      { id: "I-A", name: "午前", count: 2 },
      { id: "I-B", name: "午後", count: 1 },
    ]);
  });

  it("CSV and JSONL exports escape formula prefixes and never expose local file paths", () => {
    const r = row({ id: "9", device_name: "=SUM(1,2)", value: 5.5 });
    const hCsv = toHistoryCsv([r]);
    expect(hCsv).toContain('"\'=SUM(1,2)"');
    expect(hCsv).not.toContain("image_path");
    const lCsv = toLatestCsv(latestPerDevice([r]));
    expect(lCsv).toContain("メーター名称");
    expect(lCsv).toContain('"\'=SUM(1,2)"');
    expect(JSON.parse(toJsonl([r])).id).toBe("9");
  });
});
