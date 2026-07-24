import { describe, it, expect, vi, beforeEach } from "vitest";
import { TalosClient, TalosAPIError } from "../src/client.js";
import type { RequestEvent } from "../src/types.js";

function makeOkFetch(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  } as Response);
}

function makeErrorFetch(status: number, text: string) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    text: async () => text,
    json: async () => ({}),
  } as unknown as Response);
}

describe("TelemetryHook", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("receives a RequestEvent on success", async () => {
    vi.stubGlobal("fetch", makeOkFetch({ data: [], nextCursor: null }));
    const events: RequestEvent[] = [];
    const client = new TalosClient({
      baseUrl: "http://test.local",
      onRequest: (e) => events.push(e),
    });

    await client.listTaloses();

    expect(events).toHaveLength(1);
    const ev = events[0];
    expect(ev.method).toBe("GET");
    expect(ev.status).toBe(200);
    expect(ev.durationMs).toBeGreaterThanOrEqual(0);
    expect(ev.correlationId).toMatch(/^[a-z0-9]{8}$/);
    expect(ev.error).toBeUndefined();
  });

  it("receives a RequestEvent with error on API failure", async () => {
    vi.stubGlobal("fetch", makeErrorFetch(404, "not found"));
    const events: RequestEvent[] = [];
    const client = new TalosClient({
      baseUrl: "http://test.local",
      onRequest: (e) => events.push(e),
    });

    await expect(client.getTalos("abc")).rejects.toBeInstanceOf(TalosAPIError);

    expect(events).toHaveLength(1);
    const ev = events[0];
    expect(ev.status).toBe(404);
    expect(ev.error).toBe("not found");
  });

  it("redacts long IDs in path", async () => {
    vi.stubGlobal("fetch", makeOkFetch({}));
    const events: RequestEvent[] = [];
    const client = new TalosClient({
      baseUrl: "http://test.local",
      onRequest: (e) => events.push(e),
    });

    await client.getTalos("clxabcdefghij1234567890");

    expect(events[0].path).toBe("/api/talos/:id");
    expect(events[0].path).not.toContain("clxabcdefghij1234567890");
  });

  it("does not throw if hook throws", async () => {
    vi.stubGlobal("fetch", makeOkFetch({ data: [], nextCursor: null }));
    const client = new TalosClient({
      baseUrl: "http://test.local",
      onRequest: () => { throw new Error("hook exploded"); },
    });

    // Should not throw — hook errors are swallowed
    await expect(client.listTaloses()).resolves.toBeDefined();
  });

  it("works with no hook provided (default no-op)", async () => {
    vi.stubGlobal("fetch", makeOkFetch({ data: [], nextCursor: null }));
    const client = new TalosClient({ baseUrl: "http://test.local" });

    await expect(client.listTaloses()).resolves.toBeDefined();
  });

  it("status is 0 when fetch itself rejects (network error)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failure")));
    const events: RequestEvent[] = [];
    const client = new TalosClient({
      baseUrl: "http://test.local",
      onRequest: (e) => events.push(e),
    });

    await expect(client.listTaloses()).rejects.toThrow("Network failure");

    expect(events).toHaveLength(1);
    expect(events[0].status).toBe(0);
    expect(events[0].error).toBe("Network failure");
  });

  it("correlationId is unique per request", async () => {
    vi.stubGlobal("fetch", makeOkFetch({ data: [], nextCursor: null }));
    const ids: string[] = [];
    const client = new TalosClient({
      baseUrl: "http://test.local",
      onRequest: (e) => ids.push(e.correlationId),
    });

    await client.listTaloses();
    await client.listTaloses();

    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
  });
});
