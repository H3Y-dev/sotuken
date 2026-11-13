import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { describeApiError, fetchImageBlobUrl, fetchReading } from "@/api/client";
import type { Reading } from "@/api/types";
import { displayNameOf, formatDateTime, readingTimestamp, statusLabelOf } from "@/lib/records";

type ViewMode = "both" | "overlay" | "original";

interface ImageSlot {
  loading: boolean;
  url: string | null;
  missing: boolean;
  error: string;
}

const emptySlot = (hasId: boolean): ImageSlot => ({
  loading: hasId,
  url: null,
  missing: !hasId,
  error: "",
});

export function OverlayPreview({
  reading,
  onClose,
}: {
  reading: Reading;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Reading>(reading);
  const [mode, setMode] = useState<ViewMode>("both");
  const [original, setOriginal] = useState<ImageSlot>(() => emptySlot(Boolean(reading.image_id)));
  const [overlay, setOverlay] = useState<ImageSlot>(() => emptySlot(Boolean(reading.overlay_image_id)));
  const [detailError, setDetailError] = useState("");
  const [loadedAt, setLoadedAt] = useState<Record<string, string>>({});

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    const revokers: (() => void)[] = [];

    async function load() {
      setDetailError("");
      let row = reading;
      try {
        row = await fetchReading(reading.id, controller.signal);
        if (!controller.signal.aborted) setDetail(row);
      } catch (err) {
        if (controller.signal.aborted) return;
        setDetailError(describeApiError(err));
      }

      const loadOne = async (
        imageId: string | null,
        setter: React.Dispatch<React.SetStateAction<ImageSlot>>,
      ) => {
        if (!imageId) {
          if (!controller.signal.aborted) {
            setter({ loading: false, url: null, missing: true, error: "" });
          }
          return;
        }
        setter({ loading: true, url: null, missing: false, error: "" });
        try {
          const blob = await fetchImageBlobUrl(imageId, controller.signal);
          if (controller.signal.aborted) {
            blob?.revoke();
            return;
          }
          if (!blob) {
            setter({ loading: false, url: null, missing: true, error: "" });
            return;
          }
          revokers.push(blob.revoke);
          setter({ loading: false, url: blob.url, missing: false, error: "" });
        } catch (err) {
          if (controller.signal.aborted) return;
          setter({
            loading: false,
            url: null,
            missing: false,
            error: describeApiError(err),
          });
        }
      };

      await Promise.all([
        loadOne(row.image_id, setOriginal),
        loadOne(row.overlay_image_id, setOverlay),
      ]);
    }

    void load();
    return () => {
      controller.abort();
      for (const revoke of revokers) revoke();
    };
  }, [reading]);

  const showOriginal = mode === "both" || mode === "original";
  const showOverlay = mode === "both" || mode === "overlay";
  const label = statusLabelOf(detail);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="preview-dialog-title"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-5xl flex-col gap-4 overflow-y-auto rounded-md border border-hairline bg-dial p-5 text-text shadow-lg"
        onClick={(e) => e.stopPropagation()}
        data-preview-reading-id={detail.id}
      >
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-hairline pb-3">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 id="preview-dialog-title" className="text-xl font-bold text-text">
                {displayNameOf(detail)}
              </h2>
              <StatusBadge label={label} />
              {detail.device_id && (
                <span className="g-num text-base text-steel">機器ID: {detail.device_id}</span>
              )}
            </div>
            <p className="g-num text-base text-steel">
              記録 #{detail.id}
              {" ・ "}
              {formatDateTime(readingTimestamp(detail))}
              {" ・ "}
              値: <strong className="text-ink">{detail.value ?? "—"}</strong>
              {detail.unit ? ` ${detail.unit}` : ""}
              {detail.confidence !== null ? ` ・ 確からしさ ${(detail.confidence * 100).toFixed(0)}%` : ""}
              {detail.failure_stage ? ` ・ 失敗段階 ${detail.failure_stage}` : ""}
            </p>
          </div>
          <Button type="button" variant="outline" size="field" onClick={onClose}>
            <X aria-hidden />
            閉じる
          </Button>
        </div>

        {detailError && (
          <p className="rounded-md border border-warn bg-warn-tint px-3 py-2 text-base text-text">
            詳細再取得エラー: {detailError}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="表示切り替え">
          {(
            [
              ["both", "並べて表示"],
              ["overlay", "オーバーレイのみ"],
              ["original", "元画像のみ"],
            ] as const
          ).map(([id, text]) => (
            <Button
              key={id}
              type="button"
              size="field"
              variant={mode === id ? "default" : "outline"}
              onClick={() => setMode(id)}
            >
              {text}
            </Button>
          ))}
        </div>

        <div className={mode === "both" ? "grid grid-cols-1 gap-4 md:grid-cols-2" : "grid grid-cols-1 gap-4"}>
          {showOverlay && (
            <figure className="flex flex-col gap-2 rounded-md border border-hairline bg-panel p-3">
              <figcaption className="text-base font-bold text-text">検出結果オーバーレイ</figcaption>
              {overlay.loading ? (
                <p className="py-12 text-center text-base text-steel">画像を読み込み中…</p>
              ) : overlay.error ? (
                <p className="py-12 text-center text-base text-fail">{overlay.error}</p>
              ) : overlay.missing || !overlay.url ? (
                <p className="py-12 text-center text-base text-steel">オーバーレイ画像はありません。</p>
              ) : (
                <img
                  src={overlay.url}
                  alt={`${displayNameOf(detail)} の検出結果オーバーレイ`}
                  data-image-kind="overlay"
                  data-image-loaded={loadedAt.overlay ?? ""}
                  onLoad={() => setLoadedAt((prev) => ({ ...prev, overlay: new Date().toISOString() }))}
                  className="max-h-[58vh] w-full rounded-sm border border-hairline bg-white object-contain"
                />
              )}
            </figure>
          )}

          {showOriginal && (
            <figure className="flex flex-col gap-2 rounded-md border border-hairline bg-panel p-3">
              <figcaption className="text-base font-bold text-text">元画像</figcaption>
              {original.loading ? (
                <p className="py-12 text-center text-base text-steel">画像を読み込み中…</p>
              ) : original.error ? (
                <p className="py-12 text-center text-base text-fail">{original.error}</p>
              ) : original.missing || !original.url ? (
                <p className="py-12 text-center text-base text-steel">元の写真が見つかりません。</p>
              ) : (
                <img
                  src={original.url}
                  alt={`${displayNameOf(detail)} の元画像`}
                  data-image-kind="original"
                  data-image-loaded={loadedAt.original ?? ""}
                  onLoad={() => setLoadedAt((prev) => ({ ...prev, original: new Date().toISOString() }))}
                  className="max-h-[58vh] w-full rounded-sm border border-hairline bg-white object-contain"
                />
              )}
            </figure>
          )}
        </div>
      </div>
    </div>
  );
}
