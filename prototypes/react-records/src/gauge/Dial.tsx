import { useId } from "react";
import { validRange, validTolerance, type Kind } from "./judge";

// 文字盤の絵。仕様は DESIGN.md の「文字盤の絵」。
// 240°の目盛り、許容範囲の帯、読み取り値の針。下の切れ目に状態の形（● ▲ ■ ◌ ◎）を置く。
// 目盛りの範囲・許容範囲は任意項目。未設定・不正なら針・帯を描かず、仮の範囲で補わない。

const CX = 60, CY = 60, SWEEP = 240;
const ang = (t: number) => ((-SWEEP / 2 + SWEEP * t) * Math.PI) / 180;
const pt = (r: number, t: number) => [CX + r * Math.sin(ang(t)), CY - r * Math.cos(ang(t))] as const;
const arc = (r: number, t0: number, t1: number) => {
  const [x0, y0] = pt(r, t0), [x1, y1] = pt(r, t1);
  return `M${x0} ${y0}A${r} ${r} 0 ${(t1 - t0) * SWEEP > 180 ? 1 : 0} 1 ${x1} ${y1}`;
};
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function StateMark({ kind, x, y, s }: { kind: Kind; x: number; y: number; s: number }) {
  if (kind === "ok") return <circle cx={x} cy={y} r={s * 0.5} fill="var(--g-ok)" />;
  if (kind === "warn")
    return <path d={`M${x} ${y - s * 0.6}L${x + s * 0.62} ${y + s * 0.45}H${x - s * 0.62}Z`} fill="var(--g-warn)" />;
  if (kind === "fail") return <rect x={x - s * 0.45} y={y - s * 0.45} width={s * 0.9} height={s * 0.9} fill="var(--g-fail)" />;
  if (kind === "missing")
    return <circle cx={x} cy={y} r={s * 0.45} fill="none" stroke="var(--g-ink)" strokeWidth={2.5} strokeDasharray="3 2.5" />;
  // 途中: 鋼色の二重丸（◎）。塗りの丸（正常）・破線の丸（未撮影）と形で分かれる
  return (
    <g fill="none" stroke="var(--g-steel)">
      <circle cx={x} cy={y} r={s * 0.42} strokeWidth={s * 0.12} />
      <circle cx={x} cy={y} r={s * 0.14} fill="var(--g-steel)" strokeWidth={0} />
    </g>
  );
}

export function Dial({
  kind,
  value,
  scale,
  tolerance,
  size = 148,
  mini = false,
  label,
}: {
  kind: Kind;
  value: number | null;
  scale: [number, number] | null;
  tolerance: [number, number] | null;
  size?: number;
  mini?: boolean;
  label: string;
}) {
  const hatch = useId();
  const range = validRange(scale) ? scale : null;
  const norm = (v: number) => (range ? (v - range[0]) / (range[1] - range[0]) : 0);
  const drawn = kind !== "missing" && kind !== "fail";
  const showNeedle = drawn && range !== null && value !== null;
  // 振り切れは、本物の計器と同じく端を少し越えた所で止める
  const t = showNeedle ? clamp(norm(value), -0.04, 1.04) : 0;
  const band =
    kind !== "missing" && range && validTolerance(tolerance)
      ? [clamp(norm(tolerance[0]), 0, 1), clamp(norm(tolerance[1]), 0, 1)]
      : null;
  const out = kind === "ok" && value !== null && validTolerance(tolerance) && (value < tolerance[0] || value > tolerance[1]);
  const mark = out ? "warn" : kind === "ok" && !validTolerance(tolerance) ? "wait" : kind;
  const ticks = mini && kind === "missing" ? 0 : mini ? 6 : 31;
  const major = mini ? 1 : 5;
  const center =
    kind === "missing" ? "未撮影" : kind === "fail" ? "読めず" : kind === "wait" && value === null ? "待ち" : !range ? "目盛り未設定" : null;

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox="0 0 120 112"
      width={size}
      height={(size * 112) / 120}
      className="g-dial shrink-0"
      data-kind={kind}
    >
      {kind === "fail" && (
        <defs>
          <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--g-fail)" strokeWidth="1.6" opacity=".45" />
          </pattern>
        </defs>
      )}
      <circle
        cx={CX}
        cy={CY}
        r={57}
        fill="var(--g-dial)"
        stroke={kind === "missing" ? "var(--g-ink)" : "var(--g-rule)"}
        strokeWidth={kind === "missing" ? (mini ? 3.5 : 2.5) : 1.5}
        strokeDasharray={kind === "missing" ? (mini ? "5 4" : "6 5") : undefined}
      />
      {kind === "fail" && <circle cx={CX} cy={CY} r={55} fill={`url(#${hatch})`} />}

      {band && band[1] > band[0] && (
        <path d={arc(43, band[0], band[1])} fill="none" stroke="var(--g-band)" strokeWidth={mini ? 12 : 8} />
      )}

      {/* 目盛りの範囲が無いときは目盛りを罫の色に落とし、値を表さない絵だと分かるようにする */}
      <g stroke={kind === "missing" || !range ? "var(--g-rule)" : "var(--g-ink)"} strokeLinecap="butt">
        {Array.from({ length: ticks }, (_, i) => {
          const tt = i / (ticks - 1);
          const isMajor = i % major === 0;
          const [x0, y0] = pt(isMajor ? (mini ? 44 : 47) : 51, tt);
          const [x1, y1] = pt(55, tt);
          return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} strokeWidth={isMajor ? (mini ? 4 : 2.2) : 1.2} />;
        })}
      </g>

      {/* 両端の数字は、目盛りの外側の下の切れ目に置き、目盛り・中心と重ねない */}
      {!mini && showNeedle && range && (
        <g fill="var(--g-steel)" fontSize="12" fontFamily="var(--g-font-num)" textAnchor="middle">
          <text x={pt(38, -0.04)[0]} y={pt(38, -0.04)[1] + 4}>{range[0]}</text>
          <text x={pt(38, 1.04)[0]} y={pt(38, 1.04)[1] + 4}>{range[1]}</text>
        </g>
      )}

      {showNeedle && (
        <g className="g-needle" style={{ transform: `rotate(${-SWEEP / 2 + SWEEP * t}deg)` }}>
          {/* 帯と重なっても見えるよう、針に文字盤色の縁を付ける */}
          <line x1={CX} y1={CY + 8} x2={CX} y2={CY - 51} stroke="var(--g-dial)" strokeWidth={mini ? 9 : 6} strokeLinecap="round" />
          <line x1={CX} y1={CY + 8} x2={CX} y2={CY - 51} stroke="var(--g-ink)" strokeWidth={mini ? 5.5 : 3} strokeLinecap="round" />
        </g>
      )}
      {kind !== "missing" && (
        <>
          <circle cx={CX} cy={CY} r={mini ? 8 : 5.5} fill={showNeedle ? "var(--g-ink)" : "var(--g-dial)"} stroke="var(--g-ink)" strokeWidth={2} />
          {showNeedle && <circle cx={CX} cy={CY} r={mini ? 2.5 : 1.8} fill="var(--g-dial)" />}
        </>
      )}

      {!mini && center && (
        <text
          x={CX}
          y={kind === "missing" ? 66 : 84}
          textAnchor="middle"
          fontSize={center.length > 3 ? 12 : 15}
          fontWeight="700"
          fontFamily="var(--g-font-text)"
          fill={kind === "fail" ? "var(--g-fail)" : center.length > 3 ? "var(--g-steel)" : "var(--g-ink)"}
        >
          {center}
        </text>
      )}
      <StateMark kind={mark} x={CX} y={mini ? 97 : 99} s={mini ? 30 : 15} />
    </svg>
  );
}
