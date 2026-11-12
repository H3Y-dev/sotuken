import { CircleCheck, CircleDashed, Clock, SquareX, TriangleAlert, CirclePlus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Receive } from "../mock/inspections";
import type { Kind } from "./judge";

// 状態は「色・文字・形」の3つで示す。形は文字盤の下の印と同じ（● ▲ ■ ◌）。
export const KIND: Record<Kind, { label: string; Icon: typeof CircleCheck }> = {
  ok: { label: "正常", Icon: CircleCheck },
  warn: { label: "要確認", Icon: TriangleAlert },
  fail: { label: "失敗", Icon: SquareX },
  missing: { label: "未撮影", Icon: CircleDashed },
  wait: { label: "途中", Icon: Clock },
};

export function StatusBadge({ kind, label }: { kind: Kind; label?: string }) {
  const { Icon, label: l } = KIND[kind];
  return (
    <Badge variant={kind} size="field">
      <Icon aria-hidden />
      {label ?? l}
    </Badge>
  );
}

export function OffRouteBadge() {
  return (
    <Badge variant="tag" size="field">
      <CirclePlus aria-hidden />
      ルート外
    </Badge>
  );
}

export function ReceiveBadge({ receive, missingPhotos, arrived, total }: { receive: Receive; missingPhotos: number; arrived: number; total: number }) {
  if (receive === "complete") return <StatusBadge kind="ok" label="受信 完了" />;
  if (receive === "short") return <StatusBadge kind="warn" label={`不足あり ${missingPhotos}枚未着`} />;
  return <StatusBadge kind="wait" label={`受信中 ${arrived}/${total}`} />;
}
