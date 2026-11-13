import { useEffect, useState } from "react";
import { Cog } from "lucide-react";
import "./gauge.css";
import { inspections } from "../mock/inspections";
import { GaugeHome } from "./GaugeHome";
import { GaugeDetail } from "./GaugeDetail";

// 計器盤の見本。#gauge = 点検の一覧、#gauge/<点検ID> = 1件の点検の詳細。
export default function GaugeApp() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  const id = decodeURIComponent(hash.replace(/^#gauge\/?/, ""));
  const ins = inspections.find((i) => i.id === id);
  useEffect(() => {
    document.title = ins ? `${ins.name} | 点検記録` : "点検の一覧 | 点検記録";
    scrollTo(0, 0);
  }, [ins]);

  return (
    <div className="gauge">
      <header className="border-b border-hairline bg-card">
        <div className="mx-auto flex max-w-[1760px] items-center gap-6 px-8 py-3">
          <a href="#gauge" className="flex items-center gap-3 font-bold text-text no-underline">
            <span className="grid size-9 place-items-center rounded-md bg-ink text-white">
              <Cog aria-hidden className="size-6" />
            </span>
            <span className="text-lg">点検記録</span>
          </a>
          <nav aria-label="画面" className="flex gap-1">
            <a href="#gauge" aria-current={id ? undefined : "page"} className="rounded-md px-3 py-1.5 text-text no-underline aria-[current=page]:bg-panel aria-[current=page]:font-bold">
              点検の一覧
            </a>
            <a href="#" className="rounded-md px-3 py-1.5 text-steel no-underline hover:text-text">
              機器の記録（旧試作）
            </a>
          </nav>
          <p className="ml-auto flex items-center gap-2 text-steel">
            <span aria-hidden className="size-3 rounded-full bg-ok" />
            PCの受信口 待ち受け中
            <span className="g-num ml-3">更新 14:52</span>
          </p>
        </div>
        <div className="g-tickrule" aria-hidden />
      </header>
      <main className="mx-auto max-w-[1760px] px-8 pb-16">
        {id && !ins ? (
          <p className="pt-8 text-lg">点検「{id}」は見つかりません。<a href="#gauge" className="text-ink underline">点検の一覧</a>から選んでください。</p>
        ) : ins ? (
          <GaugeDetail key={ins.id} ins={ins} />
        ) : (
          <GaugeHome />
        )}
      </main>
    </div>
  );
}
