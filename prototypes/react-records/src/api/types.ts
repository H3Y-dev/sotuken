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
