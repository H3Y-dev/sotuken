import { useState } from "react";

export interface TrendPoint {
  id: string;
  label: string;
  value: number;
}

const W = 820;
const H = 260;
const PAD_L = 62;
const PAD_R = 24;
const PAD_T = 20;
const PAD_B = 44;

export function TrendChart({ points }: { points: TrendPoint[] }) {
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  if (!points.length) {
    return (
      <p className="py-8 text-center text-base text-steel">
        数値として読み取れた記録がありません。
      </p>
    );
  }

  const values = points.map((p) => p.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const span = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.2, 1);
  const minV = rawMin - span * 0.1;
  const maxV = rawMax + span * 0.1;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;

  const xAt = (i: number) =>
    points.length === 1 ? PAD_L + innerW / 2 : PAD_L + (i / (points.length - 1)) * innerW;
  const yAt = (v: number) =>
    PAD_T + innerH - ((v - minV) / (maxV - minV || 1)) * innerH;

  const polyline = points.map((p, i) => `${xAt(i).toFixed(1)},${yAt(p.value).toFixed(1)}`).join(" ");
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const val = minV + (maxV - minV) * t;
    return { y: yAt(val), text: val.toFixed(Math.abs(maxV - minV) < 10 ? 2 : 1) };
  });

  const xLabelIndices =
    points.length <= 4
      ? points.map((_, i) => i)
      : [0, Math.floor((points.length - 1) / 2), points.length - 1];

  const active =
    selectedIdx !== null && selectedIdx < points.length ? points[selectedIdx] : points[points.length - 1];
  const activeIdx =
    selectedIdx !== null && selectedIdx < points.length ? selectedIdx : points.length - 1;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-base">
        <span className="text-steel">
          データ点数: <strong className="g-num text-text">{points.length}点</strong>
        </span>
        <span className="text-steel">
          選択中:{" "}
          <strong className="g-num text-ink">
            {active.label} → {active.value}
          </strong>
        </span>
      </div>

      <svg
        role="img"
        aria-label="機器別の読み取り値の推移"
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full max-w-full"
      >
        {/* 水平グリッドとY軸値 */}
        {yTicks.map((t) => (
          <g key={t.y}>
            <line
              x1={PAD_L}
              y1={t.y}
              x2={W - PAD_R}
              y2={t.y}
              stroke="#b4bbbe"
              strokeDasharray="3 3"
              strokeWidth={1}
            />
            <text
              x={PAD_L - 8}
              y={t.y + 4}
              textAnchor="end"
              fill="#475158"
              fontSize={12}
              className="g-num"
            >
              {t.text}
            </text>
          </g>
        ))}

        {/* 軸線 */}
        <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={H - PAD_B} stroke="#757f85" strokeWidth={1.5} />
        <line x1={PAD_L} y1={H - PAD_B} x2={W - PAD_R} y2={H - PAD_B} stroke="#757f85" strokeWidth={1.5} />

        {/* 折れ線 */}
        {points.length > 1 && (
          <polyline
            fill="none"
            stroke="#1d3a63"
            strokeWidth={2.5}
            strokeLinejoin="round"
            strokeLinecap="round"
            points={polyline}
          />
        )}

        {/* X軸代表ラベル */}
        {xLabelIndices.map((idx) => (
          <text
            key={`x-${idx}`}
            x={xAt(idx)}
            y={H - PAD_B + 22}
            textAnchor={idx === 0 ? "start" : idx === points.length - 1 ? "end" : "middle"}
            fill="#475158"
            fontSize={12}
            className="g-num"
          >
            {points[idx].label}
          </text>
        ))}

        {/* クリック・フォーカス可能な点（点が多いときは視認性を保つサイズ） */}
        {points.map((p, i) => {
          const isSel = i === activeIdx;
          return (
            <circle
              key={p.id}
              cx={xAt(i)}
              cy={yAt(p.value)}
              r={isSel ? 5.5 : points.length > 40 ? 2.5 : 4}
              fill={isSel ? "#1d3a63" : "#f8f8f5"}
              stroke="#1d3a63"
              strokeWidth={2}
              className="cursor-pointer"
              onMouseEnter={() => setSelectedIdx(i)}
              onClick={() => setSelectedIdx(i)}
            >
              <title>{`${p.label}: ${p.value}`}</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}
