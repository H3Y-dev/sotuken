import type { Inspection, MeterResult, Source } from "../mock/inspections";

/** 画面での状態。ok=正常 warn=要確認 fail=失敗 wait=途中 missing=未撮影 */
export type Kind = "ok" | "warn" | "fail" | "wait" | "missing";

export const STAGES = ["撮影", "到着", "読み取り", "記録"] as const;

const WAIT_LABEL = ["", "PCに未着", "読み取り待ち", "記録待ち"];

export function judge(m: MeterResult): { kind: Kind; reasons: string[] } {
  if (m.stage === 0) return { kind: "missing", reasons: ["撮り忘れ"] };
  if (m.stage < 4) return { kind: "wait", reasons: [WAIT_LABEL[m.stage]] };
  if (m.status === "failed" || m.value === null)
    return { kind: "fail", reasons: ["値を読み取れなかった"] };
  const reasons: string[] = [];
  if (!m.id) reasons.push("名前なし");
  if (m.status === "low_confidence") reasons.push("読み取りが不確か");
  const [lo, hi] = m.tolerance;
  if (m.id && (m.value < lo || m.value > hi)) reasons.push("許容範囲の外");
  return reasons.length ? { kind: "warn", reasons } : { kind: "ok", reasons: [] };
}

export const SOURCE_LABEL: Record<Source, string> = {
  phone_qr: "スマホのQR",
  list: "一覧から",
  manual: "手入力",
  pc_qr: "PCの画像QR",
};

export function summarize(ins: Inspection) {
  const route = ins.meters.filter((m) => m.seq !== undefined);
  const byKind = (k: Kind) => ins.meters.filter((m) => judge(m).kind === k);
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
    read: reached(3),
    recorded: reached(4),
    missing,
    offRoute,
    warn,
    fail,
    wait,
    /** 人が見て手を打つべきものがあるか。途中（wait）は待てば進むので含めない */
    needsAction:
      missing.length + offRoute.length + warn.length + fail.length > 0 ||
      ins.receive === "short",
  };
}

/** 目盛りが細かい計器ほど桁を多く出す。桁数をそろえるため末尾の0も残す */
export const formatValue = (v: number, scaleMax: number) =>
  v.toFixed(scaleMax <= 30 ? 2 : 1);

export const time = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" })
    : "—";

export const day = (iso: string) =>
  new Date(iso).toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", weekday: "short", timeZone: "Asia/Tokyo" });
