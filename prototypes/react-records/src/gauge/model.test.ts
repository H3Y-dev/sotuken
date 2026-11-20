import { describe, it, expect } from "vitest";
import type { InspectionMeter, InspectionProgress } from "../api/types";
import { toInspection, toMeter } from "./model";

const baseMeter: InspectionMeter = {
  key: "device:A-101",
  seq: 1,
  off_route: false,
  device_id: "A-101",
  name: "ボイラー1 蒸気圧力",
  unit: "MPa",
  scale: [0, 1.6],
  tolerance: [0.6, 1.0],
  stage: 4,
  value: 0.82,
  read_status: "ok",
  sources: ["phone_qr"],
  photos: 1,
  image_id: null, overlay_image_id: null,
  captured_at: "2026-11-12T13:07:00+09:00",
};

const baseProgress: InspectionProgress = {
  id: "I-1",
  name: "第1点検",
  route_id: "R-1",
  route_name: "第1ルート",
  operator: "佐藤",
  place: "第1工場",
  started_at: "2026-11-12T13:05:00+09:00",
  completed_at: "2026-11-12T13:38:00+09:00",
  status: {
    state: "完了",
    matched: 1,
    missing_photos: [],
  },
  devices: [baseMeter],
};

describe("toMeter", () => {
  it("旧応答で画像キーがない場合はnullにする", () => {
    const { image_id, overlay_image_id, ...old } = baseMeter;
    void image_id; void overlay_image_id;
    expect(toMeter(old as unknown as InspectionMeter)).toMatchObject({ imageId: null, overlayImageId: null });
  });
  it("実APIの機器行を画面用モデルへ変換する", () => {
    expect(toMeter(baseMeter)).toEqual({
      key: "device:A-101",
      seq: 1,
      offRoute: false,
      id: "A-101",
      name: "ボイラー1 蒸気圧力",
      unit: "MPa",
      scale: [0, 1.6],
      tolerance: [0.6, 1.0],
      stage: 4,
      value: 0.82,
      status: "ok",
      sources: ["phone_qr"],
      photos: 1,
      imageId: null, overlayImageId: null,
      capturedAt: "2026-11-12T13:07:00+09:00",
    });
  });

  it("seq・device_id・空単位・不正な目盛り/許容範囲を正規化する", () => {
    const converted = toMeter({
      ...baseMeter,
      key: "photo:hash:1",
      seq: null,
      off_route: true,
      device_id: null,
      name: "名前なし",
      unit: "",
      scale: [10, 10],
      tolerance: [5, 2],
      sources: ["phone_qr", "pc_qr", "phone_qr"],
    });
    expect(converted.seq).toBeUndefined();
    expect(converted.offRoute).toBe(true);
    expect(converted.id).toBe("");
    expect(converted.unit).toBeNull();
    expect(converted.scale).toBeNull();
    expect(converted.tolerance).toBeNull();
    expect(converted.sources).toEqual(["phone_qr", "pc_qr"]);
  });

  it("1点許容範囲（最小=最大）は有効として保持する", () => {
    const converted = toMeter({ ...baseMeter, tolerance: [1.0, 1.0] });
    expect(converted.tolerance).toEqual([1.0, 1.0]);
  });

  it("stage<4はvalue/statusをnullにし、stage=4の失敗・矛盾行はfailed扱いでvalueをnullにする", () => {
    const waiting = toMeter({ ...baseMeter, stage: 2, value: 1.2, read_status: "ok" });
    expect(waiting.value).toBeNull();
    expect(waiting.status).toBeNull();

    const failed = toMeter({ ...baseMeter, stage: 4, value: 1.2, read_status: "failed" });
    expect(failed.value).toBeNull();
    expect(failed.status).toBe("failed");

    const missingVal = toMeter({ ...baseMeter, stage: 4, value: null, read_status: "ok" });
    expect(missingVal.value).toBeNull();
    expect(missingVal.status).toBe("failed");

    const missingStatus = toMeter({ ...baseMeter, stage: 4, value: 0.8, read_status: null });
    expect(missingStatus.value).toBeNull();
    expect(missingStatus.status).toBe("failed");
  });
});

describe("toInspection", () => {
  it("受信状態・欠損項目・削除済みルートを変換する", () => {
    const short = toInspection({
      ...baseProgress,
      route_id: "R-DEL",
      route_name: null,
      operator: null,
      place: null,
      started_at: null,
      completed_at: null,
      status: { state: "不足あり", matched: 0, missing_photos: ["a.jpg", "b.jpg"] },
      devices: [],
    });
    expect(short.routeId).toBe("R-DEL");
    expect(short.routeName).toBeNull();
    expect(short.operator).toBe("—");
    expect(short.place).toBe("—");
    expect(short.startedAt).toBeNull();
    expect(short.completedAt).toBeNull();
    expect(short.receive).toBe("short");
    expect(short.missingPhotos).toBe(2);
    expect(short.meters).toEqual([]);

    expect(
      toInspection({ ...baseProgress, status: { state: "受信中", matched: 1, missing_photos: [] } }).receive,
    ).toBe("receiving");
  });
});
