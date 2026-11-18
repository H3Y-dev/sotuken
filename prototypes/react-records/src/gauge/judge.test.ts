import { describe, it, expect } from "vitest";
import type { Inspection, MeterResult } from "./model";
import { formatValue, judge, summarize, validRange, validTolerance } from "./judge";

const t = (d: string, hm: string) => `2026-11-${d}T${hm}:00+09:00`;

const inspections: Inspection[] = [
  {
    id: "I-20261112-PM",
    name: "第1工場 午後の巡回",
    routeId: "R-A",
    routeName: "第1工場 ボイラー系",
    operator: "佐藤",
    place: "第1工場",
    startedAt: t("12", "13:05"),
    completedAt: t("12", "13:38"),
    receive: "receiving",
    missingPhotos: 0,
    meters: [
      { key: "device:A-101", seq: 1, id: "A-101", name: "ボイラー1 蒸気圧力", unit: "MPa", scale: [0, 1.6], tolerance: [0.6, 1.0], stage: 4, value: 0.82, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:07") },
      { key: "device:A-105", seq: 2, id: "A-105", name: "排ガス 温度", unit: "°C", scale: [0, 400], tolerance: [150, 260], stage: 2, value: null, status: "failed", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:30") },
      { key: "device:A-106", seq: 3, id: "A-106", name: "復水 戻り温度", unit: "°C", scale: [0, 120], tolerance: [50, 90], stage: 1, value: null, status: null, sources: ["manual"], photos: 1, capturedAt: t("12", "13:36") },
    ],
  },
  {
    id: "I-MULTI-20261112",
    name: "第2工場 朝の巡回",
    routeId: "R-MULTI",
    routeName: "第2工場 冷却・空気系",
    operator: "山田",
    place: "第2工場",
    startedAt: t("12", "09:00"),
    completedAt: t("12", "09:42"),
    receive: "complete",
    missingPhotos: 0,
    meters: [
      { key: "device:SYN-001", seq: 1, id: "SYN-001", name: "ボイラー給水 圧力", unit: "kPa", scale: [0, 25], tolerance: [8, 14], stage: 4, value: 10.78, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "09:03") },
      { key: "device:SYN-003", seq: 2, id: "SYN-003", name: "冷却水 入口圧力", unit: "kPa", scale: [0, 40], tolerance: [15, 28], stage: 4, value: 21.62, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "09:11") },
      { key: "device:SYN-002", seq: 3, id: "SYN-002", name: "冷却水 出口圧力", unit: "kPa", scale: [0, 60], tolerance: [20, 35], stage: 4, value: 36.75, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "09:19") },
      { key: "device:SYN-004", seq: 4, id: "SYN-004", name: "圧縮空気タンク 圧力", unit: "MPa", scale: [0, 16], tolerance: [4, 8], stage: 4, value: 5.71, status: "low_confidence", sources: ["manual"], photos: 1, capturedAt: t("12", "09:27") },
      { key: "device:SYN-006", seq: 5, id: "SYN-006", name: "冷却塔ポンプ 吐出圧力", unit: "MPa", scale: [0, 1.0], tolerance: [0.3, 0.6], stage: 0, value: null, status: null, sources: [], photos: 0, capturedAt: null },
      { key: "device:SYN-005", offRoute: true, id: "SYN-005", name: "蒸気ヘッダー 圧力", unit: "MPa", scale: [0, 16], tolerance: [5, 10], stage: 4, value: 7.9, status: "ok", sources: ["phone_qr", "pc_qr"], photos: 2, capturedAt: t("12", "09:36") },
    ],
  },
  {
    id: "I-20261111-PM",
    name: "第2工場 夕方の巡回",
    routeId: "R-MULTI",
    routeName: "第2工場 冷却・空気系",
    operator: "山田",
    place: "第2工場",
    startedAt: t("11", "16:30"),
    completedAt: t("11", "17:05"),
    receive: "short",
    missingPhotos: 1,
    meters: [
      { key: "device:SYN-001", seq: 1, id: "SYN-001", name: "ボイラー給水 圧力", unit: "kPa", scale: [0, 25], tolerance: [8, 14], stage: 4, value: 11.2, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "16:33") },
      { key: "device:SYN-003", seq: 2, id: "SYN-003", name: "冷却水 入口圧力", unit: "kPa", scale: [0, 40], tolerance: [15, 28], stage: 4, value: null, status: "failed", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "16:40") },
      { key: "device:SYN-004", seq: 3, id: "SYN-004", name: "圧縮空気タンク 圧力", unit: "MPa", scale: [0, 16], tolerance: [4, 8], stage: 1, value: null, status: null, sources: ["manual"], photos: 1, capturedAt: t("11", "16:55") },
    ],
  },
  {
    id: "I-20261111-AM",
    name: "第2工場 朝の巡回",
    routeId: "R-MULTI",
    routeName: "第2工場 冷却・空気系",
    operator: "鈴木",
    place: "第2工場",
    startedAt: t("11", "09:02"),
    completedAt: t("11", "09:38"),
    receive: "complete",
    missingPhotos: 0,
    meters: [
      { key: "device:SYN-001", seq: 1, id: "SYN-001", name: "ボイラー給水 圧力", unit: "kPa", scale: [0, 25], tolerance: [8, 14], stage: 4, value: 10.4, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "09:05") },
      { key: "device:SYN-002", seq: 2, id: "SYN-002", name: "冷却水 出口圧力", unit: "kPa", scale: [0, 60], tolerance: [20, 35], stage: 4, value: 28.9, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "09:19") },
    ],
  },
  {
    id: "I-20261110-01",
    name: "臨時の点検（ルートなし）",
    routeId: null,
    routeName: null,
    operator: "高橋",
    place: "第1工場",
    startedAt: t("10", "15:10"),
    completedAt: t("10", "15:24"),
    receive: "complete",
    missingPhotos: 0,
    meters: [
      { key: "device:A-101", id: "A-101", name: "ボイラー1 蒸気圧力", unit: "MPa", scale: [0, 1.6], tolerance: null, stage: 4, value: 0.88, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("10", "15:12") },
      { key: "photo:hash:abc", id: "", name: "", unit: null, scale: null, tolerance: null, stage: 4, value: 47.0, status: "ok", sources: [], photos: 1, capturedAt: t("10", "15:17") },
      { key: "device:A-110", id: "A-110", name: "攪拌機 回転数カウンタ", unit: null, scale: [0, 2000], tolerance: null, stage: 4, value: 1240, status: "ok", sources: ["manual"], photos: 1, capturedAt: t("10", "15:23") },
    ],
  },
];

const ins = (id: string) => inspections.find((i) => i.id === id)!;
const multi = ins("I-MULTI-20261112");
const meter = (i: string, id: string) => ins(i).meters.find((m) => m.id === id)!;
const base: MeterResult = multi.meters[0];

describe("計器盤の判定", () => {
  it("通し試験の形: 撮り忘れ・ルート外・要確認を区別する", () => {
    expect(judge(meter("I-MULTI-20261112", "SYN-006")).kind).toBe("missing");
    expect(judge(meter("I-MULTI-20261112", "SYN-004")).kind).toBe("warn");
    expect(judge(meter("I-MULTI-20261112", "SYN-001")).kind).toBe("ok");
    const s = summarize(multi);
    expect(s.routeTotal).toBe(5);
    expect(s.routeCaptured).toBe(4);
    expect(s.offRoute.map((m) => m.id)).toEqual(["SYN-005"]);
    expect(s.photos).toBe(6);
    expect(s.needsAction).toBe(true);
    expect(s.allOk).toBe(false);
  });

  it("許容範囲の判定: 未設定・下端・上端・1点（最小=最大）・範囲外", () => {
    // 未設定
    expect(judge({ ...base, value: 99, scale: null, tolerance: null })).toEqual({ kind: "ok", reasons: [], outOfTolerance: false });
    // 下端・上端（両端は範囲内）
    expect(judge({ ...base, value: 8, tolerance: [8, 14] })).toEqual({ kind: "ok", reasons: [], outOfTolerance: false });
    expect(judge({ ...base, value: 14, tolerance: [8, 14] })).toEqual({ kind: "ok", reasons: [], outOfTolerance: false });
    // 1点（最小=最大）
    expect(validTolerance([10, 10])).toBe(true);
    expect(judge({ ...base, value: 10, tolerance: [10, 10] })).toEqual({ kind: "ok", reasons: [], outOfTolerance: false });
    expect(judge({ ...base, value: 10.1, tolerance: [10, 10] })).toEqual({ kind: "ok", reasons: [], outOfTolerance: true });
    // 範囲外（下・上）
    expect(judge({ ...base, value: 7.9, tolerance: [8, 14] })).toEqual({ kind: "ok", reasons: [], outOfTolerance: true });
    expect(judge({ ...base, value: 14.1, tolerance: [8, 14] })).toEqual({ kind: "ok", reasons: [], outOfTolerance: true });

    const s = summarize(multi);
    expect(s.outOfTolerance.map((m) => m.id)).toEqual(["SYN-002"]);
    expect(s.warn.map((m) => m.id)).toEqual(["SYN-004"]);
    expect(s.readSuccess).toBe(5);
  });

  it("名前なしと名前だけの記録（機器IDなし）を区別し、許容範囲外の注意は付けない", () => {
    const nameless = judge({ ...base, id: "", name: "", value: 99 });
    expect(nameless.kind).toBe("warn");
    expect(nameless.reasons).toContain("名前なし");
    expect(nameless.outOfTolerance).toBe(false);

    const nameOnly = judge({ ...base, id: "", name: "ボイラー給水 圧力", value: 99 });
    expect(nameOnly.kind).toBe("warn");
    expect(nameOnly.reasons).toContain("機器IDなし");
    expect(nameOnly.reasons).not.toContain("名前なし");
    expect(nameOnly.outOfTolerance).toBe(false);
  });

  it("失敗は段階より先に見る: stage<4 でも failed なら失敗", () => {
    expect(judge({ ...base, stage: 2, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge({ ...base, stage: 1, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge({ ...base, stage: 4, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge(meter("I-20261112-PM", "A-105")).kind).toBe("fail");
  });

  it("途中: 未着・読み取り待ちは待ち", () => {
    expect(judge({ ...base, stage: 1, value: null, status: null })).toEqual({ kind: "wait", reasons: ["PCに未着"], outOfTolerance: false });
    expect(judge({ ...base, stage: 2, value: null, status: null })).toEqual({ kind: "wait", reasons: ["読み取り待ち"], outOfTolerance: false });
  });

  it("撮り忘れは理由「撮り忘れ」", () => {
    expect(judge({ ...base, stage: 0, value: null, status: null })).toEqual({ kind: "missing", reasons: ["撮り忘れ"], outOfTolerance: false });
  });

  it("目盛り範囲の外は要確認。目盛りが未設定・不正なら見ない", () => {
    expect(judge({ ...base, value: 30 }).reasons).toContain("目盛り範囲の外");
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
    expect(noUnit.unit).toBeNull();
    expect(judge(noUnit).kind).toBe("ok");
    const nameless = meter("I-20261110-01", "");
    expect(nameless.scale).toBeNull();
    expect(nameless.unit).toBeNull();
    expect(judge(nameless).kind).toBe("warn");
    expect(judge({ ...base, value: 20, tolerance: [14, 8] }).outOfTolerance).toBe(false);
  });

  it("全部正常で受信も完了なら対処不要", () => {
    const am = ins("I-20261111-AM");
    const s = summarize(am);
    expect(s.needsAction).toBe(false);
    expect(s.allOk).toBe(true);
    expect(s.outOfTolerance).toEqual([]);
  });

  it("空の点検・受信不足・受信中は完了にしない", () => {
    const empty = summarize({ ...ins("I-20261111-AM"), receive: "complete", meters: [] });
    expect(empty.allOk).toBe(false);
    expect(empty.needsAction).toBe(false);

    const short = summarize({ ...ins("I-20261111-AM"), receive: "short", missingPhotos: 1 });
    expect(short.allOk).toBe(false);
    expect(short.needsAction).toBe(true);

    const receiving = summarize({ ...ins("I-20261111-AM"), receive: "receiving" });
    expect(receiving.allOk).toBe(false);
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
    expect(failed.recorded).toBe(
      ins("I-20261111-PM").meters.filter((m) => m.stage >= 4 && m.value !== null && judge(m).kind !== "fail").length,
    );
  });
});
