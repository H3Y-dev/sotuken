import { CircleCheck, CircleDashed, Clock, SquareX, TriangleAlert, CirclePlus, Inbox } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Inspection } from "../mock/inspections";
import { summarize, type Kind } from "./judge";

// 状態は「色・文字・形」の3つで示す。形は文字盤の下の印と同じ（● ▲ ■ ◌ ◎）。
export const KIND: Record<Kind, { label: string; Icon: typeof CircleCheck }> = {
  ok: { label: "正常", Icon: CircleCheck },
  warn: { label: "要確認", Icon: TriangleAlert },
  fail: { label: "失敗", Icon: SquareX },
  missing: { label: "未撮影", Icon: CircleDashed },
  wait: { label: "途中", Icon: Clock },
};

export function StatusBadge({ kind, label, outOfTolerance = false, unset = false }: { kind: Kind; label?: string; outOfTolerance?: boolean; unset?: boolean }) {
  const neutral = kind === "ok" && unset;
  const { Icon, label: l } = KIND[outOfTolerance ? "warn" : neutral ? "wait" : kind];
  return (
    <Badge variant={outOfTolerance ? "warn" : neutral ? "tag" : kind} size="field">
      <Icon aria-hidden />
      {outOfTolerance ? "許容範囲外" : neutral ? "読取済" : label ?? l}
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

/**
 * 写真の受信（通信）と、点検の完了は分けて示す。緑の「点検 完了」は、写真が全部届き、
 * 全台が正常のときだけ。届いていても未撮影・失敗・要確認があれば控えめな札にする。
 */
export function ReceiveBadge({ ins }: { ins: Inspection }) {
  const s = summarize(ins);
  if (ins.receive === "short") return <StatusBadge kind="warn" label={`不足あり ${ins.missingPhotos}枚未着`} />;
  if (ins.receive === "receiving") return <StatusBadge kind="wait" label={`受信中 ${s.arrived}/${s.captured}`} />;
  if (s.allOk) return <StatusBadge kind="ok" label="点検 完了" />;
  if (s.missing.length + s.fail.length + s.warn.length === 0) return <StatusBadge kind="wait" label="写真受信済み（処理中）" />;
  return (
    <Badge variant="tag" size="field">
      <Inbox aria-hidden />
      写真受信済み（要対処）
    </Badge>
  );
}
