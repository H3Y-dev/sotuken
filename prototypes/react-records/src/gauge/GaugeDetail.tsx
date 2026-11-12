import { useState } from "react";
import { ArrowLeft, ChevronRight, CirclePlus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Inspection, MeterResult } from "../mock/inspections";
import { SOURCE_LABEL, STAGES, day, formatValue, judge, summarize, time, type Kind } from "./judge";
import { Dial } from "./Dial";
import { KIND, OffRouteBadge, ReceiveBadge, StatusBadge } from "./status";

const who = (m: MeterResult) =>
  `${m.seq ? `No.${m.seq} ` : ""}${m.id || "名前なし"}${m.name ? ` ${m.name}` : ""}`;
const range = (m: MeterResult) =>
  `${formatValue(m.tolerance[0], m.scale[1])}〜${formatValue(m.tolerance[1], m.scale[1])} ${m.unit}`;

const SEVERITY: Kind[] = ["fail", "warn", "missing", "wait", "ok"];

function Stages({ m, kind }: { m: MeterResult; kind: Kind }) {
  return (
    <ol className="grid grid-cols-4 gap-1" aria-label="進み具合">
      {STAGES.map((s, i) => {
        const on = m.stage > i;
        const failed = kind === "fail" && i === 2;
        return (
          <li key={s} className="flex flex-col gap-1">
            <span className="g-seg rounded-sm" data-on={failed ? "fail" : String(on)} />
            <span className={on ? "font-bold text-text" : "text-steel"}>
              {s}
              <span className="sr-only">{failed ? " 失敗" : on ? " 済み" : " まだ"}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function MeterCard({ m }: { m: MeterResult }) {
  const { kind, reasons } = judge(m);
  const hasValue = m.value !== null && (kind === "ok" || kind === "warn");
  const label = `${who(m)}。${KIND[kind].label}${hasValue ? `。読み取り値 ${m.value} ${m.unit}、許容 ${range(m)}` : ""}`;

  return (
    <Card data-kind={kind} className="g-edge gap-4 rounded-lg px-5 py-4 text-base ring-rule/60">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <span className="g-num text-steel">
            {m.seq ? `No.${m.seq}　` : ""}
            {m.id || "機器IDなし"}
          </span>
          <span className="truncate text-lg font-bold">{m.name || "名前なし"}</span>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          <StatusBadge kind={kind} label={kind === "wait" ? reasons[0] : undefined} />
          {m.offRoute && <OffRouteBadge />}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Dial kind={kind} value={m.value} scale={m.scale} tolerance={m.tolerance} label={label} />
        <div className="flex min-w-0 flex-col gap-1">
          {hasValue ? (
            <>
              <span className="flex items-baseline gap-1.5">
                <span className="g-num text-[44px] leading-none font-bold text-ink">{formatValue(m.value!, m.scale[1])}</span>
                <span className="text-lg text-steel">{m.unit}</span>
              </span>
              <span className="text-steel">
                許容 <span className="g-num">{range(m)}</span>
              </span>
            </>
          ) : (
            <span className="text-lg font-bold text-ink">
              {kind === "missing" ? "撮影されていません" : kind === "fail" ? "読み取れませんでした" : `${reasons[0]}です`}
            </span>
          )}
          {kind === "warn" && <span className="font-bold text-warn">{reasons.join("・")}</span>}
        </div>
      </div>

      <Stages m={m} kind={kind} />

      <p className="flex flex-wrap gap-x-4 text-steel">
        <span>出所 {m.sources.length ? m.sources.map((s) => SOURCE_LABEL[s]).join("・") : "なし"}</span>
        <span>撮影 <span className="g-num">{time(m.capturedAt)}</span></span>
        {m.photos > 1 && <span>写真 {m.photos}枚</span>}
      </p>
    </Card>
  );
}

function Attention({ ins }: { ins: Inspection }) {
  const s = summarize(ins);
  const items: { kind: Kind | "tag"; title: string; lines: string[]; todo: string }[] = [];
  if (s.missing.length)
    items.push({ kind: "missing", title: `未撮影 ${s.missing.length}台（撮り忘れ）`, lines: s.missing.map(who), todo: "現場で撮り直すか、撮れなかった理由を残してください。" });
  if (ins.receive === "short")
    items.push({ kind: "warn", title: `PCに未着の写真 ${ins.missingPhotos}枚`, lines: s.wait.filter((m) => m.stage === 1).map(who), todo: "スマホの送信箱を開き、再送してください。" });
  if (s.fail.length)
    items.push({ kind: "fail", title: `失敗 ${s.fail.length}台`, lines: s.fail.map(who), todo: "写真を開いて値を目で読み、手で記録してください。" });
  if (s.warn.length)
    items.push({ kind: "warn", title: `要確認 ${s.warn.length}台`, lines: s.warn.map((m) => `${who(m)} — ${judge(m).reasons.join("・")}`), todo: "写真と見比べて、値が正しいか確かめてください。" });
  if (s.offRoute.length)
    items.push({ kind: "tag", title: `ルート外 ${s.offRoute.length}台`, lines: s.offRoute.map((m) => `${who(m)}（写真${m.photos}枚）`), todo: "ルートに加えるか、今回だけの追加かを決めてください。" });
  if (!items.length) return null;

  return (
    <section aria-label="対処が必要なこと" className="grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] gap-3">
      {items.map((it) => {
        const Icon = it.kind === "tag" ? CirclePlus : KIND[it.kind].Icon;
        return (
          <Alert key={it.title} data-kind={it.kind === "tag" ? "wait" : it.kind} className="g-edge content-start gap-1 rounded-lg px-4 py-3 text-base">
            <Icon aria-hidden className={it.kind === "fail" ? "text-fail" : it.kind === "warn" ? "text-warn" : "text-ink"} />
            <AlertTitle className="text-lg font-bold text-text">{it.title}</AlertTitle>
            <AlertDescription className="text-base text-text">
              <ul>
                {it.lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              <p className="mt-1 text-steel">{it.todo}</p>
            </AlertDescription>
          </Alert>
        );
      })}
    </section>
  );
}

function Pipeline({ ins }: { ins: Inspection }) {
  const s = summarize(ins);
  const steps = [
    { label: "撮影", n: s.captured, of: ins.meters.length },
    { label: "PCに到着", n: s.arrived, of: s.captured },
    { label: "読み取り", n: s.read, of: s.captured },
    { label: "記録", n: s.recorded, of: s.captured },
  ];
  return (
    <ol className="flex flex-wrap items-stretch gap-2" aria-label="点検全体の進み具合（機器の件数）">
      {steps.map((st, i) => (
        <li key={st.label} className="flex items-center gap-2">
          <div className="flex min-w-[150px] flex-col rounded-md border border-rule bg-card px-4 py-2">
            <span className="text-steel">{st.label}</span>
            <span className="g-num text-[28px] leading-tight font-bold text-ink">
              {st.n}
              <span className="text-lg font-normal text-steel">/{st.of}件</span>
            </span>
          </div>
          {i < steps.length - 1 && <ChevronRight aria-hidden className="size-6 text-rule" />}
        </li>
      ))}
    </ol>
  );
}

export function GaugeDetail({ ins }: { ins: Inspection }) {
  const [order, setOrder] = useState("route");
  const s = summarize(ins);
  const sort = (list: MeterResult[]) =>
    order === "route" ? list : [...list].sort((a, b) => SEVERITY.indexOf(judge(a).kind) - SEVERITY.indexOf(judge(b).kind));
  const onRoute = sort(ins.meters.filter((m) => !m.offRoute));
  const extra = sort(ins.meters.filter((m) => m.offRoute));
  const grid = "grid grid-cols-[repeat(auto-fill,minmax(400px,1fr))] gap-4";

  return (
    <section className="flex flex-col gap-6 pt-4">
      <a href="#gauge" className={cn(buttonVariants({ variant: "ghost", size: "field" }), "-ml-4 w-fit text-ink")}>
        <ArrowLeft data-icon="inline-start" aria-hidden />
        点検の一覧へ戻る
      </a>

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <h1 className="text-[28px] leading-tight font-bold">{ins.name}</h1>
          <ReceiveBadge receive={ins.receive} missingPhotos={ins.missingPhotos} arrived={s.arrived} total={s.captured} />
        </div>
        <dl className="flex flex-wrap gap-x-8 gap-y-1">
          {[
            ["点検ID", <span key="id" className="g-num">{ins.id}</span>],
            ["ルート", ins.routeId ? `${ins.routeName}（${s.routeTotal}台）` : "なし"],
            ["担当", ins.operator],
            ["日時", <span key="at" className="g-num">{day(ins.startedAt)} {time(ins.startedAt)}〜{time(ins.completedAt)}</span>],
            ["写真", `${s.photos}枚`],
          ].map(([k, v]) => (
            <div key={k as string} className="flex gap-2">
              <dt className="text-steel">{k}</dt>
              <dd className="font-bold">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      <Pipeline ins={ins} />
      <Attention ins={ins} />

      <div className="flex flex-wrap items-end justify-between gap-4">
        <h2 className="text-xl font-bold">
          {ins.routeId ? `ルートの機器 ${onRoute.length}台` : `撮影した機器 ${onRoute.length}台`}
        </h2>
        <ToggleGroup variant="field" spacing={0} value={[order]} onValueChange={(v) => v[0] && setOrder(v[0] as string)} aria-label="並び順">
          <ToggleGroupItem value="route" className="h-11 px-4 text-base">ルート順</ToggleGroupItem>
          <ToggleGroupItem value="severity" className="h-11 px-4 text-base">要確認を上に</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className={grid}>
        {onRoute.map((m) => (
          <MeterCard key={`${m.seq}-${m.id}`} m={m} />
        ))}
      </div>

      {extra.length > 0 && (
        <>
          <h2 className="text-xl font-bold">ルート外の機器 {extra.length}台</h2>
          <div className={grid}>
            {extra.map((m) => (
              <MeterCard key={m.id} m={m} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
