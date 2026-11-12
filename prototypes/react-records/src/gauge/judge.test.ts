import { describe, it, expect } from "vitest";
import { inspections } from "../mock/inspections";
import { judge, summarize } from "./judge";

const multi = inspections.find((i) => i.id === "I-MULTI-20261112")!;
const kindOf = (id: string) => judge(multi.meters.find((m) => m.id === id)!).kind;

describe("計器盤の判定", () => {
  it("通し試験の形: 撮り忘れ・ルート外・要確認を区別する", () => {
    expect(kindOf("SYN-006")).toBe("missing");
    expect(kindOf("SYN-002")).toBe("warn"); // 許容範囲の外
    expect(kindOf("SYN-004")).toBe("warn"); // 確からしさが低い
    expect(kindOf("SYN-001")).toBe("ok");
    const s = summarize(multi);
    expect(s.routeTotal).toBe(5);
    expect(s.routeCaptured).toBe(4);
    expect(s.offRoute.map((m) => m.id)).toEqual(["SYN-005"]);
    expect(s.photos).toBe(6);
    expect(s.needsAction).toBe(true);
  });

  it("名前なしは値が読めても要確認、読めなければ失敗、途中は待ち", () => {
    const base = multi.meters[0];
    expect(judge({ ...base, id: "" }).kind).toBe("warn");
    expect(judge({ ...base, value: null, status: "failed" }).kind).toBe("fail");
    expect(judge({ ...base, stage: 2 }).kind).toBe("wait");
  });

  it("全部正常で受信も完了なら対処不要", () => {
    const am = inspections.find((i) => i.id === "I-20261111-AM")!;
    expect(summarize(am).needsAction).toBe(false);
  });
});
