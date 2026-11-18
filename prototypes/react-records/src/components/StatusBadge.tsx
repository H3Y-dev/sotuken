import { CircleCheck, SquareX, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { StatusLabel } from "@/lib/records";

export function statusKind(label: StatusLabel): "ok" | "warn" | "fail" {
  if (label === "失敗") return "fail";
  if (label === "要確認") return "warn";
  return "ok";
}

export function StatusBadge({ label }: { label: StatusLabel }) {
  const kind = statusKind(label);
  const Icon =
    kind === "fail" ? SquareX : kind === "warn" ? TriangleAlert : CircleCheck;
  return (
    <Badge variant={kind} size="field">
      <Icon aria-hidden />
      {label}
    </Badge>
  );
}
