// 点検のダミーデータ。2026-11-12 の複数機器QR点検の通し試験
// （ルート5台・撮り忘れ1台・ルート外1台・出所4種）を手本にした架空の値。
// 単位・目盛りの範囲は、DBの devices 表に既にある（unit / min_value / max_value）。
// DBに無いのは許容範囲だけで、今後 devices 表に任意の列として足す予定（QRには入れない）。
// どれも任意項目なので、未設定（null）の機器も混ぜて、画面が壊れないことを確かめられるようにしている。

/** 0=未撮影 1=撮影済み（PC未着） 2=PCに到着（読み取り待ち） 3=読み取り済み（記録待ち） 4=DBに記録 */
export type Stage = 0 | 1 | 2 | 3 | 4;
export type Source = "phone_qr" | "list" | "manual" | "pc_qr";
export type ReadStatus = "ok" | "low_confidence" | "failed";
export type Receive = "receiving" | "short" | "complete";

export interface MeterResult {
  /** ルート上の順番。ルート外・ルートなしの点検では付けない */
  seq?: number;
  offRoute?: boolean;
  /** 機器ID。空はQRも一覧も手入力もなかった写真（名前なし） */
  id: string;
  name: string;
  /** devices.unit。未設定は null か空文字 */
  unit: string | null;
  /** 目盛りの範囲 [devices.min_value, devices.max_value]。未設定は null */
  scale: [number, number] | null;
  /** 許容範囲。今のDBに無い（任意の列として足す予定）。未設定は null */
  tolerance: [number, number] | null;
  stage: Stage;
  value: number | null;
  status: ReadStatus | null;
  sources: Source[];
  photos: number;
  capturedAt: string | null;
}

export interface Inspection {
  id: string;
  name: string;
  routeId: string | null;
  routeName: string | null;
  operator: string;
  place: string;
  startedAt: string;
  completedAt: string | null;
  receive: Receive;
  /** manifestに載っているのにPCへ届いていない写真の枚数 */
  missingPhotos: number;
  meters: MeterResult[];
}

const t = (d: string, hm: string) => `2026-11-${d}T${hm}:00+09:00`;

export const inspections: Inspection[] = [
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
      { seq: 1, id: "A-101", name: "ボイラー1 蒸気圧力", unit: "MPa", scale: [0, 1.6], tolerance: [0.6, 1.0], stage: 4, value: 0.82, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:07") },
      { seq: 2, id: "A-102", name: "ボイラー2 蒸気圧力", unit: "MPa", scale: [0, 1.6], tolerance: [0.6, 1.0], stage: 4, value: 0.79, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:12") },
      { seq: 3, id: "A-103", name: "給水タンク 水位", unit: "%", scale: [0, 100], tolerance: [40, 85], stage: 4, value: 62.5, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:18") },
      { seq: 4, id: "A-104", name: "燃料ガス 供給圧力", unit: "kPa", scale: [0, 10], tolerance: [2.0, 4.5], stage: 3, value: 3.12, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:24") },
      { seq: 5, id: "A-105", name: "排ガス 温度", unit: "°C", scale: [0, 400], tolerance: [150, 260], stage: 2, value: null, status: "failed", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "13:30") },
      { seq: 6, id: "A-106", name: "復水 戻り温度", unit: "°C", scale: [0, 120], tolerance: [50, 90], stage: 1, value: null, status: null, sources: ["manual"], photos: 1, capturedAt: t("12", "13:36") },
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
      { seq: 1, id: "SYN-001", name: "ボイラー給水 圧力", unit: "kPa", scale: [0, 25], tolerance: [8, 14], stage: 4, value: 10.78, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "09:03") },
      { seq: 2, id: "SYN-003", name: "冷却水 入口圧力", unit: "kPa", scale: [0, 40], tolerance: [15, 28], stage: 4, value: 21.62, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "09:11") },
      { seq: 3, id: "SYN-002", name: "冷却水 出口圧力", unit: "kPa", scale: [0, 60], tolerance: [20, 35], stage: 4, value: 36.75, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("12", "09:19") },
      { seq: 4, id: "SYN-004", name: "圧縮空気タンク 圧力", unit: "MPa", scale: [0, 16], tolerance: [4, 8], stage: 4, value: 5.71, status: "low_confidence", sources: ["list"], photos: 1, capturedAt: t("12", "09:27") },
      { seq: 5, id: "SYN-006", name: "冷却塔ポンプ 吐出圧力", unit: "MPa", scale: [0, 1.0], tolerance: [0.3, 0.6], stage: 0, value: null, status: null, sources: [], photos: 0, capturedAt: null },
      { offRoute: true, id: "SYN-005", name: "蒸気ヘッダー 圧力", unit: "MPa", scale: [0, 16], tolerance: [5, 10], stage: 4, value: 7.9, status: "ok", sources: ["phone_qr", "pc_qr"], photos: 2, capturedAt: t("12", "09:36") },
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
      { seq: 1, id: "SYN-001", name: "ボイラー給水 圧力", unit: "kPa", scale: [0, 25], tolerance: [8, 14], stage: 4, value: 11.2, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "16:33") },
      { seq: 2, id: "SYN-003", name: "冷却水 入口圧力", unit: "kPa", scale: [0, 40], tolerance: [15, 28], stage: 4, value: null, status: "failed", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "16:40") },
      { seq: 3, id: "SYN-002", name: "冷却水 出口圧力", unit: "kPa", scale: [0, 60], tolerance: [20, 35], stage: 4, value: 30.4, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "16:47") },
      { seq: 4, id: "SYN-004", name: "圧縮空気タンク 圧力", unit: "MPa", scale: [0, 16], tolerance: [4, 8], stage: 1, value: null, status: null, sources: ["list"], photos: 1, capturedAt: t("11", "16:55") },
      { seq: 5, id: "SYN-006", name: "冷却塔ポンプ 吐出圧力", unit: "MPa", scale: [0, 1.0], tolerance: [0.3, 0.6], stage: 4, value: 0.44, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "17:01") },
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
      { seq: 1, id: "SYN-001", name: "ボイラー給水 圧力", unit: "kPa", scale: [0, 25], tolerance: [8, 14], stage: 4, value: 10.4, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "09:05") },
      { seq: 2, id: "SYN-003", name: "冷却水 入口圧力", unit: "kPa", scale: [0, 40], tolerance: [15, 28], stage: 4, value: 22.1, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "09:12") },
      { seq: 3, id: "SYN-002", name: "冷却水 出口圧力", unit: "kPa", scale: [0, 60], tolerance: [20, 35], stage: 4, value: 28.9, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "09:19") },
      { seq: 4, id: "SYN-004", name: "圧縮空気タンク 圧力", unit: "MPa", scale: [0, 16], tolerance: [4, 8], stage: 4, value: 6.3, status: "ok", sources: ["list"], photos: 1, capturedAt: t("11", "09:27") },
      { seq: 5, id: "SYN-006", name: "冷却塔ポンプ 吐出圧力", unit: "MPa", scale: [0, 1.0], tolerance: [0.3, 0.6], stage: 4, value: 0.47, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("11", "09:34") },
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
      { id: "A-101", name: "ボイラー1 蒸気圧力", unit: "MPa", scale: [0, 1.6], tolerance: null, stage: 4, value: 0.88, status: "ok", sources: ["phone_qr"], photos: 1, capturedAt: t("10", "15:12") },
      { id: "", name: "", unit: null, scale: null, tolerance: null, stage: 4, value: 47.0, status: "ok", sources: [], photos: 1, capturedAt: t("10", "15:17") },
      { id: "A-103", name: "給水タンク 水位", unit: "%", scale: [0, 100], tolerance: [40, 85], stage: 4, value: 71.0, status: "ok", sources: ["manual"], photos: 1, capturedAt: t("10", "15:21") },
      { id: "A-110", name: "攪拌機 回転数カウンタ", unit: "", scale: [0, 2000], tolerance: null, stage: 4, value: 1240, status: "ok", sources: ["list"], photos: 1, capturedAt: t("10", "15:23") },
    ],
  },
];
