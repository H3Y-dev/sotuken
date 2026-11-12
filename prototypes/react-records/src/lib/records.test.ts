import { describe, it, expect } from "vitest";
import { data } from "../mock/data";
import {
  filterReadings,
  latestPerDevice,
  sortReadings,
  toCsv,
  toJsonl,
} from "./records";
describe("記録", () => {
  it("点検なしと日付で絞り込む", () => {
    const r = filterReadings(data, {
      inspection: "none",
      device: "all",
      start: "2026-11-02",
      end: "2026-11-03",
    });
    expect(r.length).toBeGreaterThan(0);
    expect(
      r.every(
        (x) =>
          !x.inspection &&
          x.timestamp.slice(0, 10) >= "2026-11-02" &&
          x.timestamp.slice(0, 10) <= "2026-11-03",
      ),
    ).toBe(true);
  });
  it("機器ごとの最新を取得する", () => {
    const r = latestPerDevice(data);
    expect(r.find((x) => x.device === "メーター 01")?.timestamp).toBe(
      data
        .filter((x) => x.device === "メーター 01")
        .map((x) => x.timestamp)
        .sort()
        .at(-1),
    );
  });
  it("要確認を先に並べる", () => {
    expect(
      sortReadings(data)[0].status === "low_confidence" ||
        !sortReadings(data)[0].device,
    ).toBe(true);
  });
  it("名前なしは要確認の順位で新しい順に並ぶ", () => {
    const base = data[1];
    const rows = sortReadings([
      { ...base, id: 1, device: "", status: "ok", timestamp: "2026-11-02" },
      { ...base, id: 2, device: "機器", status: "low_confidence", timestamp: "2026-11-03" },
      { ...base, id: 3, device: "機器", status: "failed", timestamp: "2026-11-04" },
    ]);
    expect(rows.map((r) => r.id)).toEqual([2, 1, 3]);
  });
  it("CSVとJSONLを書き出す", () => {
    expect(toCsv(data.slice(0, 1))).toContain("timestamp");
    expect(JSON.parse(toJsonl(data.slice(0, 1))).id).toBe(1);
  });
});
