import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { SquareX } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, describeApiError, imageUrl, listDevices, submitManualReading } from "@/api/client";
import type { Device, ManualReadingResult } from "@/api/types";
import type { StatusLabel } from "@/lib/records";
import { StatusBadge } from "./StatusBadge";

const DEVICE_NAME_MAX = 64;

type FormState = {
  deviceName: string;
  thresholdMin: string;
  thresholdMax: string;
};

const INITIAL_FORM: FormState = {
  deviceName: "Gauge_01",
  thresholdMin: "0",
  thresholdMax: "40",
};

type ValidationResult =
  | { ok: true; values: { deviceName: string; thresholdMin: number; thresholdMax: number } }
  | { ok: false; message: string };

function validate(values: FormState): ValidationResult {
  const deviceName = values.deviceName.trim();
  if (!deviceName) {
    return { ok: false, message: "機器名を入力してください。" };
  }
  if ([...deviceName].length > DEVICE_NAME_MAX) {
    return { ok: false, message: `機器名は${DEVICE_NAME_MAX}文字以内で入力してください。` };
  }
  const thresholdMin = Number(values.thresholdMin.trim());
  const thresholdMax = Number(values.thresholdMax.trim());
  if (values.thresholdMin.trim() === "" || !Number.isFinite(thresholdMin)) {
    return { ok: false, message: "下限閾値は有限の数値で入力してください。" };
  }
  if (values.thresholdMax.trim() === "" || !Number.isFinite(thresholdMax)) {
    return { ok: false, message: "上限閾値は有限の数値で入力してください。" };
  }
  if (thresholdMin > thresholdMax) {
    return { ok: false, message: "下限閾値は上限閾値以下にしてください。" };
  }
  return { ok: true, values: { deviceName, thresholdMin, thresholdMax } };
}

function isAuthError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.code === "unauthenticated");
}

function readingStatusLabel(status: string | null | undefined): StatusLabel {
  if (status === "ok") return "正常";
  if (status === "low_confidence") return "要確認";
  return "失敗";
}

export function ManualReadingView({ onAuthExpired }: { onAuthExpired?: () => void }) {
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ManualReadingResult | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedPreset, setSelectedPreset] = useState("");
  const previewUrlRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const clearPreview = () => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setPreviewUrl(null);
  };

  useEffect(() => () => clearPreview(), []);

  useEffect(() => {
    const controller = new AbortController();
    listDevices(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted && Array.isArray(items)) {
          setDevices(items);
        }
      })
      .catch(() => {
        // Ignore errors when device list is unavailable
      });
    return () => controller.abort();
  }, []);

  const onPresetChange = (deviceId: string) => {
    setSelectedPreset(deviceId);
    const found = devices.find((d) => d.device_id === deviceId);
    if (!found) return;
    const nextMin = found.tolerance_min ?? found.min_value;
    const nextMax = found.tolerance_max ?? found.max_value;
    setForm((prev) => ({
      deviceName: found.device_name,
      thresholdMin: nextMin !== null && nextMin !== undefined ? String(nextMin) : prev.thresholdMin,
      thresholdMax: nextMax !== null && nextMax !== undefined ? String(nextMax) : prev.thresholdMax,
    }));
    setError("");
  };

  const onClear = () => {
    clearPreview();
    setFile(null);
    setError("");
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    clearPreview();
    setFile(next);
    setError("");
    setResult(null);
    if (next) {
      const url = URL.createObjectURL(next);
      previewUrlRef.current = url;
      setPreviewUrl(url);
    }
  };

  const updateField = (key: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setError("");
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || submitting) return;

    const checked = validate(form);
    if (!checked.ok) {
      setResult(null);
      setError(checked.message);
      return;
    }

    const formData = new FormData();
    formData.append("device_name", checked.values.deviceName);
    formData.append("threshold_min", String(checked.values.thresholdMin));
    formData.append("threshold_max", String(checked.values.thresholdMax));
    formData.append("image", file);

    setSubmitting(true);
    setError("");
    setResult(null);
    try {
      const data = await submitManualReading(formData);
      setResult(data);
    } catch (err) {
      if (isAuthError(err)) onAuthExpired?.();
      setError(describeApiError(err) || "読み取りに失敗しました。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="flex flex-col gap-4" aria-labelledby="manual-heading">
      <div className="flex flex-col gap-1">
        <h1 id="manual-heading" className="text-[28px] font-bold text-text">
          手動読み取り
        </h1>
        <p className="text-base text-steel">
          手元の画像1枚をその場でテスト読み取りし、検出オーバーレイと判定を確認します。
        </p>
      </div>

      <form onSubmit={(event) => void onSubmit(event)} noValidate className="flex flex-col gap-4">
        <Card className="border-hairline bg-dial">
          <CardHeader className="border-b border-hairline">
            <CardTitle className="text-xl font-bold text-text">読み取り条件</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {devices.length > 0 && (
              <div className="flex flex-col gap-2">
                <label htmlFor="manual-device-preset" className="font-bold text-text">
                  登録機器から入力（任意）
                </label>
                <select
                  id="manual-device-preset"
                  value={selectedPreset}
                  disabled={submitting}
                  onChange={(event) => onPresetChange(event.target.value)}
                  className="h-11 rounded-md border border-hairline bg-white px-3 text-base text-text"
                >
                  <option value="">選択して自動入力…</option>
                  {devices.map((d) => (
                    <option key={d.device_id} value={d.device_id}>
                      {d.device_name}（{d.device_id}）
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <label htmlFor="manual-device-name" className="font-bold text-text">
                  機器名
                </label>
                <Input
                  id="manual-device-name"
                  name="device_name"
                  placeholder="例: Gauge_01"
                  className="h-11 bg-white text-base"
                  value={form.deviceName}
                  maxLength={DEVICE_NAME_MAX}
                  disabled={submitting}
                  onChange={(event) => updateField("deviceName", event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <label htmlFor="manual-threshold-min" className="font-bold text-text">
                  許容下限
                </label>
                <Input
                  id="manual-threshold-min"
                  name="threshold_min"
                  type="number"
                  inputMode="decimal"
                  placeholder="0"
                  className="g-num h-11 bg-white text-base"
                  value={form.thresholdMin}
                  disabled={submitting}
                  onChange={(event) => updateField("thresholdMin", event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <label htmlFor="manual-threshold-max" className="font-bold text-text">
                  許容上限
                </label>
                <Input
                  id="manual-threshold-max"
                  name="threshold_max"
                  type="number"
                  inputMode="decimal"
                  placeholder="40"
                  className="g-num h-11 bg-white text-base"
                  value={form.thresholdMax}
                  disabled={submitting}
                  onChange={(event) => updateField("thresholdMax", event.target.value)}
                />
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label htmlFor="manual-image" className="font-bold text-text">
                  画像を選ぶ
                </label>
                <span className="text-sm text-steel">対応形式: JPEG / PNG</span>
              </div>
              <Input
                ref={fileInputRef}
                id="manual-image"
                type="file"
                accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                disabled={submitting}
                onChange={onFileChange}
              />
            </div>

            {previewUrl && (
              <figure className="flex flex-col gap-2 rounded-md border border-hairline bg-panel p-3">
                <figcaption className="font-bold text-text">読み取る画像</figcaption>
                <img
                  src={previewUrl}
                  alt="読み取る画像"
                  className="max-h-[40vh] w-full rounded-sm border border-hairline bg-white object-contain"
                />
              </figure>
            )}

            {error && (
              <Alert variant="destructive" className="border-fail bg-fail-tint">
                <SquareX aria-hidden className="size-4" />
                <AlertDescription className="font-bold text-current">{error}</AlertDescription>
              </Alert>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" size="field" disabled={!file || submitting}>
                {submitting ? "読み取り中…" : "読み取る"}
              </Button>
              <Button
                type="button"
                size="field"
                variant="outline"
                className="border-hairline"
                disabled={(!file && !result && !error) || submitting}
                onClick={onClear}
              >
                クリア
              </Button>
              {!file && <span className="text-base text-steel">画像を選んでください。</span>}
            </div>
          </CardContent>
        </Card>
      </form>

      {result && (
        <Card className="border-hairline bg-dial" data-testid="manual-result">
          <CardHeader className="border-b border-hairline">
            <CardTitle className="text-xl font-bold text-text">読み取り結果</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex flex-col gap-1">
                <span className="text-base text-steel">判定</span>
                <StatusBadge label={readingStatusLabel(result.reading.status)} />
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-base text-steel">読み取り値</span>
                <span className="g-num text-3xl font-bold text-ink">
                  {result.value !== null ? result.value.toFixed(2) : "—"}
                </span>
              </div>
            </div>

            {result.is_alert ? (
              <Alert variant="destructive" className="border-fail bg-fail-tint">
                <SquareX aria-hidden className="size-4" />
                <AlertDescription className="font-bold text-current">
                  {`設定した範囲を外れています: ${result.alert_message ?? ""}`}
                </AlertDescription>
              </Alert>
            ) : (
              <Alert className="border-hairline bg-panel">
                <AlertDescription className="font-bold text-text">
                  測定値は設定した範囲内です。
                </AlertDescription>
              </Alert>
            )}

            <figure className="flex flex-col gap-2 rounded-md border border-hairline bg-panel p-3">
              <figcaption className="font-bold text-text">検出結果オーバーレイ</figcaption>
              {result.reading.overlay_image_id ? (
                <img
                  src={imageUrl(result.reading.overlay_image_id)}
                  alt="検出結果オーバーレイ"
                  data-testid="manual-overlay"
                  className="max-h-[58vh] w-full rounded-sm border border-hairline bg-white object-contain"
                />
              ) : (
                <p className="text-base text-steel">
                  検出結果のオーバーレイ画像は作れませんでした（中心を検出できなかったため）。
                </p>
              )}
            </figure>
          </CardContent>
        </Card>
      )}
    </section>
  );
}
