import type { Inspection, MeterResult, Source } from "../mock/inspections";

/** 画面での状態。ok=正常 warn=要確認 fail=失敗 wait=途中 missing=未撮影 */
export type Kind = "ok" | "warn" | "fail" | "wait" | "missing";

export const STAGES = ["撮影", "到着", "読み取り", "記録"] as const;

const WAIT_LABEL = ["", "PCに未着", "読み取り待ち", "記録待ち"];

/** 目盛りの範囲が使えるか（未設定・数でない・最小>=最大は使わない） */
export const validRange = (r: [number, number] | null): r is [number, number] =>
  r !== null && Number.isFinite(r[0]) && Number.isFinite(r[1]) && r[0] < r[1];

/** 許容範囲が使えるか（未設定・数でない・下限>上限は使わない） */
export const validTolerance = (r: [number, number] | null): r is [number, number] =>
  r !== null && Number.isFinite(r[0]) && Number.isFinite(r[1]) && r[0] <= r[1];

/**
 * 成否は「値を読み取れたか」で決める。許容範囲の外は outOfTolerance として別に返し、
 * kind は変えない（読み取りは成功なので ok のまま。画面では補助の注意として出す）。
 */
export function judge(m: MeterResult): { kind: Kind; reasons: string[]; outOfTolerance: boolean } {
  if (m.stage === 0) return { kind: "missing", reasons: ["撮り忘れ"], outOfTolerance: false };
  if (m.status === "failed" || (m.stage >= 3 && m.value === null))
    return { kind: "fail", reasons: ["値を読み取れなかった"], outOfTolerance: false };
  if (m.stage < 4 || m.value === null)
    return { kind: "wait", reasons: [WAIT_LABEL[m.stage]], outOfTolerance: false };
  const v = m.value;
  const reasons: string[] = [];
  if (!m.id) reasons.push("名前なし");
  if (m.status === "low_confidence") reasons.push("読み取りが不確か");
  if (validRange(m.scale) && (v < m.scale[0] || v > m.scale[1])) reasons.push("目盛り範囲の外");
  const outOfTolerance = Boolean(m.id && validTolerance(m.tolerance) && (v < m.tolerance[0] || v > m.tolerance[1]));
  return { kind: reasons.length ? "warn" : "ok", reasons, outOfTolerance };
}

export const SOURCE_LABEL: Record<Source, string> = {
  phone_qr: "スマホのQR",
  list: "一覧から",
  manual: "手入力",
  pc_qr: "PCの画像QR",
};

export function summarize(ins: Inspection) {
  const route = ins.meters.filter((m) => m.seq !== undefined);
  const judged = ins.meters.map((m) => ({ m, ...judge(m) }));
  const byKind = (k: Kind) => judged.filter((j) => j.kind === k).map((j) => j.m);
  const missing = byKind("missing");
  const offRoute = ins.meters.filter((m) => m.offRoute);
  const warn = byKind("warn");
  const fail = byKind("fail");
  const wait = byKind("wait");
  const reached = (s: number) => ins.meters.filter((m) => m.stage >= s).length;
  return {
    routeTotal: route.length,
    routeCaptured: route.filter((m) => m.stage > 0).length,
    photos: ins.meters.reduce((n, m) => n + m.photos, 0),
    captured: reached(1),
    arrived: reached(2),
    /** 値を読み取れた台数（記録待ちも含む。失敗は含まない） */
    readSuccess: judged.filter((j) => j.m.value !== null && j.kind !== "fail" && j.kind !== "missing").length,
    recorded: reached(4),
    missing,
    offRoute,
    warn,
    fail,
    wait,
    /** 読み取りは成功したが許容範囲の外（補助の注意。対処が必要には数えない） */
    outOfTolerance: judged.filter((j) => j.outOfTolerance).map((j) => j.m),
    /** 全台が正常（許容範囲の外も読み取り成功なので正常に含む） */
    allOk: judged.every((j) => j.kind === "ok"),
    /** 人が見て手を打つべきものがあるか。途中（wait）は待てば進むので含めない */
    needsAction:
      missing.length + offRoute.length + warn.length + fail.length > 0 ||
      ins.receive === "short",
  };
}

/** 目盛りが細かい計器ほど桁を多く出す。桁数をそろえるため末尾の0も残す。目盛り未設定は1桁 */
export const formatValue = (v: number, scaleMax?: number | null) =>
  v.toFixed(scaleMax != null && Number.isFinite(scaleMax) && scaleMax <= 30 ? 2 : 1);

export const time = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" })
    : "—";

export const day = (iso: string) =>
  new Date(iso).toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", weekday: "short", timeZone: "Asia/Tokyo" });
