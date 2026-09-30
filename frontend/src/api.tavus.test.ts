import { afterEach, describe, expect, it, vi } from "vitest";
import { createTavusConversation, listTavusFaces, listTavusPals, persistTavusApiKey } from "./api";

describe("Tavus Face API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves portrait and video preview URLs from the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      faces: [
        {
          face_id: "face-45",
          face_name: "Brooke",
          model_name: "phoenix-4.5",
          status: "completed",
          thumbnail_image_url: "https://cdn.replica.tavus.io/brooke/thumbnail.jpg",
          thumbnail_video_url: "https://cdn.replica.tavus.io/brooke/preview.mp4",
        },
      ],
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await listTavusFaces();

    expect(result.faces).toEqual([{
      face_id: "face-45",
      face_name: "Brooke",
      model_name: "phoenix-4.5",
      status: "completed",
      thumbnail_image_url: "https://cdn.replica.tavus.io/brooke/thumbnail.jpg",
      thumbnail_video_url: "https://cdn.replica.tavus.io/brooke/preview.mp4",
    }]);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/tavus/faces");
  });

  it.each([
    ["pals", listTavusPals],
    ["faces", listTavusFaces],
  ])("expires abandoned %s catalog keys and refetches an expired key", async (kind, list) => {
    const firstKey = `expired-${kind}`;
    const secondKey = `fresh-${kind}`;
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ [kind]: [] }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const now = vi.spyOn(Date, "now");
    try {
      now.mockReturnValue(1000);
      persistTavusApiKey(firstKey);
      await list();
      await list();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      now.mockReturnValue(5 * 60 * 1000 + 1001);
      persistTavusApiKey(secondKey);
      await list();
      persistTavusApiKey(firstKey);
      await list();
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      now.mockRestore();
      persistTavusApiKey("");
    }
  });

  it.each([
    ["pals", listTavusPals],
    ["faces", listTavusFaces],
  ])("bounds the %s catalog cache and evicts the oldest key", async (kind, list) => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ [kind]: [] }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    try {
      const firstKey = `oldest-${kind}`;
      persistTavusApiKey(firstKey);
      await list();
      for (let index = 0; index < 32; index += 1) {
        persistTavusApiKey(`extra-${kind}-${index}`);
        await list();
      }
      expect(fetchMock).toHaveBeenCalledTimes(33);
      persistTavusApiKey(firstKey);
      await list();
      expect(fetchMock).toHaveBeenCalledTimes(34);
    } finally {
      persistTavusApiKey("");
    }
  });

  it("preserves a successful cached response when a later fetch fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ pals: [{ pal_id: "kept", pal_name: "Saved" }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response("unavailable", { status: 502 }));
    vi.stubGlobal("fetch", fetchMock);
    try {
      persistTavusApiKey("cached-on-error");
      expect((await listTavusPals()).pals[0].pal_id).toBe("kept");
      persistTavusApiKey("new-key-on-error");
      await expect(listTavusPals()).rejects.toThrow();
      persistTavusApiKey("cached-on-error");
      expect((await listTavusPals()).pals[0].pal_id).toBe("kept");
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      persistTavusApiKey("");
    }
  });

  it("forwards properties and test mode in the create-conversation body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      conversation_id: "conv-1",
      conversation_url: "https://tavus.daily.co/room",
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await createTavusConversation({
      palId: "pal-1",
      properties: { language: "multilingual" },
      testMode: true,
    });

    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(body).toEqual({
      pal_id: "pal-1",
      properties: { language: "multilingual" },
      test_mode: true,
    });
  });

  it("omits empty properties and live test mode from the body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      conversation_id: "conv-1",
      conversation_url: "https://tavus.daily.co/room",
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await createTavusConversation({ palId: "pal-1", properties: {}, testMode: false });

    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(body).toEqual({ pal_id: "pal-1" });
  });
});
