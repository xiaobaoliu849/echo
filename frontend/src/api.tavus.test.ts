import { afterEach, describe, expect, it, vi } from "vitest";
import { listTavusFaces } from "./api";

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
});
