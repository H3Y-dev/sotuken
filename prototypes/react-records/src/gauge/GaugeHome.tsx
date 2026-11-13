import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { inspections, type Inspection } from "../mock/inspections";
import { day, judge, summarize, time, type Kind } from "./judge";
import { Dial } from "./Dial";
import { KIND, ReceiveBadge } from "./status";

const meterLabel = (m: Inspection["meters"][number], kind: Kind) =>
  `${m.seq ? `No.${m.seq} ` : m.offRoute ? "ルート外 " : ""}${m.id || "名前なし"} ${KIND[kind].label}${m.value !== null && kind !== "fail" ? ` ${m.value}${m.unit ? ` ${m.unit}` : ""}` : ""}${judge(m).outOfTolerance ? " 許容範囲外" : ""}`;

/** 左端の帯。注意枠・詳細の並びと同じ優先順（未撮影→失敗→要確認・対処→途中→正常） */
function rowKind(ins: Inspection): Kind {
  const s = summarize(ins);
  if (s.missing.length) return "missing";
  if (s.fail.length) return "fail";
  if (s.needsAction) return "warn";
  if (ins.receive === "receiving") return "wait";
  return "ok";
}

function Row({ ins }: { ins: Inspection }) {
  const s = summarize(ins);
  const kind = rowKind(ins);
  const route = ins.meters.filter((m) => !m.offRoute);
  const extra = ins.meters.filter((m) => m.offRoute);
  const chips: { kind: Kind | "tag"; text: string }[] = [
    ...(s.outOfTolerance.length ? [{ kind: "warn" as const, text: `許容範囲外 ${s.outOfTolerance.length}` }] : []),
    ...(s.missing.length ? [{ kind: "missing" as const, text: `未撮影 ${s.missing.length}` }] : []),
    ...(s.fail.length ? [{ kind: "fail" as const, text: `失敗 ${s.fail.length}` }] : []),
    ...(s.warn.length ? [{ kind: "warn" as const, text: `要確認 ${s.warn.length}` }] : []),
    ...(s.offRoute.length ? [{ kind: "tag" as const, text: `ルート外 ${s.offRoute.length}` }] : []),
  ];
  const dial = (m: Inspection["meters"][number], idx: number) => {
    const k = judge(m).kind;
    return (
      <li key={`${m.seq ?? "x"}-${m.id}-${idx}`}>
        <Dial mini size={52} kind={k} value={m.value} scale={m.scale} tolerance={m.tolerance} label={meterLabel(m, k)} />
      </li>
    );
  };

  return (
    <li>
      <a href={`#gauge/${encodeURIComponent(ins.id)}`} className="group block rounded-lg no-underline">
        <Card
          data-kind={kind}
          className="g-edge grid grid-cols-[104px_minmax(240px,1fr)_360px_130px_190px_24px] items-center gap-x-6 rounded-lg px-5 py-4 text-base ring-hairline group-hover:ring-ink"
        >
          <div className="flex flex-col">
            <span className="text-steel">{day(ins.startedAt)}</span>
            <span className="g-num text-2xl font-bold text-ink">{time(ins.startedAt)}</span>
          </div>

          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="truncate text-lg font-bold">{ins.name}</span>
            <span className="flex flex-wrap gap-x-4 text-steel">
              <span>{ins.routeId ? `ルート ${ins.routeName}` : "ルートなし"}</span>
              <span>担当 {ins.operator}</span>
            </span>
            {chips.length > 0 && (
              <span className="flex flex-wrap gap-1.5">
                {chips.map((c) => {
                  const Icon = c.kind === "tag" ? null : KIND[c.kind].Icon;
                  return (
                    <Badge key={c.text} variant={c.kind} size="field">
                      {Icon && <Icon aria-hidden />}
                      {c.text}
                    </Badge>
                  );
                })}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <ul className="flex gap-1" aria-label="機器ごとの結果">
              {route.map(dial)}
            </ul>
            {extra.length > 0 && (
              <ul className="flex gap-1 border-l-2 border-dashed border-rule pl-3" aria-label="ルート外の機器">
                {extra.map(dial)}
              </ul>
            )}
          </div>

          <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-3">
            {ins.routeId && (
              <>
                <dt className="text-steel">撮影</dt>
                <dd className="g-num text-xl font-bold text-ink">
                  {s.routeCaptured}/{s.routeTotal}<span className="ml-1 text-base font-normal text-steel">台</span>
                </dd>
              </>
            )}
            <dt className="text-steel">記録</dt>
            <dd className="g-num text-xl font-bold text-ink">
              {ins.routeId ? s.routeRecorded : s.recorded}/{ins.routeId ? s.routeCaptured : s.captured}<span className="ml-1 text-base font-normal text-steel">台</span>
            </dd>
          {ins.routeId && s.offRoute.length > 0 && <><dt className="text-steel">ルート外</dt><dd className="g-num">{s.offRouteRecorded}/{s.offRoute.length}台</dd></>}
          </dl>

          <div>
            <ReceiveBadge ins={ins} />
          </div>

          <ChevronRight aria-hidden className="size-6 text-steel group-hover:text-ink" />
        </Card>
      </a>
    </li>
  );
}

export function GaugeHome() {
  const [filter, setFilter] = useState("all");
  const needs = inspections.filter((i) => summarize(i).needsAction);
  const list = filter === "action" ? needs : inspections;

  return (
    <section className="flex flex-col gap-5 pt-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] leading-tight font-bold">点検の一覧</h1>
          <p className="text-steel">
            新しい順。抜け・要確認がある点検は左端に印が付きます。文字盤は1台ずつの結果です。
          </p>
        </div>
        <ToggleGroup
          variant="field"
          spacing={0}
          value={[filter]}
          onValueChange={(v) => v[0] && setFilter(v[0] as string)}
          aria-label="表示する点検"
        >
          <ToggleGroupItem value="all" className="h-11 px-4 text-base">
            すべて {inspections.length}件
          </ToggleGroupItem>
          <ToggleGroupItem value="action" className="h-11 px-4 text-base">
            対処が必要 {needs.length}件
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <ul className="flex flex-col gap-3">
        {list.map((ins) => (
          <Row key={ins.id} ins={ins} />
        ))}
      </ul>
    </section>
  );
}
