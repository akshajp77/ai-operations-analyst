import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "@/lib/api/errors";
import { describeUploadFailure } from "./failures";

function apiError(status: number, code: string, message = "Something went wrong."): ApiError {
  return new ApiError(status, { code, message, details: {}, request_id: "req-123" });
}

describe("describeUploadFailure", () => {
  it("keeps the server's explanation when it names the actual problem", () => {
    // The backend knows which row failed; no wording we invent beats that.
    const failure = describeUploadFailure(
      apiError(422, "dataset_parse_failed", "Row 42 could not be parsed as a date."),
    );

    expect(failure.message).toBe("Row 42 could not be parsed as a date.");
    expect(failure.code).toBe("dataset_parse_failed");
  });

  it.each([
    ["unsupported_file_type", 415],
    ["payload_too_large", 413],
    ["dataset_error", 422],
    ["insufficient_data", 422],
    ["validation_failed", 422],
  ])("passes through the server's message for %s", (code, status) => {
    expect(describeUploadFailure(apiError(status, code, "Precise reason.")).message).toBe(
      "Precise reason.",
    );
  });

  it("carries the correlation id so support can find the request", () => {
    expect(describeUploadFailure(apiError(413, "payload_too_large")).requestId).toBe("req-123");
  });

  it("rewrites a rate limit into an instruction the user can follow", () => {
    const failure = describeUploadFailure(apiError(429, "rate_limited", "Rate limit exceeded."));

    expect(failure.message).toMatch(/wait a moment/i);
  });

  it.each(["unauthorized", "forbidden"])("explains an access failure for %s", (code) => {
    expect(describeUploadFailure(apiError(403, code)).message).toMatch(
      /not signed in|not allowed/i,
    );
  });

  it("hides a server error's message rather than leaking internals", () => {
    const failure = describeUploadFailure(
      apiError(500, "app_error", "psycopg.OperationalError: connection refused"),
    );

    expect(failure.message).not.toMatch(/psycopg/);
    expect(failure.message).toMatch(/try again/i);
  });

  it("blames the connection, not the file, when no response arrived", () => {
    const failure = describeUploadFailure(new NetworkError(new Error("offline")));

    expect(failure.message).toMatch(/connection/i);
    expect(failure.code).toBeNull();
  });

  it("still says something useful for a throw it does not recognise", () => {
    expect(describeUploadFailure(new TypeError("undefined is not a function")).message).toMatch(
      /try again/i,
    );
  });
});
