/**
 * Turning a failed upload into something a user can act on.
 *
 * Branching happens on `ApiError.code`, never on the message. The backend's
 * codes are a contract (`backend/app/core/exceptions.py`); its messages are
 * written for humans and will be reworded, so matching on them would produce
 * a bug that only appears after a copy edit.
 *
 * The server's own message is preferred where it is more specific than
 * anything we could write — it names the offending row or column — and
 * replaced only where it would be unhelpful or alarming.
 */

import { ApiError, NetworkError } from "@/lib/api/errors";
import type { UploadFailure } from "./types";

/** Shown when nothing more specific is known. */
const GENERIC = "The upload failed. Please try again.";

function failure(message: string, code: string | null, requestId: string | null): UploadFailure {
  return { message, code, requestId };
}

/**
 * Describe why an upload failed.
 *
 * Accepts `unknown` because that is what a `catch` gives you, and because an
 * unexpected throw still has to render as something.
 */
export function describeUploadFailure(error: unknown): UploadFailure {
  if (error instanceof NetworkError) {
    // No response at all: the remedy is the user's connection or a server
    // that is down, not the file they chose.
    return failure(error.message, null, null);
  }

  if (!(error instanceof ApiError)) {
    return failure(GENERIC, null, null);
  }

  const { code, requestId } = error;

  switch (code) {
    case "unsupported_file_type":
    case "payload_too_large":
    case "dataset_parse_failed":
    case "dataset_error":
    case "insufficient_data":
    case "validation_failed":
      // The server knows precisely what was wrong with this file — which row
      // failed to parse, which limit was exceeded. Nothing we could write
      // here would be more useful.
      return failure(error.message, code, requestId);

    case "rate_limited":
      return failure(
        "Too many uploads in a short time. Wait a moment and try again.",
        code,
        requestId,
      );

    case "unauthorized":
    case "forbidden":
      return failure("You are not signed in, or not allowed to upload here.", code, requestId);

    default:
      // A 5xx message can leak internals and rarely helps the user; anything
      // unrecognised is treated the same way.
      return failure(error.status >= 500 ? GENERIC : error.message || GENERIC, code, requestId);
  }
}
