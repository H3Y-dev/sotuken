import { afterEach, expect, it, vi } from "vitest";
import { ApiError, downloadInspectionCsv, initSession } from "./client";

afterEach(() => vi.unstubAllGlobals());

it.each([false, true])("posts an empty body with CSRF for save=%s", async (save) => {
  vi.stubGlobal("window", { location: { hash: "", pathname: "/", search: "" } });
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "token" })))
    .mockResolvedValueOnce(save
      ? new Response(JSON.stringify({ filename: "点検.csv" }))
      : new Response("csv-data", { headers: { "Content-Disposition": "attachment; filename*=UTF-8''%E7%82%B9%E6%A4%9C.csv" } }));
  vi.stubGlobal("fetch", fetchMock);
  await initSession();
  const result = await downloadInspectionCsv("a/b", save);
  expect(result.name).toBe("点検.csv");
  if (!save) expect(await result.blob.text()).toBe("csv-data");
  expect(fetchMock).toHaveBeenLastCalledWith(`/api/v1/inspections/a%2Fb/csv${save ? "/save" : ""}`, expect.objectContaining({
    method: "POST", body: "{}", headers: { "X-CSRF-Token": "token", "Content-Type": "application/json" },
  }));
});

it.each([401, 503])("does not retry a failed POST (%s)", async (status) => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "db_busy" } }), { status }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(downloadInspectionCsv("id", true)).rejects.toMatchObject({ status, code: "db_busy" } satisfies Partial<ApiError>);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
