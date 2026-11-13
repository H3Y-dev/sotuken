import { useEffect, useState } from "react";
import { CircleCheck, QrCode, RefreshCw, SquareX, TriangleAlert, Usb, Wifi } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { QrCodeSvg } from "@/components/QrCodeSvg";
import {
  ApiError,
  cancelPairing,
  describeApiError,
  fetchPairing,
  startPairing,
} from "@/api/client";
import type { PairingStatus, RuntimeStatus, UsbStatus } from "@/api/types";
import { formatDateTime } from "@/lib/records";

export function SettingsView({
  runtime,
  runtimeError,
  usb,
  onRefreshRuntime,
}: {
  runtime: RuntimeStatus | null;
  runtimeError: string;
  usb: UsbStatus | null;
  onRefreshRuntime: () => Promise<void>;
}) {
  const [pairing, setPairing] = useState<PairingStatus | null>(null);
  const [pairingError, setPairingError] = useState("");
  const [busy, setBusy] = useState(false);
  const [expiredLocally, setExpiredLocally] = useState(false);
  const [localRemaining, setLocalRemaining] = useState(0);
  const [seenOwnerId, setSeenOwnerId] = useState<string>("");
  const [restartedNotice, setRestartedNotice] = useState(false);

  const loadPairing = async (signal?: AbortSignal) => {
    try {
      const p = await fetchPairing(signal);
      if (signal?.aborted) return;
      setPairingError("");
      if (seenOwnerId && p.owner_instance_id !== seenOwnerId) {
        setRestartedNotice(true);
      }
      setSeenOwnerId(p.owner_instance_id);
      setPairing(p);
      setLocalRemaining(Math.max(0, Math.ceil(p.remaining_seconds)));
      setExpiredLocally(false);
    } catch (err) {
      if (signal?.aborted) return;
      if (err instanceof ApiError && err.code === "owner_unavailable") {
        // 所有者停止時は QR を即時に隠す
        setPairing(null);
      }
      const msg = describeApiError(err);
      if (msg) setPairingError(msg);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadPairing(controller.signal);
    const timer = setInterval(() => {
      void loadPairing(controller.signal);
    }, 1000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ローカル時計でも期限を追い、期限切れになったら即時に QR を隠す
  useEffect(() => {
    if (!pairing?.active || !pairing.payload) {
      setLocalRemaining(0);
      return;
    }
    const startMs = Date.now();
    const initialSec = Math.max(0, pairing.remaining_seconds);
    const tick = () => {
      const elapsed = (Date.now() - startMs) / 1000;
      const rem = Math.max(0, Math.ceil(initialSec - elapsed));
      setLocalRemaining(rem);
      if (rem <= 0) {
        setExpiredLocally(true);
      }
    };
    tick();
    const timer = setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [pairing]);

  // runtime の owner_instance_id が変わった場合も再起動を検知して古い QR を隠す
  useEffect(() => {
    if (!runtime?.owner_instance_id) return;
    if (seenOwnerId && runtime.owner_instance_id !== seenOwnerId) {
      setRestartedNotice(true);
      setPairing(null);
    }
    setSeenOwnerId(runtime.owner_instance_id);
  }, [runtime?.owner_instance_id, seenOwnerId]);

  const handleStartPairing = async () => {
    setBusy(true);
    setPairingError("");
    setRestartedNotice(false);
    try {
      const p = await startPairing();
      setPairing(p);
      setLocalRemaining(Math.max(0, Math.ceil(p.remaining_seconds)));
      setExpiredLocally(false);
    } catch (err) {
      setPairingError(describeApiError(err));
      if (err instanceof ApiError && err.code === "pairing_active") {
        void loadPairing();
      } else if (err instanceof ApiError && err.code === "owner_unavailable") {
        setPairing(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleCancelPairing = async () => {
    setBusy(true);
    setPairingError("");
    try {
      await cancelPairing();
      await loadPairing();
    } catch (err) {
      setPairingError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const qrVisible =
    !runtimeError &&
    Boolean(pairing?.active && pairing?.payload) &&
    !expiredLocally &&
    localRemaining > 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-text">接続・設定</h2>
          <p className="text-base text-steel">
            PC受信口・スマホ登録QR・USB自動吸い出しの状態を確認できます。
          </p>
        </div>
        <Button type="button" variant="outline" size="field" onClick={() => void onRefreshRuntime()}>
          <RefreshCw aria-hidden />
          状態を更新
        </Button>
      </div>

      {restartedNotice && (
        <div
          role="status"
          className="rounded-md border border-warn bg-warn-tint px-4 py-3 text-base text-text"
        >
          所有プロセスが再起動されたため、前の招待QRは無効になりました。必要なら新しく作成してください。
        </div>
      )}

      {runtimeError && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-fail bg-fail-tint px-4 py-3 text-base font-bold text-fail"
        >
          <SquareX aria-hidden className="size-5 shrink-0" />
          {runtimeError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* 受信口とスマホ登録QR */}
        <Card className="border border-hairline bg-dial shadow-none">
          <CardContent className="flex flex-col gap-4 pt-5">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
              <div className="flex items-center gap-2">
                <Wifi aria-hidden className="size-5 text-ink" />
                <h3 className="text-xl font-bold text-text">スマホの送信先・QR登録</h3>
              </div>
              {runtime?.receiver_running ? (
                <Badge variant="ok" size="field">
                  <CircleCheck aria-hidden />
                  待ち受け中
                </Badge>
              ) : (
                <Badge variant="fail" size="field">
                  <SquareX aria-hidden />
                  停止中
                </Badge>
              )}
            </div>

            <dl className="grid grid-cols-1 gap-2 text-base">
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">送信先URL</dt>
                <dd className="g-num font-bold text-ink">{runtime?.receiver_url || "—"}</dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">所有者ID</dt>
                <dd className="g-num text-text" data-testid="owner-instance-id">
                  {runtime?.owner_instance_id || "—"}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">確認時刻</dt>
                <dd className="g-num text-steel">{formatDateTime(runtime?.observed_at)}</dd>
              </div>
            </dl>

            <div className="flex flex-wrap gap-3 pt-1">
              <Button
                type="button"
                size="field"
                disabled={busy || Boolean(runtimeError) || !runtime?.receiver_running || qrVisible}
                onClick={() => void handleStartPairing()}
              >
                <QrCode aria-hidden />
                スマホを登録
              </Button>
              <Button
                type="button"
                variant="outline"
                size="field"
                disabled={busy || Boolean(runtimeError)}
                onClick={() => void handleCancelPairing()}
              >
                登録を中止
              </Button>
            </div>

            {pairingError && (
              <p role="alert" className="rounded-md border border-warn bg-warn-tint px-3 py-2 text-base text-text">
                {pairingError}
              </p>
            )}

            {qrVisible && pairing?.payload ? (
              <div
                data-testid="pairing-qr-box"
                className="flex flex-col items-center gap-3 rounded-md border border-hairline bg-panel p-4"
              >
                <QrCodeSvg payload={pairing.payload} />
                <p className="g-num text-lg font-bold text-ink" data-testid="pairing-remaining">
                  残り {localRemaining} 秒
                </p>
                <p className="text-center text-base text-steel">
                  スマホの「送信先QR読取」で読み取ってください。期限が切れると自動で閉じます。
                </p>
              </div>
            ) : (
              <div
                data-testid="pairing-inactive"
                className="rounded-md border border-dashed border-rule bg-panel/60 p-4 text-base text-steel"
              >
                {expiredLocally
                  ? "QRの有効期限が切れました。必要なら「スマホを登録」から作り直してください。"
                  : "登録済み・期限切れ・中止後は、「スマホを登録」からQRを作り直してください。"}
              </div>
            )}
          </CardContent>
        </Card>

        {/* USB自動吸い出し */}
        <Card className="border border-hairline bg-dial shadow-none">
          <CardContent className="flex flex-col gap-4 pt-5">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
              <div className="flex items-center gap-2">
                <Usb aria-hidden className="size-5 text-ink" />
                <h3 className="text-xl font-bold text-text">USB自動吸い出し</h3>
              </div>
              {usb?.running ? (
                <Badge variant="ok" size="field">
                  <CircleCheck aria-hidden />
                  動作中
                </Badge>
              ) : usb?.enabled ? (
                <Badge variant="warn" size="field">
                  <TriangleAlert aria-hidden />
                  停止中
                </Badge>
              ) : (
                <Badge variant="wait" size="field">
                  無効
                </Badge>
              )}
            </div>

            <dl className="grid grid-cols-1 gap-2.5 text-base">
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">ADB認識</dt>
                <dd className="font-bold text-text">
                  {usb ? (usb.adb_found ? "利用可能" : "未検出") : "—"}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">接続端末</dt>
                <dd className="g-num font-bold text-text" data-testid="usb-device-count">
                  {usb ? `${usb.devices.length}台` : "—"}
                </dd>
              </div>
              {usb && usb.devices.length > 0 && (
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="text-steel">端末ID</dt>
                  <dd className="g-num text-text">{usb.devices.join("、")}</dd>
                </div>
              )}
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">吸い出し累計</dt>
                <dd className="g-num text-xl font-bold text-ink" data-testid="usb-pulled-total">
                  {usb ? `${usb.pulled_total}組` : "—"}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">巡回回数 / 周期</dt>
                <dd className="g-num text-steel">
                  {usb ? `${usb.cycles}回 / ${usb.interval}秒` : "—"}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-steel">所有者ID</dt>
                <dd className="g-num text-steel">{usb?.owner_instance_id || "—"}</dd>
              </div>
            </dl>

            {usb?.last_error && (
              <div
                role="alert"
                data-testid="usb-last-error"
                className="flex items-start gap-2 rounded-md border border-warn bg-warn-tint px-3 py-2.5 text-base text-text"
              >
                <TriangleAlert aria-hidden className="mt-1 size-5 shrink-0 text-warn" />
                <span>USBエラー: {usb.last_error}</span>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
