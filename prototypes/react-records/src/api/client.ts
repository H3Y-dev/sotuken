import { data } from "../mock/data";
import type { Filters, Reading } from "./types";
import {
  filterReadings,
  latestPerDevice,
  toCsv,
  toJsonl,
} from "../lib/records";
// manager.storage に対応する仮の取得処理
export async function fetchHistory(): Promise<Reading[]> {
  await new Promise((r) => setTimeout(r, 120));
  return data.map((r) => ({ ...r }));
}
// manager.export.filter_readings に対応
export const filterHistory = (rows: Reading[], filters: Filters) =>
  filterReadings(rows, filters);
// manager.export.latest_per_device と group_by_device に対応
export const fetchLatest = (rows: Reading[]) => latestPerDevice(rows);
// manager.export.export_to_csv に対応
export const exportCsv = (rows: Reading[]) => toCsv(rows);
// 履歴を JSONL 形式に変換
export const exportJsonl = (rows: Reading[]) => toJsonl(rows);
