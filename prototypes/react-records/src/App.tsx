import { OverlayPreview } from "@/components/OverlayPreview";
import { download } from "./lib/download";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";
import { Choice } from "@/components/Choice";
import { NumberTicker } from "@/components/ui/number-ticker";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  fetchHistory,
  filterHistory,
  fetchLatest,
  exportCsv,
  exportJsonl,
} from "./api/client";
import type { Reading, Filters } from "./api/types";
const label = (r: Reading) =>
  !r.device
    ? "要確認"
    : r.status === "ok"
      ? "正常"
      : r.status === "failed"
        ? "失敗"
        : "要確認";
const date = (s: string) => new Date(s).toLocaleString("ja-JP");
export default function App() {
  const [rows, setRows] = useState<Reading[]>([]),
    [updated, setUpdated] = useState(""),
    [auto, setAuto] = useState(false),
    [limit, setLimit] = useState(100),
    [selected, setSelected] = useState<Reading | null>(null),
    [trend, setTrend] = useState("メーター 01");
  const [f, setF] = useState<Filters>({
    inspection: "all",
    device: "all",
    start: "",
    end: "",
  });
  const refresh = useCallback(async () => {
    setRows(await fetchHistory());
    setUpdated(new Date().toLocaleTimeString("ja-JP"));
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(() => void refresh(), 5000);
    return () => clearInterval(id);
  }, [auto, refresh]);
  const filtered = useMemo(() => filterHistory(rows, f), [rows, f]),
    latest = useMemo(() => fetchLatest(filtered), [filtered]);
  const history = useMemo(
    () => [...filtered].sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    [filtered],
  );
  const devices = [
      ...new Set(rows.map((r) => r.device).filter(Boolean)),
    ].sort(),
    inspections = [
      ...new Set(rows.map((r) => r.inspection).filter(Boolean)),
    ].sort();
  const set = (key: keyof Filters, value: string) => {
    setF((x) => ({ ...x, [key]: value }));
    setLimit(100);
  };
  const series = filtered
    .filter((r) => r.device === trend && r.value !== null)
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .map((r) => ({ ...r, time: date(r.timestamp) }));
  return (
    <main>
      <header>
        <div>
          <small>READING RECORDS / 記録</small>
          <h1>機器</h1>
          <p>読み取り結果を確認できます</p>
        </div>
        <div className="actions">
          <Button onClick={() => void refresh()}>更新</Button>
          <label>
            <Checkbox
              checked={auto}
              onCheckedChange={(v) => setAuto(v === true)}
            />{" "}
            自動更新(5秒ごと)
          </label>
          <span>更新時刻 {updated || "未更新"}</span>
        </div>
      </header>
      <Card>
        <CardContent>
          <div className="filters">
            <label>
              点検
              <Choice
                value={f.inspection}
                onChange={(v) => set("inspection", v)}
                options={[
                  ["all", "すべて"],
                  ["none", "点検なし(旧データ)"],
                  ...inspections.map((x) => [x, x] as [string, string]),
                ]}
              />
            </label>
            <label>
              機器名
              <Choice
                value={f.device}
                onChange={(v) => set("device", v)}
                options={[
                  ["all", "すべて"],
                  ...devices.map((x) => [x, x] as [string, string]),
                ]}
              />
            </label>
            <label>
              開始日
              <Input
                type="date"
                value={f.start}
                onChange={(e) => set("start", e.target.value)}
              />
            </label>
            <label>
              終了日
              <Input
                type="date"
                value={f.end}
                onChange={(e) => set("end", e.target.value)}
              />
            </label>
          </div>
          <p>
            絞り込み結果 <b>{filtered.length}</b>件 / 全{rows.length}件
          </p>
        </CardContent>
      </Card>
      <section>
        <div className="section-title">
          <div>
            <small>LATEST READINGS</small>
            <h2>各メーターの最新の読み取り</h2>
          </div>
          <Button
            variant="outline"
            onClick={() =>
              download("latest.csv", "\ufeff" + exportCsv(latest), "text/csv")
            }
          >
            点検の結果を書き出す
          </Button>
        </div>
        <Card>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  {["メーター名", "読み取り値", "時刻", "状態"].map((x) => (
                    <TableHead key={x}>{x}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {latest.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{r.device || "名前なし"}</TableCell>
                    <TableCell>{r.value ?? "?"}</TableCell>
                    <TableCell>{date(r.timestamp)}</TableCell>
                    <TableCell>
                      <Badge
                        className={
                          "status " + (r.device ? r.status : "low_confidence")
                        }
                      >
                        {label(r)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p>
              要確認<NumberTicker value={latest.filter((r) => !r.device || r.status === "low_confidence").length} />
              件・失敗<NumberTicker value={latest.filter((r) => r.device && r.status === "failed").length} />
              件・名前なし<NumberTicker value={latest.filter((r) => !r.device).length} />件
            </p>
          </CardContent>
        </Card>
      </section>
      <section>
        <div className="section-title">
          <div>
            <small>ALL RECORDS</small>
            <h2>全履歴</h2>
          </div>
          <div className="actions">
            <Button
              variant="outline"
              onClick={() =>
                download(
                  "history.csv",
                  "\ufeff" + exportCsv(filtered),
                  "text/csv",
                )
              }
            >
              CSVを書き出す
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                download(
                  "history.jsonl",
                  exportJsonl(filtered),
                  "application/x-ndjson",
                )
              }
            >
              JSONLを書き出す
            </Button>
          </div>
        </div>
        <Card>
          <CardContent>
            <Collapsible>
              <CollapsibleTrigger className="history-trigger">
                全履歴を表示 / 折りたたむ
              </CollapsibleTrigger>
              <CollapsibleContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      {[
                        "ID",
                        "時刻",
                        "機器名",
                        "点検",
                        "状態",
                        "読み取り値",
                        "版",
                        "画像",
                      ].map((x) => (
                        <TableHead key={x}>{x}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {history.slice(0, limit).map((r) => (
                      <TableRow
                        key={r.id}
                        onClick={() => setSelected(r)}
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") setSelected(r);
                        }}
                        className="clickable"
                      >
                        <TableCell>{r.id}</TableCell>
                        <TableCell>{date(r.timestamp)}</TableCell>
                        <TableCell>{r.device || "名前なし"}</TableCell>
                        <TableCell>{r.inspection || "点検なし"}</TableCell>
                        <TableCell>{label(r)}</TableCell>
                        <TableCell>{r.value ?? "?"}</TableCell>
                        <TableCell>{r.version}</TableCell>
                        <TableCell>{r.image}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {limit < history.length && (
                  <Button
                    variant="outline"
                    onClick={() => setLimit((x) => x + 100)}
                  >
                    さらに表示
                  </Button>
                )}
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      </section>
      <section>
        <div className="section-title">
          <div>
            <small>TREND</small>
            <h2>機器別の推移</h2>
          </div>
          <Choice
            value={trend}
            onChange={setTrend}
            options={devices.map((x) => [x, x])}
          />
        </div>
        <Card>
          <CardContent>
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" minTickGap={45} tickFormatter={(value: string) => value.replace(/:\d\d$/, "")} />
                  <YAxis />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="value"
                    name="読み取り値"
                    stroke="#2B4A6F"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </section>
      {selected && (
        <OverlayPreview selected={selected} onClose={() => setSelected(null)} />
      )}
    </main>
  );
}
