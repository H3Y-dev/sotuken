import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Download, Image as ImageIcon, RefreshCw, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusBadge, statusKind } from "@/components/StatusBadge";
import { TrendChart } from "@/components/TrendChart";
import type { Filters, Reading } from "@/api/types";
import { download } from "@/lib/download";
import {
  displayNameOf,
  formatDateTime,
  inspectionOptions,
  latestPerDevice,
  readingTimeMs,
  readingTimestamp,
  statusLabelOf,
  toHistoryCsv,
  toJsonl,
  toLatestCsv,
} from "@/lib/records";

const DEFAULT_FILTERS: Filters = {
  inspection: "all",
  device: "all",
  start: "",
  end: "",
};

export function RecordsView({
  rows,
  total,
  knownDevices,
  knownInspections,
  filters,
  onFiltersChange,
  onRefresh,
  loading,
  autoRefresh,
  onAutoRefreshChange,
  updatedAt,
  onSelectReading,
}: {
  rows: Reading[];
  total: number;
  knownDevices: string[];
  knownInspections: { id: string; name: string; count: number }[];
  filters: Filters;
  onFiltersChange: (next: Filters) => void;
  onRefresh: () => void;
  loading: boolean;
  autoRefresh: boolean;
  onAutoRefreshChange: (enabled: boolean) => void;
  updatedAt: string;
  onSelectReading: (r: Reading) => void;
}) {
  const [limit, setLimit] = useState(100);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [trendDevice, setTrendDevice] = useState("");

  const latest = useMemo(() => latestPerDevice(rows), [rows]);
  const currentInspections = useMemo(
    () => (knownInspections.length ? knownInspections : inspectionOptions(rows)),
    [knownInspections, rows],
  );
  const trendOptions = useMemo(() => {
    const names = [...new Set(rows.map((r) => r.device_name).filter(Boolean))].sort();
    return names.length ? names : knownDevices;
  }, [rows, knownDevices]);

  const activeTrendDevice =
    trendDevice && trendOptions.includes(trendDevice) ? trendDevice : (trendOptions[0] ?? "");

  const trendPoints = useMemo(() => {
    if (!activeTrendDevice) return [];
    return rows
      .filter((r) => r.device_name === activeTrendDevice && r.value !== null)
      .sort((a, b) => readingTimeMs(a) - readingTimeMs(b) || Number(a.id) - Number(b.id))
      .map((r) => ({
        id: r.id,
        label: formatDateTime(readingTimestamp(r)),
        value: r.value as number,
      }));
  }, [rows, activeTrendDevice]);

  const warnCount = latest.filter((r) => r.status_label === "要確認").length;
  const failCount = latest.filter((r) => r.status_label === "失敗").length;
  const unnamedCount = latest.filter((r) => r.display_name === "名前なし").length;

  const hasFilter =
    filters.inspection !== "all" ||
    filters.device !== "all" ||
    Boolean(filters.start) ||
    Boolean(filters.end);

  const updateFilter = (patch: Partial<Filters>) => {
    setLimit(100);
    onFiltersChange({ ...filters, ...patch });
  };

  return (
    <div className="flex flex-col gap-6">
      {/* 操作バー */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-text">機器の記録</h2>
          <p className="text-base text-steel">
            各機器の最新値と全履歴、元画像・オーバーレイを確認できます。
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" size="field" onClick={onRefresh} disabled={loading}>
            <RefreshCw aria-hidden />
            {loading ? "読み込み中…" : "更新"}
          </Button>
          <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-rule bg-dial px-3 text-base text-text">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => onAutoRefreshChange(e.target.checked)}
              className="size-5 accent-ink"
            />
            自動更新（5秒ごと）
          </label>
          <span className="g-num text-base text-steel">
            更新時刻 {updatedAt || "未更新"}
          </span>
        </div>
      </div>

      {/* 絞り込み */}
      <Card className="border border-hairline bg-dial shadow-none">
        <CardContent className="flex flex-col gap-4 pt-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="flex flex-col gap-1.5 text-base font-bold text-text">
              点検
              <select
                aria-label="点検"
                value={filters.inspection}
                onChange={(e) => updateFilter({ inspection: e.target.value })}
                className="h-11 rounded-md border border-rule bg-white px-3 text-base font-normal text-text"
              >
                <option value="all">すべて</option>
                <option value="none">点検なし(旧データ)</option>
                {currentInspections.map((ins) => (
                  <option key={ins.id} value={ins.id}>
                    {ins.name}（{ins.count}件）
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-base font-bold text-text">
              機器名
              <select
                aria-label="機器名"
                value={filters.device}
                onChange={(e) => updateFilter({ device: e.target.value })}
                className="h-11 rounded-md border border-rule bg-white px-3 text-base font-normal text-text"
              >
                <option value="all">すべて</option>
                {knownDevices.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-base font-bold text-text">
              開始日
              <Input
                aria-label="開始日"
                type="date"
                value={filters.start}
                onChange={(e) => updateFilter({ start: e.target.value })}
                className="g-num h-11 border-rule bg-white text-base"
              />
            </label>

            <label className="flex flex-col gap-1.5 text-base font-bold text-text">
              終了日
              <Input
                aria-label="終了日"
                type="date"
                value={filters.end}
                onChange={(e) => updateFilter({ end: e.target.value })}
                className="g-num h-11 border-rule bg-white text-base"
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="g-num text-base text-steel">
              絞り込み結果 <strong className="text-ink">{total}件</strong>
            </p>
            {hasFilter && (
              <Button
                type="button"
                variant="outline"
                size="field"
                onClick={() => {
                  setLimit(100);
                  onFiltersChange(DEFAULT_FILTERS);
                }}
              >
                <RotateCcw aria-hidden />
                絞り込みを解除
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* 各メーターの最新の読み取り */}
      <section className="flex flex-col gap-3" aria-labelledby="heading-latest">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 id="heading-latest" className="text-xl font-bold text-text">
              各メーターの最新の読み取り
            </h3>
            <p className="g-num text-base text-steel">
              要確認 {warnCount}件・失敗 {failCount}件・名前なし {unnamedCount}件
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="field"
            disabled={!latest.length}
            onClick={() =>
              download("latest.csv", `\ufeff${toLatestCsv(latest)}`, "text/csv;charset=utf-8")
            }
          >
            <Download aria-hidden />
            点検の結果を書き出す
          </Button>
        </div>

        <Card className="border border-hairline bg-dial shadow-none">
          <CardContent className="p-0">
            {latest.length === 0 ? (
              <p className="px-5 py-8 text-base text-steel">表示できる記録がありません。</p>
            ) : (
              <div className="overflow-x-auto">
                <Table className="text-base">
                  <TableHeader>
                    <TableRow className="border-hairline hover:bg-transparent">
                      <TableHead className="px-4 py-3 text-base font-bold text-steel">メーター名</TableHead>
                      <TableHead className="px-4 py-3 text-base font-bold text-steel">読み取り値</TableHead>
                      <TableHead className="px-4 py-3 text-base font-bold text-steel">撮影・取込時刻</TableHead>
                      <TableHead className="px-4 py-3 text-base font-bold text-steel">状態</TableHead>
                      <TableHead className="px-4 py-3 text-base font-bold text-steel">画像確認</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {latest.map((r) => (
                      <TableRow
                        key={r.id}
                        data-reading-id={r.id}
                        data-kind={statusKind(r.status_label)}
                        className="cursor-pointer border-hairline hover:bg-panel/40"
                        onClick={() => onSelectReading(r)}
                      >
                        <TableCell className="g-edge-cell px-4 py-3 font-bold text-text">
                          {r.display_name}
                        </TableCell>
                        <TableCell className="g-num px-4 py-3 text-lg font-bold text-ink">
                          {r.value ?? "?"}
                          {r.unit ? <span className="ml-1 text-base font-normal text-steel">{r.unit}</span> : null}
                        </TableCell>
                        <TableCell className="g-num px-4 py-3 text-steel">
                          {formatDateTime(readingTimestamp(r))}
                        </TableCell>
                        <TableCell className="px-4 py-3">
                          <StatusBadge label={r.status_label} />
                        </TableCell>
                        <TableCell className="px-4 py-3">
                          <Button
                            type="button"
                            variant="outline"
                            size="field"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectReading(r);
                            }}
                          >
                            <ImageIcon aria-hidden />
                            {r.overlay_image_id || r.image_id ? "画像を見る" : "詳細"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {/* 全履歴 */}
      <section className="flex flex-col gap-3" aria-labelledby="heading-history">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h3 id="heading-history" className="text-xl font-bold text-text">
              全履歴（<span className="g-num">{rows.length}件</span>）
            </h3>
            <Button
              type="button"
              variant="outline"
              size="field"
              aria-expanded={historyOpen}
              onClick={() => setHistoryOpen((v) => !v)}
            >
              {historyOpen ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
              {historyOpen ? "全履歴を折りたたむ" : "全履歴を表示"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="field"
              disabled={!rows.length}
              onClick={() =>
                download("history.csv", `\ufeff${toHistoryCsv(rows)}`, "text/csv;charset=utf-8")
              }
            >
              <Download aria-hidden />
              CSVを書き出す
            </Button>
            <Button
              type="button"
              variant="outline"
              size="field"
              disabled={!rows.length}
              onClick={() =>
                download("history.jsonl", toJsonl(rows), "application/x-ndjson;charset=utf-8")
              }
            >
              <Download aria-hidden />
              JSONLを書き出す
            </Button>
          </div>
        </div>

        {historyOpen && (
          <Card className="border border-hairline bg-dial shadow-none">
            <CardContent className="flex flex-col gap-3 p-0">
              {rows.length === 0 ? (
                <p className="px-5 py-8 text-base text-steel">該当する履歴がありません。</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table className="text-base">
                    <TableHeader>
                      <TableRow className="border-hairline hover:bg-transparent">
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">ID</TableHead>
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">時刻</TableHead>
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">機器名</TableHead>
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">点検</TableHead>
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">状態</TableHead>
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">読み取り値</TableHead>
                        <TableHead className="px-4 py-3 text-base font-bold text-steel">写真</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.slice(0, limit).map((r) => {
                        const sLabel = statusLabelOf(r);
                        return (
                          <TableRow
                            key={r.id}
                            data-history-id={r.id}
                            data-kind={statusKind(sLabel)}
                            className="cursor-pointer border-hairline hover:bg-panel/40"
                            onClick={() => onSelectReading(r)}
                          >
                            <TableCell className="g-edge-cell g-num px-4 py-3 text-steel">#{r.id}</TableCell>
                            <TableCell className="g-num px-4 py-3 text-steel">
                              {formatDateTime(readingTimestamp(r))}
                            </TableCell>
                            <TableCell className="px-4 py-3 font-bold text-text">
                              {displayNameOf(r)}
                            </TableCell>
                            <TableCell className="px-4 py-3 text-steel">
                              {r.inspection_name || r.inspection_id || "点検なし"}
                            </TableCell>
                            <TableCell className="px-4 py-3">
                              <StatusBadge label={sLabel} />
                            </TableCell>
                            <TableCell className="g-num px-4 py-3 font-bold text-ink">
                              {r.value ?? "?"}
                            </TableCell>
                            <TableCell className="px-4 py-3">
                              <Button
                                type="button"
                                variant="outline"
                                size="field"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onSelectReading(r);
                                }}
                              >
                                <ImageIcon aria-hidden />
                                {r.overlay_image_id
                                  ? "オーバーレイ"
                                  : r.image_id
                                    ? "元画像"
                                    : "詳細"}
                              </Button>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}

              {limit < rows.length && (
                <div className="px-4 pb-4">
                  <Button
                    type="button"
                    variant="outline"
                    size="field"
                    onClick={() => setLimit((n) => n + 100)}
                  >
                    さらに表示（残り <span className="g-num">{rows.length - limit}件</span>）
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </section>

      {/* 機器別の推移 */}
      <section className="flex flex-col gap-3" aria-labelledby="heading-trend">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="heading-trend" className="text-xl font-bold text-text">
            機器別の推移
          </h3>
          <label className="flex items-center gap-2 text-base font-bold text-text">
            対象機器
            <select
              aria-label="推移の対象機器"
              value={activeTrendDevice}
              onChange={(e) => setTrendDevice(e.target.value)}
              className="h-11 rounded-md border border-rule bg-white px-3 text-base font-normal text-text"
            >
              {trendOptions.length === 0 && <option value="">記録なし</option>}
              {trendOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <Card className="border border-hairline bg-dial shadow-none">
          <CardContent className="pt-5">
            <TrendChart points={trendPoints} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
