import { useCallback, useEffect, useState, type FormEvent } from "react";
import { RefreshCw, SquareX } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
  createRoute,
  deleteRoute,
  describeApiError,
  getRoute,
  listDevices,
  listRoutes,
  updateRoute,
} from "@/api/client";
import type {
  Device,
  RouteDetail,
  RouteDevice,
  RouteSummary,
} from "@/api/types";
import { QrCodeSvg } from "./QrCodeSvg";

const NEW_ROUTE = "__new__";
const DEVICE_ID_RE = /^[A-Za-z0-9._-]{1,32}$/;

type Notice = { kind: "ok" | "error"; text: string };

function formatUpdated(updatedAt: string): string {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return updatedAt;
  return date.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" });
}

function isAuthError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.code === "unauthenticated");
}

function routeErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 422 || err.code === "validation_failed") {
      return "ルート名は1〜64文字、機器は1〜200台で入力してください。";
    }
    if (err.status === 404 || err.code === "not_found") {
      return "ルートが見つかりませんでした。一覧を再読込してください。";
    }
  }
  return describeApiError(err) || "ルートの保存に失敗しました。";
}

export function RoutesView({ onAuthExpired }: { onAuthExpired?: () => void }) {
  const [routes, setRoutes] = useState<RouteSummary[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [selectedId, setSelectedId] = useState(NEW_ROUTE);
  const [detail, setDetail] = useState<RouteDetail | null>(null);
  const [routeName, setRouteName] = useState("");
  const [routeDevices, setRouteDevices] = useState<RouteDevice[]>([]);
  const [registeredId, setRegisteredId] = useState("");
  const [manualId, setManualId] = useState("");
  const [manualName, setManualName] = useState("");
  const [addError, setAddError] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteChecked, setDeleteChecked] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setLoadError("");
      try {
        const [routeItems, deviceItems] = await Promise.all([
          listRoutes(signal),
          listDevices(signal),
        ]);
        if (signal?.aborted) return;
        setRoutes(routeItems);
        setDevices(deviceItems);
      } catch (err) {
        if (signal?.aborted) return;
        if (isAuthError(err)) onAuthExpired?.();
        setLoadError(describeApiError(err) || "通信エラーが発生しました。");
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [onAuthExpired],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openNew = useCallback(() => {
    setSelectedId(NEW_ROUTE);
    setDetail(null);
    setRouteName("");
    setRouteDevices([]);
    setRegisteredId("");
    setManualId("");
    setManualName("");
    setAddError("");
    setNotice(null);
    setDeleteChecked(false);
  }, []);

  const selectRoute = useCallback(
    async (id: string) => {
      setNotice(null);
      setAddError("");
      setDeleteChecked(false);
      if (id === NEW_ROUTE) {
        openNew();
        return;
      }
      setSelectedId(id);
      setDetail(null);
      setRouteName("");
      setRouteDevices([]);
      setSaving(false);
      const controller = new AbortController();
      try {
        const data = await getRoute(id, controller.signal);
        if (controller.signal.aborted) return;
        setDetail(data);
        setRouteName(data.name);
        setRouteDevices(data.devices.map((d) => ({ id: d.id, name: d.name })));
      } catch (err) {
        if (controller.signal.aborted) return;
        if (isAuthError(err)) onAuthExpired?.();
        setNotice({ kind: "error", text: routeErrorText(err) });
      }
    },
    [onAuthExpired, openNew],
  );

  const addDevice = (device: RouteDevice) => {
    if (routeDevices.some((d) => d.id === device.id)) {
      setAddError(`機器ID ${device.id} はすでにルートに追加されています。`);
      return;
    }
    setRouteDevices((prev) => [...prev, device]);
    setAddError("");
  };

  const addRegistered = () => {
    const found = devices.find((d) => d.device_id === registeredId);
    if (!found) {
      setAddError("登録済みの機器を選択してください。");
      return;
    }
    addDevice({ id: found.device_id, name: found.device_name });
    setRegisteredId("");
  };

  const addManual = () => {
    const id = manualId.trim();
    const name = manualName.trim();
    if (!DEVICE_ID_RE.test(id)) {
      setAddError("機器IDは半角英数字と . _ - の1〜32文字で入力してください。");
      return;
    }
    if (name.length === 0 || name.length > 64) {
      setAddError("機器名は1〜64文字で入力してください。");
      return;
    }
    addDevice({ id, name });
    setManualId("");
    setManualName("");
  };

  const updateRouteDeviceName = (index: number, name: string) => {
    setRouteDevices((prev) => prev.map((d, i) => (i === index ? { ...d, name } : d)));
  };

  const moveDevice = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= routeDevices.length) return;
    setRouteDevices((prev) => {
      const next = [...prev];
      const [moved] = next.splice(index, 1);
      next.splice(target, 0, moved);
      return next;
    });
  };

  const removeDevice = (index: number) => {
    setRouteDevices((prev) => prev.filter((_, i) => i !== index));
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (saving) return;
    const name = routeName.trim();
    if (name.length === 0 || name.length > 64) {
      setNotice({ kind: "error", text: "ルート名は1〜64文字で入力してください。" });
      return;
    }
    if (routeDevices.length < 1 || routeDevices.length > 200) {
      setNotice({ kind: "error", text: "ルートに登録する機器は1〜200台にしてください。" });
      return;
    }

    setSaving(true);
    setNotice(null);
    const input = { name, devices: routeDevices };
    try {
      const saved =
        selectedId === NEW_ROUTE
          ? await createRoute(input)
          : await updateRoute(selectedId, input);
      const items = await listRoutes();
      setRoutes(items);
      setSelectedId(saved.route_id);
      setDetail(saved);
      setRouteName(saved.name);
      setRouteDevices(saved.devices.map((d) => ({ id: d.id, name: d.name })));
      setDeleteChecked(false);
      setNotice({ kind: "ok", text: `ルート「${saved.name}」を保存しました。` });
    } catch (err) {
      if (isAuthError(err)) onAuthExpired?.();
      setNotice({ kind: "error", text: routeErrorText(err) });
    } finally {
      setSaving(false);
    }
  };

  const removeRoute = async () => {
    if (!deleteChecked || selectedId === NEW_ROUTE || deleting) return;
    setDeleting(true);
    setNotice(null);
    try {
      await deleteRoute(selectedId);
      const items = await listRoutes();
      setRoutes(items);
      openNew();
      setNotice({ kind: "ok", text: "ルートを削除しました。" });
    } catch (err) {
      if (isAuthError(err)) onAuthExpired?.();
      setNotice({ kind: "error", text: routeErrorText(err) });
    } finally {
      setDeleting(false);
    }
  };

  const selectedName = routes.find((r) => r.route_id === selectedId)?.name ?? "";
  const isExisting = selectedId !== NEW_ROUTE && detail !== null;

  return (
    <section className="flex flex-col gap-4" aria-labelledby="routes-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 id="routes-heading" className="text-xl font-bold text-ink">
          ルート
        </h1>
        <Button
          type="button"
          size="field"
          variant="outline"
          className="border-hairline text-steel"
          disabled={loading || saving || deleting}
          onClick={() => {
            void load();
            if (selectedId !== NEW_ROUTE && detail) void selectRoute(selectedId);
          }}
        >
          <RefreshCw aria-hidden />
          更新
        </Button>
      </div>

      {loadError && (
        <Alert variant="destructive" className="border-fail bg-fail-tint">
          <SquareX aria-hidden className="size-4" />
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3 font-bold text-current">
            <span>ルート一覧を取得できませんでした（{loadError}）</span>
            <Button
              type="button"
              size="field"
              variant="outline"
              className="border-hairline"
              disabled={loading}
              onClick={() => void load()}
            >
              <RefreshCw aria-hidden />
              再読込
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {notice && (
        <Alert
          variant={notice.kind === "error" ? "destructive" : "default"}
          className={notice.kind === "error" ? "border-fail bg-fail-tint" : "border-hairline bg-dial"}
        >
          {notice.kind === "error" ? <SquareX aria-hidden className="size-4" /> : null}
          <AlertDescription className="font-bold text-current">{notice.text}</AlertDescription>
        </Alert>
      )}

      <Card className="border-hairline bg-dial">
        <CardHeader className="border-b border-hairline">
          <CardTitle className="flex flex-wrap items-center gap-2 text-ink">
            点検ルートの選択
            <Badge variant="tag" size="field" className="g-num">{routes.length}件</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3 pt-4">
          <span className="font-bold text-text" id="route-selector-label">
            ルート
          </span>
          <div className="flex flex-wrap gap-2" role="group" aria-labelledby="route-selector-label">
            <Button
              type="button"
              size="field"
              variant={selectedId === NEW_ROUTE ? "secondary" : "outline"}
              className={selectedId === NEW_ROUTE ? "border-hairline font-bold text-ink" : "border-hairline text-steel"}
              aria-current={selectedId === NEW_ROUTE ? "true" : undefined}
              disabled={loading || saving || deleting}
              onClick={() => void selectRoute(NEW_ROUTE)}
            >
              新規作成
            </Button>
            {routes.map((r) => (
              <Button
                key={r.route_id}
                type="button"
                size="field"
                variant={selectedId === r.route_id ? "secondary" : "outline"}
                className={selectedId === r.route_id ? "border-hairline font-bold text-ink" : "border-hairline text-steel"}
                aria-current={selectedId === r.route_id ? "true" : undefined}
                disabled={loading || saving || deleting}
                onClick={() => void selectRoute(r.route_id)}
              >
                {r.name}（{r.count}台）
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      <form onSubmit={(e) => void save(e)} noValidate className="flex flex-col gap-4">
        <Card className="border-hairline bg-dial">
          <CardHeader className="border-b border-hairline">
            <CardTitle className="text-ink">
              {selectedId === NEW_ROUTE ? "新しいルート" : `ルート: ${selectedName || routeName || selectedId}`}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 pt-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="route-name" className="font-bold text-text">
                ルート名
              </label>
              <Input
                id="route-name"
                value={routeName}
                maxLength={64}
                disabled={saving || deleting}
                onChange={(e) => setRouteName(e.target.value)}
              />
            </div>

            {isExisting && (
              <div className="flex flex-col gap-2 rounded-md border border-hairline bg-panel px-4 py-3 text-base text-steel">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-text">ルートID</span>
                  <span className="g-num text-text" data-testid="route-id">{detail.route_id}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-text">更新</span>
                  <span className="g-num text-text" data-testid="route-updated-at">
                    {formatUpdated(detail.updated_at)}
                  </span>
                </div>
              </div>
            )}

            <div className="flex flex-col gap-2">
              <h2 className="font-bold text-text" id="registered-device-label">登録済みの機器から追加</h2>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-steel">機器</span>
                <div className="flex flex-wrap gap-2" role="group" aria-labelledby="registered-device-label">
                  {devices.map((d) => (
                    <Button
                      key={d.device_id}
                      type="button"
                      size="field"
                      variant={registeredId === d.device_id ? "secondary" : "outline"}
                      className="border-hairline text-steel"
                      aria-label={`${d.device_name}（${d.device_id}）`}
                      aria-current={registeredId === d.device_id ? "true" : undefined}
                      disabled={saving || deleting}
                      onClick={() => {
                        setRegisteredId(d.device_id);
                        setAddError("");
                      }}
                    >
                      {d.device_name}（{d.device_id}）
                    </Button>
                  ))}
                </div>
                <Button
                  type="button"
                  size="field"
                  variant="outline"
                  className="border-hairline"
                  disabled={saving || deleting || !registeredId}
                  onClick={addRegistered}
                >
                  選んだ機器を追加
                </Button>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <h2 className="font-bold text-text">手入力で追加</h2>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-2">
                  <label htmlFor="route-manual-id" className="text-steel">
                    機器ID
                  </label>
                  <Input
                    id="route-manual-id"
                    value={manualId}
                    maxLength={32}
                    disabled={saving || deleting}
                    onChange={(e) => {
                      setManualId(e.target.value);
                      setAddError("");
                    }}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <label htmlFor="route-manual-name" className="text-steel">
                    機器名
                  </label>
                  <Input
                    id="route-manual-name"
                    value={manualName}
                    maxLength={64}
                    disabled={saving || deleting}
                    onChange={(e) => {
                      setManualName(e.target.value);
                      setAddError("");
                    }}
                  />
                </div>
                <Button
                  type="button"
                  size="field"
                  variant="outline"
                  className="border-hairline"
                  disabled={saving || deleting}
                  onClick={addManual}
                >
                  手入力で追加
                </Button>
              </div>
            </div>

            {addError && (
              <Alert variant="destructive" className="border-fail bg-fail-tint">
                <SquareX aria-hidden className="size-4" />
                <AlertDescription className="font-bold text-current">{addError}</AlertDescription>
              </Alert>
            )}

            <div className="border border-hairline bg-panel">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>順番</TableHead>
                    <TableHead>機器ID</TableHead>
                    <TableHead>機器名</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {routeDevices.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-steel">
                        機器が追加されていません
                      </TableCell>
                    </TableRow>
                  ) : (
                    routeDevices.map((device, index) => (
                      <TableRow key={`${device.id}-${index}`}>
                        <TableCell className="g-num">{index + 1}</TableCell>
                        <TableCell className="g-num text-text">{device.id}</TableCell>
                        <TableCell>
                          <Input
                            aria-label={`${device.id} の機器名`}
                            value={device.name}
                            maxLength={64}
                            disabled={saving || deleting}
                            onChange={(e) => updateRouteDeviceName(index, e.target.value)}
                          />
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="border-hairline"
                              aria-label={`${device.id} を上へ`}
                              disabled={saving || deleting || index === 0}
                              onClick={() => moveDevice(index, -1)}
                            >
                              上へ
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="border-hairline"
                              aria-label={`${device.id} を下へ`}
                              disabled={saving || deleting || index === routeDevices.length - 1}
                              onClick={() => moveDevice(index, 1)}
                            >
                              下へ
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="destructive"
                              aria-label={`${device.id} を削除`}
                              disabled={saving || deleting}
                              onClick={() => removeDevice(index)}
                            >
                              削除
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="field" disabled={saving || deleting}>
            {saving ? "保存中..." : "ルートを保存"}
          </Button>
          <span className="g-num text-steel">{routeDevices.length}台</span>
        </div>
      </form>

      {isExisting && (
        <>
          <Card className="border-hairline bg-dial">
            <CardHeader className="border-b border-hairline">
              <CardTitle className="text-ink">スマホへ渡すルートQR（保存済みの内容）</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap items-start gap-4 pt-4 text-base">
              {detail.qr_payload !== null ? (
                <QrCodeSvg
                  payload={detail.qr_payload}
                  label="点検ルート配布用QRコード"
                />
              ) : (
                <p className="text-steel">機器の一覧が大きいため、Wi-Fiで取得してください。</p>
              )}
            </CardContent>
          </Card>

          <Card className="border-hairline bg-dial">
            <CardHeader className="border-b border-hairline">
              <CardTitle className="text-ink">ルートの削除</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 pt-4">
              <label className="flex items-center gap-3 text-base text-text">
                <Checkbox
                  checked={deleteChecked}
                  disabled={saving || deleting}
                  onCheckedChange={(checked) => setDeleteChecked(checked === true)}
                />
                このルートを削除することを確認しました
              </label>
              <div>
                <Button
                  type="button"
                  size="field"
                  variant="destructive"
                  disabled={!deleteChecked || saving || deleting}
                  onClick={() => void removeRoute()}
                >
                  {deleting ? "削除中..." : "ルートを削除"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </section>
  );
}
