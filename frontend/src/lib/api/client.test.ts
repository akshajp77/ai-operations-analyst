/**
 * Tests for the HTTP client.
 *
 * Worth covering carefully: every network call in the product flows through
 * this module, so a bug here is a bug in every feature at once.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NetworkError } from "@/lib/api/errors";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed body on success", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "ok" }));

    await expect(apiFetch<{ status: string }>("/health/live")).resolves.toEqual({
      status: "ok",
    });
  });

  it("attaches a correlation id to every request", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}));

    await apiFetch("/health/live");

    const headers = vi.mocked(fetch).mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-Request-ID"]).toBeTruthy();
  });

  it("drops null and undefined query parameters", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}));

    await apiFetch("/datasets", { query: { page: 2, search: null, tag: undefined } });

    const url = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(url).toContain("page=2");
    expect(url).not.toContain("search");
    expect(url).not.toContain("tag");
  });

  it("does not set Content-Type for FormData", async () => {
    // The browser must set it itself, including the multipart boundary;
    // overriding it makes the server unable to parse the upload.
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}));

    await apiFetch("/datasets", { method: "POST", body: new FormData() });

    const headers = vi.mocked(fetch).mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("returns undefined for a 204 rather than failing to parse an empty body", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiFetch("/datasets/abc")).resolves.toBeUndefined();
  });

  describe("error handling", () => {
    it("throws ApiError carrying the backend's code and request id", async () => {
      vi.mocked(fetch).mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: "dataset_not_found",
              message: "Dataset 'ds_1' was not found.",
              details: { dataset_id: "ds_1" },
              request_id: "req-123",
            },
          },
          404,
        ),
      );

      const error = await apiFetch("/datasets/ds_1").catch((e: unknown) => e);

      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).code).toBe("dataset_not_found");
      expect((error as ApiError).requestId).toBe("req-123");
      expect((error as ApiError).isRetryable).toBe(false);
    });

    it("survives a non-JSON error body", async () => {
      // A proxy timeout or WAF block returns HTML. The status code must still
      // reach the caller instead of being masked by a JSON parse failure.
      vi.mocked(fetch).mockResolvedValue(
        new Response("<html>502 Bad Gateway</html>", { status: 502 }),
      );

      const error = (await apiFetch("/datasets").catch((e: unknown) => e)) as ApiError;

      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(502);
      expect(error.code).toBe("unexpected_response");
      expect(error.isRetryable).toBe(true);
    });

    it("throws NetworkError when no response arrives", async () => {
      vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

      await expect(apiFetch("/datasets")).rejects.toBeInstanceOf(NetworkError);
    });

    it("exposes field errors from a 422", async () => {
      vi.mocked(fetch).mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: "validation_failed",
              message: "The request payload failed validation.",
              details: { fields: [{ field: "name", message: "required", type: "missing" }] },
              request_id: "req-9",
            },
          },
          422,
        ),
      );

      const error = (await apiFetch("/datasets").catch((e: unknown) => e)) as ApiError;

      expect(error.fieldErrors).toHaveLength(1);
      expect(error.fieldErrors[0].field).toBe("name");
    });
  });
});
