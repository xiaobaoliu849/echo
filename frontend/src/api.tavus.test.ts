import { afterEach, describe, expect, it, vi } from "vitest";
import { createTavusConversation, listTavusFaces } from "./api";

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
