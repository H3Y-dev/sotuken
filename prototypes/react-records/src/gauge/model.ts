import type {
  InspectionMeter,
  InspectionProgress,
  InspectionReadStatus,
  InspectionSource,
  InspectionState,
} from "../api/types";
import { validRange, validTolerance } from "./judge";

/** 0=計画のみ 1=撮った申告あり／未着 2=PCに到着（読み取り待ち） 4=DBに記録 */
export type Stage = 0 | 1 | 2 | 4;
export type Source = InspectionSource;
export type ReadStatus = InspectionReadStatus;
export type Receive = "receiving" | "short" | "complete";

export interface MeterResult {
  key: string;
  /** ルート上の順番。ルート外・ルートなし・削除済みルートでは付けない */
  seq?: number;
  offRoute?: boolean;
  /** 機器ID。空は機器IDなしの記録 */
  id: string;
  name: string;
  /** devices.unit。未設定・空文字は null */
  unit: string | null;
  /** 目盛りの範囲 [min, max]。未設定・不正は null */
  scale: [number, number] | null;
  /** 許容範囲 [min, max]。未設定・不正は null */
  tolerance: [number, number] | null;
  stage: Stage;
  value: number | null;
  status: ReadStatus | null;
  sources: Source[];
  photos: number;
  capturedAt: string | null;
  imageId: string | null;
  overlayImageId: string | null;
}

export interface Inspection {
  summary?: import("@/api/types").InspectionSummary;
  id: string;
  name: string;
  routeId: string | null;
  routeName: string | null;
  operator: string;
  place: string;
  startedAt: string | null;
  completedAt: string | null;
  receive: Receive;
  /** manifestに載っているのにPCへ届いていない写真の枚数 */
  missingPhotos: number;
  meters: MeterResult[];
}

const RECEIVE_MAP: Record<InspectionState, Receive> = {
  受信中: "receiving",
  不足あり: "short",
  完了: "complete",
};

function normalizeValueAndStatus(
  stage: Stage,
  rawValue: number | null,
  rawStatus: InspectionReadStatus | null,
): { value: number | null; status: ReadStatus | null } {
  if (stage < 4) return { value: null, status: null };
  if (rawStatus === "failed") return { value: null, status: "failed" };
  if (rawValue === null || !Number.isFinite(rawValue) || rawStatus === null) {
    return { value: null, status: "failed" };
  }
  return { value: rawValue, status: rawStatus };
}

/** 実APIの InspectionMeter を画面用の MeterResult へ変換する */
export function toMeter(row: InspectionMeter): MeterResult {
  const { value, status } = normalizeValueAndStatus(row.stage, row.value, row.read_status);
  const sources = Array.from(
    new Set(row.sources.filter((s): s is Source => s === "phone_qr" || s === "manual" || s === "pc_qr")),
  );
  return {
    key: row.key,
    seq: row.seq ?? undefined,
    offRoute: row.off_route,
    id: row.device_id ?? "",
    name: row.name,
    unit: row.unit || null,
    scale: validRange(row.scale) ? [row.scale[0], row.scale[1]] : null,
    tolerance: validTolerance(row.tolerance) ? [row.tolerance[0], row.tolerance[1]] : null,
    stage: row.stage,
    value,
    status,
    sources,
    photos: row.photos,
    capturedAt: row.captured_at,
    imageId: row.image_id ?? null,
    overlayImageId: row.overlay_image_id ?? null,
  };
}

/** 実APIの InspectionProgress を画面用の Inspection へ変換する */
export function toInspection(progress: InspectionProgress): Inspection {
  return {
    id: progress.id,
    name: progress.name,
    routeId: progress.route_id,
    routeName: progress.route_name,
    operator: progress.operator ?? "—",
    place: progress.place ?? "—",
    startedAt: progress.started_at,
    completedAt: progress.completed_at,
    receive: RECEIVE_MAP[progress.status.state],
    missingPhotos: progress.status.missing_photos.length,
    meters: progress.devices.map(toMeter),
  };
}
