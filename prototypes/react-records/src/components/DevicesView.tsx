import { useCallback, useEffect, useState, type FormEvent } from "react";
import { RefreshCw, SquareX } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ApiError,
  createDevice,
  describeApiError,
  listDevices,
  updateDevice,
} from "@/api/client";
import type { Device, DeviceInput } from "@/api/types";
import "./devices.css";

type FormMode = { kind: "create" } | { kind: "edit"; deviceId: string } | null;

type FieldName =
  | "device_id"
  | "device_name"
  | "unit"
  | "min_value"
  | "max_value"
  | "tolerance_min"
  | "tolerance_max";

type FormValues = Record<FieldName, string>;
type FieldErrors = Partial<Record<FieldName, string>>;

const EMPTY_FORM: FormValues = {
  device_id: "",
  device_name: "",
  unit: "",
  min_value: "",
  max_value: "",
  tolerance_min: "",
  tolerance_max: "",
};

const DEVICE_ID_RE = /^[A-Za-z0-9._-]{1,32}$/;

function hasControlChar(value: string): boolean {
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code <= 0x1f || (code >= 0x7f && code <= 0x9f)) return true;
  }
  return false;
}

function sortDevicesById(items: Device[]): Device[] {
  return [...items].sort((a, b) =>
    a.device_id < b.device_id ? -1 : a.device_id > b.device_id ? 1 : 0,
  );
}

function formatRange(min: number | null, max: number | null): string {
  if (min === null || max === null) return "未設定";
  return `${min} 〜 ${max}`;
}

function toFormValues(device: Device): FormValues {
  return {
    device_id: device.device_id,
    device_name: device.device_name,
    unit: device.unit ?? "",
    min_value: device.min_value === null ? "" : String(device.min_value),
    max_value: device.max_value === null ? "" : String(device.max_value),
    tolerance_min: device.tolerance_min === null ? "" : String(device.tolerance_min),
    tolerance_max: device.tolerance_max === null ? "" : String(device.tolerance_max),
  };
}

function parseOptionalNumber(
  raw: string,
  label: string,
): { value: number | null; error?: string } {
  const trimmed = raw.trim();
  if (trimmed === "") return { value: null };
  const num = Number(trimmed);
  if (!Number.isFinite(num)) {
    return { value: null, error: `${label}は有限の数値で入力してください。` };
  }
  return { value: num };
}

function validateForm(
  values: FormValues,
  isCreate: boolean,
): { payload: (DeviceInput & { device_id?: string }) | null; errors: FieldErrors } {
  const errors: FieldErrors = {};

  if (isCreate) {
    if (!values.device_id) {
      errors.device_id = "機器IDを入力してください。";
    } else if (/^\s|\s$/.test(values.device_id)) {
      errors.device_id = "機器IDの前後に空白は使えません。";
    } else if (!DEVICE_ID_RE.test(values.device_id)) {
      errors.device_id = "機器IDは半角英数字と . _ - の1〜32文字で入力してください。";
    }
  }

  if (hasControlChar(values.device_name)) {
    errors.device_name = "機器名に制御文字は使えません。";
  } else {
    const trimmedName = values.device_name.trim();
    const len = [...trimmedName].length;
    if (len === 0 || len > 64) {
      errors.device_name = "機器名は1〜64文字で入力してください。";
    } else if (trimmedName === "unknown") {
      errors.device_name = "機器名に unknown は使用できません。";
    }
  }

  let unitValue: string | null = null;
  if (hasControlChar(values.unit)) {
    errors.unit = "単位に制御文字は使えません。";
  } else {
    const trimmedUnit = values.unit.trim();
    if (trimmedUnit !== "") {
      if ([...trimmedUnit].length > 16) {
        errors.unit = "単位は16文字以内で入力してください。";
      } else {
        unitValue = trimmedUnit;
      }
    }
  }

  const minRes = parseOptionalNumber(values.min_value, "目盛り最小");
  if (minRes.error) errors.min_value = minRes.error;
  const maxRes = parseOptionalNumber(values.max_value, "目盛り最大");
  if (maxRes.error) errors.max_value = maxRes.error;

  const tolMinRes = parseOptionalNumber(values.tolerance_min, "許容最小");
  if (tolMinRes.error) errors.tolerance_min = tolMinRes.error;
  const tolMaxRes = parseOptionalNumber(values.tolerance_max, "許容最大");
  if (tolMaxRes.error) errors.tolerance_max = tolMaxRes.error;

  if (!minRes.error && !maxRes.error) {
    if ((minRes.value === null) !== (maxRes.value === null)) {
      const msg = "目盛り範囲は最小と最大の両方を入力するか、両方空欄にしてください。";
      if (minRes.value === null) errors.min_value = msg;
      else errors.max_value = msg;
    } else if (
      minRes.value !== null &&
      maxRes.value !== null &&
      minRes.value >= maxRes.value
    ) {
      errors.min_value = "目盛り最小は目盛り最大より小さい値にしてください。";
    }
  }

  if (!tolMinRes.error && !tolMaxRes.error) {
    if ((tolMinRes.value === null) !== (tolMaxRes.value === null)) {
      const msg = "許容範囲は最小と最大の両方を入力するか、両方空欄にしてください。";
      if (tolMinRes.value === null) errors.tolerance_min = msg;
      else errors.tolerance_max = msg;
    } else if (
      tolMinRes.value !== null &&
      tolMaxRes.value !== null &&
      tolMinRes.value > tolMaxRes.value
    ) {
      errors.tolerance_min = "許容最小は許容最大以下にしてください。";
    }
  }

  if (
    !errors.min_value &&
    !errors.max_value &&
    !errors.tolerance_min &&
    !errors.tolerance_max &&
    minRes.value !== null &&
    maxRes.value !== null &&
    tolMinRes.value !== null &&
    tolMaxRes.value !== null
  ) {
    if (tolMinRes.value < minRes.value || tolMaxRes.value > maxRes.value) {
      if (tolMinRes.value < minRes.value) {
        errors.tolerance_min = "許容最小は目盛り最小以上にしてください。";
      }
      if (tolMaxRes.value > maxRes.value) {
        errors.tolerance_max = "許容最大は目盛り最大以下にしてください。";
      }
    }
  }

  if (Object.keys(errors).length > 0) {
    return { payload: null, errors };
  }

  const base: DeviceInput = {
    device_name: values.device_name.trim(),
    unit: unitValue,
    min_value: minRes.value,
    max_value: maxRes.value,
    tolerance_min: tolMinRes.value,
    tolerance_max: tolMaxRes.value,
  };

  return {
    payload: isCreate ? { ...base, device_id: values.device_id } : base,
    errors: {},
  };
}

function formatSubmitError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409 || err.code === "device_conflict") {
      return "同じ機器ID（大文字・小文字違いを含む）がすでに登録されています。";
    }
    if (err.status === 422 || err.code === "validation_failed") {
      return "入力内容を確認してください（ID・機器名・単位・数値の範囲が条件を満たしていません）。";
    }
    if (err.status === 404 || err.code === "not_found") {
      return "対象の機器が見つかりませんでした。一覧を再読込してください。";
    }
    if (err.status === 401 || err.code === "unauthenticated") {
      return "セッションが失効しました。アプリを再起動してURLを開き直してください。";
    }
  }
  return describeApiError(err) || "保存に失敗しました。";
}

export function DevicesView({ onAuthExpired }: { onAuthExpired?: () => void }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [formMode, setFormMode] = useState<FormMode>(null);
  const [formValues, setFormValues] = useState<FormValues>(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState("");
  const [saving, setSaving] = useState(false);

  const loadDevices = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setLoadError("");
      try {
        const items = await listDevices(signal);
        if (signal?.aborted) return;
        setDevices(sortDevicesById(items));
      } catch (err) {
        if (signal?.aborted) return;
        if (err instanceof ApiError && (err.status === 401 || err.code === "unauthenticated")) {
          onAuthExpired?.();
        }
        setLoadError(describeApiError(err) || "通信エラーが発生しました。");
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [onAuthExpired],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadDevices(controller.signal);
    return () => controller.abort();
  }, [loadDevices]);

  const openCreate = () => {
    setFormMode({ kind: "create" });
    setFormValues(EMPTY_FORM);
    setFieldErrors({});
    setSubmitError("");
  };

  const openEdit = (device: Device) => {
    setFormMode({ kind: "edit", deviceId: device.device_id });
    setFormValues(toFormValues(device));
    setFieldErrors({});
    setSubmitError("");
  };

  const closeForm = () => {
    if (saving) return;
    setFormMode(null);
    setFieldErrors({});
    setSubmitError("");
  };

  const updateField = (name: FieldName, value: string) => {
    setFormValues((prev) => ({ ...prev, [name]: value }));
    if (fieldErrors[name]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!formMode || saving) return;

    const isCreate = formMode.kind === "create";
    const { payload, errors } = validateForm(formValues, isCreate);
    if (!payload) {
      setFieldErrors(errors);
      setSubmitError("");
      return;
    }

    setFieldErrors({});
    setSubmitError("");
    setSaving(true);
    try {
      const saved = isCreate
        ? await createDevice(payload as DeviceInput & { device_id: string })
        : await updateDevice(formMode.deviceId, payload);

      setDevices((prev) => {
        const exists = prev.some((d) => d.device_id === saved.device_id);
        const next = exists
          ? prev.map((d) => (d.device_id === saved.device_id ? saved : d))
          : [...prev, saved];
        return sortDevicesById(next);
      });
      setFormMode(null);
      setFormValues(EMPTY_FORM);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.code === "unauthenticated")) {
        onAuthExpired?.();
      }
      setSubmitError(formatSubmitError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="devices" aria-labelledby="devices-heading">
      <div className="devices-header">
        <div>
          <h1 id="devices-heading" className="devices-title">
            機器登録
          </h1>
          <p className="mt-1 text-base text-steel">
            メーターのID・名前・単位・目盛り範囲・許容範囲を登録します（ここで登録した内容を『ルート』や『点検確認』で使います）。{" "}
            <a href="#routes" className="font-bold text-ink underline underline-offset-4">
              登録後は「ルート」で巡回順を設定できます
            </a>
          </p>
        </div>
        <div className="devices-actions">
          <Button
            type="button"
            size="field"
            className="devices-btn-primary"
            disabled={saving}
            onClick={openCreate}
          >
            新規登録
          </Button>
          <Button
            type="button"
            size="field"
            variant="outline"
            className="devices-btn-outline"
            disabled={loading || saving}
            onClick={() => void loadDevices()}
          >
            <RefreshCw aria-hidden />
            再読込
          </Button>
        </div>
      </div>

      {formMode && (
        <form
          className="devices-card"
          onSubmit={(e) => void handleSubmit(e)}
          noValidate
          aria-labelledby="devices-form-heading"
        >
          <h2 id="devices-form-heading" className="devices-form-title">
            {formMode.kind === "create" ? "機器を追加" : "機器を編集"}
          </h2>

          {submitError && (
            <Alert variant="destructive" className="devices-alert">
              <SquareX aria-hidden className="size-4" />
              <AlertDescription className="font-bold text-current">
                {submitError}
              </AlertDescription>
            </Alert>
          )}

          <div className="devices-form-grid">
            <div className="devices-field">
              <label htmlFor="device-id" className="devices-label">
                機器ID
              </label>
              <Input
                id="device-id"
                name="device_id"
                type="text"
                className="devices-input devices-num"
                value={formValues.device_id}
                readOnly={formMode.kind === "edit"}
                aria-readonly={formMode.kind === "edit" ? "true" : undefined}
                aria-invalid={fieldErrors.device_id ? "true" : undefined}
                aria-describedby={fieldErrors.device_id ? "device-id-error" : undefined}
                onChange={(e) => updateField("device_id", e.target.value)}
              />
              {fieldErrors.device_id && (
                <p id="device-id-error" className="devices-field-error">
                  {fieldErrors.device_id}
                </p>
              )}
            </div>

            <div className="devices-field">
              <label htmlFor="device-name" className="devices-label">
                機器名
              </label>
              <Input
                id="device-name"
                name="device_name"
                type="text"
                className="devices-input"
                value={formValues.device_name}
                aria-invalid={fieldErrors.device_name ? "true" : undefined}
                aria-describedby={fieldErrors.device_name ? "device-name-error" : undefined}
                onChange={(e) => updateField("device_name", e.target.value)}
              />
              {fieldErrors.device_name && (
                <p id="device-name-error" className="devices-field-error">
                  {fieldErrors.device_name}
                </p>
              )}
            </div>

            <div className="devices-field">
              <label htmlFor="device-unit" className="devices-label">
                単位
              </label>
              <Input
                id="device-unit"
                name="unit"
                type="text"
                className="devices-input"
                value={formValues.unit}
                aria-invalid={fieldErrors.unit ? "true" : undefined}
                aria-describedby={fieldErrors.unit ? "device-unit-error" : undefined}
                onChange={(e) => updateField("unit", e.target.value)}
              />
              {fieldErrors.unit && (
                <p id="device-unit-error" className="devices-field-error">
                  {fieldErrors.unit}
                </p>
              )}
            </div>

            <div className="devices-field" aria-hidden="true" />

            <div className="devices-field">
              <label htmlFor="device-min-value" className="devices-label">
                目盛り最小
              </label>
              <Input
                id="device-min-value"
                name="min_value"
                type="text"
                inputMode="decimal"
                className="devices-input devices-num"
                value={formValues.min_value}
                aria-invalid={fieldErrors.min_value ? "true" : undefined}
                aria-describedby={fieldErrors.min_value ? "device-min-value-error" : undefined}
                onChange={(e) => updateField("min_value", e.target.value)}
              />
              {fieldErrors.min_value && (
                <p id="device-min-value-error" className="devices-field-error">
                  {fieldErrors.min_value}
                </p>
              )}
            </div>

            <div className="devices-field">
              <label htmlFor="device-max-value" className="devices-label">
                目盛り最大
              </label>
              <Input
                id="device-max-value"
                name="max_value"
                type="text"
                inputMode="decimal"
                className="devices-input devices-num"
                value={formValues.max_value}
                aria-invalid={fieldErrors.max_value ? "true" : undefined}
                aria-describedby={fieldErrors.max_value ? "device-max-value-error" : undefined}
                onChange={(e) => updateField("max_value", e.target.value)}
              />
              {fieldErrors.max_value && (
                <p id="device-max-value-error" className="devices-field-error">
                  {fieldErrors.max_value}
                </p>
              )}
            </div>

            <div className="devices-field">
              <label htmlFor="device-tolerance-min" className="devices-label">
                許容最小
              </label>
              <Input
                id="device-tolerance-min"
                name="tolerance_min"
                type="text"
                inputMode="decimal"
                className="devices-input devices-num"
                value={formValues.tolerance_min}
                aria-invalid={fieldErrors.tolerance_min ? "true" : undefined}
                aria-describedby={
                  fieldErrors.tolerance_min ? "device-tolerance-min-error" : undefined
                }
                onChange={(e) => updateField("tolerance_min", e.target.value)}
              />
              {fieldErrors.tolerance_min && (
                <p id="device-tolerance-min-error" className="devices-field-error">
                  {fieldErrors.tolerance_min}
                </p>
              )}
            </div>

            <div className="devices-field">
              <label htmlFor="device-tolerance-max" className="devices-label">
                許容最大
              </label>
              <Input
                id="device-tolerance-max"
                name="tolerance_max"
                type="text"
                inputMode="decimal"
                className="devices-input devices-num"
                value={formValues.tolerance_max}
                aria-invalid={fieldErrors.tolerance_max ? "true" : undefined}
                aria-describedby={
                  fieldErrors.tolerance_max ? "device-tolerance-max-error" : undefined
                }
                onChange={(e) => updateField("tolerance_max", e.target.value)}
              />
              {fieldErrors.tolerance_max && (
                <p id="device-tolerance-max-error" className="devices-field-error">
                  {fieldErrors.tolerance_max}
                </p>
              )}
            </div>
          </div>

          <div className="devices-form-footer">
            <Button
              type="submit"
              size="field"
              className="devices-btn-primary"
              disabled={saving}
            >
              {saving ? "保存中..." : formMode.kind === "create" ? "登録する" : "保存する"}
            </Button>
            <Button
              type="button"
              size="field"
              variant="outline"
              className="devices-btn-outline"
              disabled={saving}
              onClick={closeForm}
            >
              キャンセル
            </Button>
          </div>
        </form>
      )}

      {loadError && (
        <Alert variant="destructive" className="devices-alert">
          <SquareX aria-hidden className="size-4" />
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3 font-bold text-current">
            <span>機器一覧を取得できませんでした（{loadError}）</span>
            <Button
              type="button"
              size="field"
              variant="outline"
              className="devices-btn-outline"
              disabled={loading || saving}
              onClick={() => void loadDevices()}
            >
              <RefreshCw aria-hidden />
              再読込
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="devices-table-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>機器ID</TableHead>
              <TableHead>機器名</TableHead>
              <TableHead>単位</TableHead>
              <TableHead>目盛り範囲</TableHead>
              <TableHead>許容範囲</TableHead>
              <TableHead>編集</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && devices.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="devices-empty">
                  読み込み中
                </TableCell>
              </TableRow>
            ) : devices.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="devices-empty">
                  登録済みの機器はありません
                </TableCell>
              </TableRow>
            ) : (
              devices.map((d) => (
                <TableRow key={d.device_id}>
                  <TableCell className="devices-num">{d.device_id}</TableCell>
                  <TableCell>{d.device_name}</TableCell>
                  <TableCell className={d.unit === null ? "devices-muted" : undefined}>
                    {d.unit ?? "未設定"}
                  </TableCell>
                  <TableCell
                    className={
                      d.min_value === null || d.max_value === null
                        ? "devices-muted"
                        : "devices-num"
                    }
                  >
                    {formatRange(d.min_value, d.max_value)}
                  </TableCell>
                  <TableCell
                    className={
                      d.tolerance_min === null || d.tolerance_max === null
                        ? "devices-muted"
                        : "devices-num"
                    }
                  >
                    {formatRange(d.tolerance_min, d.tolerance_max)}
                  </TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="devices-btn-outline"
                      disabled={saving}
                      onClick={() => openEdit(d)}
                    >
                      編集
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
