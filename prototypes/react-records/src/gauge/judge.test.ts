import { describe, it, expect } from "vitest";
import { inspections, type MeterResult } from "../mock/inspections";
import { formatValue, judge, summarize, validRange } from "./judge";

const ins = (id: string) => inspections.find((i) => i.id === id)!;
const multi = ins("I-MULTI-20261112");
const meter = (i: string, id: string) => ins(i).meters.find((m) => m.id === id)!;
const base: MeterResult = multi.meters[0];

describe("計器盤の判定", () => {
  it("通し試験の形: 撮り忘れ・ルート外・要確認を区別する", () => {
    expect(judge(meter("I-MULTI-20261112", "SYN-006")).kind).toBe("missing");
    expect(judge(meter("I-MULTI-20261112", "SYN-004")).kind).toBe("warn"); // 確からしさが低い
    expect(judge(meter("I-MULTI-20261112", "SYN-001")).kind).toBe("ok");
    const s = summarize(multi);
    expect(s.routeTotal).toBe(5);
    expect(s.routeCaptured).toBe(4);
    expect(s.offRoute.map((m) => m.id)).toEqual(["SYN-005"]);
    expect(s.photos).toBe(6);
    expect(s.needsAction).toBe(true);
    expect(s.allOk).toBe(false);
  });

  it("許容範囲の外でも読み取れていれば正常のまま、補助の注意だけ立てる", () => {
    const r = judge(meter("I-MULTI-20261112", "SYN-002")); // 36.75 / 許容 20〜35
    expect(r).toEqual({ kind: "ok", reasons: [], outOfTolerance: true });
    const s = summarize(multi);
    expect(s.outOfTolerance.map((m) => m.id)).toEqual(["SYN-002"]);
    expect(s.warn.map((m) => m.id)).toEqual(["SYN-004"]);
    expect(s.readSuccess).toBe(5);
  });

  it("名前なしは値が読めても要確認、許容範囲外の注意は付けない", () => {
    const r = judge({ ...base, id: "", value: 99 });
    expect(r.kind).toBe("warn");
    expect(r.reasons).toContain("名前なし");
    expect(r.outOfTolerance).toBe(false);
  });

  it("失敗は段階より先に見る: stage<4 でも failed なら失敗", () => {
    expect(judge({ ...base, stage: 2, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge({ ...base, stage: 1, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge({ ...base, stage: 4, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge({ ...base, stage: 3, value: null, status: null }).kind).toBe("fail");
    expect(judge(meter("I-20261112-PM", "A-105")).kind).toBe("fail");
  });

  it("途中: 未着・読み取り待ちは待ち、読み取り済み（記録待ち）は値を持ったまま待ち", () => {
    expect(judge({ ...base, stage: 1, value: null, status: null })).toEqual({ kind: "wait", reasons: ["PCに未着"], outOfTolerance: false });
    expect(judge({ ...base, stage: 2, value: null, status: null }).reasons).toEqual(["読み取り待ち"]);
    const a104 = meter("I-20261112-PM", "A-104");
    expect(a104.stage).toBe(3);
    expect(a104.value).not.toBeNull();
    expect(judge(a104)).toEqual({ kind: "wait", reasons: ["記録待ち"], outOfTolerance: false });
    expect(summarize(ins("I-20261112-PM")).readSuccess).toBe(4);
  });

  it("撮り忘れは理由「撮り忘れ」", () => {
    expect(judge({ ...base, stage: 0, value: null, status: null })).toEqual({ kind: "missing", reasons: ["撮り忘れ"], outOfTolerance: false });
  });

  it("目盛り範囲の外は要確認。目盛りが未設定・不正なら見ない", () => {
    expect(judge({ ...base, value: 30 }).reasons).toContain("目盛り範囲の外"); // 目盛り 0〜25
    expect(judge({ ...base, value: -1 }).reasons).toContain("目盛り範囲の外");
    expect(judge({ ...base, value: 30, scale: null, tolerance: null }).kind).toBe("ok");
    expect(judge({ ...base, value: 30, scale: [5, 5], tolerance: null }).kind).toBe("ok");
    expect(judge({ ...base, value: 30, scale: [10, 0], tolerance: null }).kind).toBe("ok");
  });

  it("任意項目が未設定でも壊れない（単位・目盛り・許容範囲）", () => {
    const noTol = meter("I-20261110-01", "A-101");
    expect(noTol.tolerance).toBeNull();
    expect(judge(noTol)).toEqual({ kind: "ok", reasons: [], outOfTolerance: false });
    const noUnit = meter("I-20261110-01", "A-110");
    expect(noUnit.unit).toBe("");
    expect(judge(noUnit).kind).toBe("ok");
    const nameless = meter("I-20261110-01", "");
    expect(nameless.scale).toBeNull();
    expect(nameless.unit).toBeNull();
    expect(judge(nameless).kind).toBe("warn");
    // 許容範囲の上下が逆なら許容範囲外とは言わない
    expect(judge({ ...base, value: 20, tolerance: [14, 8] }).outOfTolerance).toBe(false);
  });

  it("全部正常で受信も完了なら対処不要", () => {
    const am = ins("I-20261111-AM");
    const s = summarize(am);
    expect(s.needsAction).toBe(false);
    expect(s.allOk).toBe(true);
    expect(s.outOfTolerance).toEqual([]);
  });
});

describe("値の書き方と目盛りの検査", () => {
  it("formatValue は目盛りの最大で桁を決め、未設定でも壊れない", () => {
    expect(formatValue(10.78, 25)).toBe("10.78");
    expect(formatValue(36.75, 60)).toBe("36.8");
    expect(formatValue(47, null)).toBe("47.0");
    expect(formatValue(47)).toBe("47.0");
  });

  it("validRange は null・最小>=最大・数でないものを弾く", () => {
    expect(validRange([0, 1])).toBe(true);
    expect(validRange(null)).toBe(false);
    expect(validRange([1, 1])).toBe(false);
    expect(validRange([2, 1])).toBe(false);
    expect(validRange([0, Number.NaN])).toBe(false);
    expect(validRange([0, Infinity])).toBe(false);
  });
});


describe("A-1 集計", () => {
  it("許容外は読取成功・記録済みのまま対処対象", () => {
    const s = summarize({ ...multi, receive: "complete", meters: [{ ...base, stage: 4, status: "ok", value: 40, scale: [0, 60], tolerance: [0, 35] }] });
    expect(s.recorded).toBe(1);
    expect(s.readSuccess).toBe(1);
    expect(s.needsAction).toBe(true);
    expect(s.allOk).toBe(false);
  });
  it("許容未設定は完了を妨げない", () => {
    const s = summarize({ ...multi, receive: "complete", meters: [{ ...base, stage: 4, status: "ok", tolerance: null }] });
    expect(s.needsAction).toBe(false);
    expect(s.allOk).toBe(true);
  });
  it("失敗を記録から除外しルート外を分ける", () => {
    const s = summarize(multi);
    expect(s.routeRecorded).toBe(4);
    expect(s.offRouteRecorded).toBe(1);
    for (const i of inspections) {
      const c = summarize(i);
      expect(c.recorded).toBeLessThanOrEqual(c.readSuccess);
      expect(c.readSuccess).toBeLessThanOrEqual(c.arrived);
      expect(c.arrived).toBeLessThanOrEqual(c.captured);
    }
    const failed = summarize(ins("I-20261111-PM"));
    expect(failed.recorded).toBe(ins("I-20261111-PM").meters.filter(m => m.stage >= 4 && m.value !== null && judge(m).kind !== "fail").length);
  });
});
