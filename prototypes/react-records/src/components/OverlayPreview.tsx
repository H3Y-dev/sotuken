import type { Reading } from "../api/types";
import { Button } from "@/components/ui/button";
import { download } from "../lib/download";
export function OverlayPreview({
  selected,
  onClose,
}: {
  selected: Reading;
  onClose: () => void;
}) {
  return (
    <div
      className="overlay"
      role="dialog"
      aria-modal="true"
      aria-label="検出結果オーバーレイ"
      onClick={() => onClose()}
    >
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="section-title">
          <h2>検出結果オーバーレイ</h2>
          <Button variant="outline" onClick={() => onClose()}>
            閉じる
          </Button>
        </div>
        <p>{selected.image} ・ ダミー画像</p>
        <svg viewBox="0 0 300 220" role="img" aria-label="メーターのダミー画像">
          <rect width="300" height="220" fill="#edf0ef" />
          <circle
            cx="150"
            cy="110"
            r="80"
            fill="white"
            stroke="#526270"
            strokeWidth="8"
          />
          <path
            d="M 90 135 A 65 65 0 1 1 210 135"
            fill="none"
            stroke="#2B4A6F"
            strokeWidth="4"
          />
          <path d="M150 110 L190 65" stroke="#b34b3d" strokeWidth="5" />
          <circle cx="150" cy="110" r="7" fill="#263746" />
          <text x="150" y="160" textAnchor="middle" fill="#263746">
            {selected.value ?? "?"}
          </text>
        </svg>
        <Button
          variant="outline"
          onClick={() => {
            const svg = document.querySelector(".modal svg");
            if (svg)
              download(
                selected.image,
                new XMLSerializer().serializeToString(svg),
                "image/svg+xml",
              );
          }}
        >
          原寸画像
        </Button>
      </div>
    </div>
  );
}
