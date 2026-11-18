import { useMemo } from "react";
import QRCode from "qrcode";

/**
 * CSP (default-src 'self'; img-src 'self' blob:) 下でも動作するよう、
 * インライン style 属性や data: URL を使わず単一 SVG path で描画する。
 */
export function QrCodeSvg({ payload }: { payload: string }) {
  const qr = useMemo(() => {
    const model = QRCode.create(payload, { errorCorrectionLevel: "M" });
    const size = model.modules.size;
    const data = model.modules.data;
    const parts: string[] = [];
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        if (data[y * size + x]) {
          parts.push(`M${x},${y}h1v1h-1z`);
        }
      }
    }
    const quiet = 4;
    return {
      total: size + quiet * 2,
      quiet,
      path: parts.join(""),
    };
  }, [payload]);

  return (
    <svg
      role="img"
      aria-label="スマホの送信先登録用QRコード"
      viewBox={`0 0 ${qr.total} ${qr.total}`}
      width={240}
      height={240}
      className="h-60 w-60 rounded-md border border-hairline bg-white"
    >
      <rect width={qr.total} height={qr.total} fill="#ffffff" />
      <g transform={`translate(${qr.quiet}, ${qr.quiet})`}>
        <path d={qr.path} fill="#1c2226" />
      </g>
    </svg>
  );
}
