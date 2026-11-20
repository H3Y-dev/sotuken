export interface Reading {
  id: string;
  reading_id: string | null;
  device_name: string;
  device_id: string | null;
  captured_at: string | null;
  timestamp: string | null;
  received_at: string | null;
  value: number | null;
  unit: string | null;
  status: string | null;
  stage: string;
  confidence: number | null;
  failure_stage: string | null;
  inspection_id: string | null;
  inspection_name: string | null;
  route_id: string | null;
  image_id: string | null;
  overlay_image_id: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Filters {
  /** "all" = すべて, "none" = 点検なし(旧データ), otherwise inspection_id */
  inspection: string;
  /** "all" = すべて, otherwise exact device_name */
  device: string;
  start: string;
  end: string;
}

export interface RuntimeStatus {
  receiver_running: boolean;
  receiver_url: string | null;
  owner_instance_id: string;
  observed_at: string;
}

export interface PairingStatus {
  active: boolean;
  payload: string | null;
  expires_at: number | null;
  remaining_seconds: number;
  owner_instance_id: string;
  observed_at: string;
}

export interface UsbStatus {
  enabled: boolean;
  running: boolean;
  adb_found: boolean;
  devices: string[];
  pulled_total: number;
  last_error: string | null;
  interval: number;
  cycles: number;
  owner_instance_id: string;
  observed_at: string;
}

export type InspectionState = "受信中" | "不足あり" | "完了";
export type InspectionReadStatus = "ok" | "low_confidence" | "failed";
export type InspectionSource = "phone_qr" | "manual" | "pc_qr";

export interface InspectionStatus {
  state: InspectionState;
  matched: number;
  missing_photos: string[];
}

export interface InspectionMeta {
  id: string;
  name: string;
  route_id: string | null;
  route_name: string | null;
  operator: string | null;
  place: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface InspectionMeter {
  key: string;
  seq: number | null;
  off_route: boolean;
  device_id: string | null;
  name: string;
  unit: string | null;
  scale: [number, number] | null;
  tolerance: [number, number] | null;
  stage: 0 | 1 | 2 | 4;
  value: number | null;
  read_status: InspectionReadStatus | null;
  sources: InspectionSource[];
  photos: number;
  captured_at: string | null;
  image_id: string | null;
  overlay_image_id: string | null;
}

export interface InspectionProgress extends InspectionMeta {
  status: InspectionStatus;
  devices: InspectionMeter[];
}

export interface InspectionSummary {
  route_total: number;
  route_captured: number;
  route_recorded: number;
  captured: number;
  recorded: number;
  missing: number;
  off_route: number;
  off_route_recorded: number;
  warn: number;
  fail: number;
  wait: number;
  out_of_tolerance: number;
  all_ok: boolean;
  needs_action: boolean;
}

export interface InspectionListItem extends InspectionMeta {
  count: number;
  status: {
    state: InspectionState;
    matched: number;
  };
  missing_photo_count: number;
  preview: InspectionMeter[];
  summary: InspectionSummary;
}

export interface InspectionListPage {
  items: InspectionListItem[];
  total: number;
  next_cursor: string | null;
  all_total: number;
  action_total: number;
}

export interface DeviceInput {
  device_name: string;
  unit: string | null;
  min_value: number | null;
  max_value: number | null;
  tolerance_min: number | null;
  tolerance_max: number | null;
}

export interface Device extends DeviceInput {
  device_id: string;
  provisional: boolean;
}
