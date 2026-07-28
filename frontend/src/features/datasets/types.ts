/**
 * Types local to the datasets feature.
 */

import type { DatasetUploadResponse } from "./api";

/** Why an upload that reached the server did not succeed. */
export interface UploadFailure {
  /** Ready to render. See `failures.ts` for how it is chosen. */
  message: string;
  /** The backend's stable error code, when there was one. */
  code: string | null;
  /** Correlation id — show it, so a support request can find the request. */
  requestId: string | null;
}

/**
 * Why a chosen file cannot be uploaded.
 *
 * A discriminated union rather than a message string, because detecting the
 * problem and wording it are different jobs: detection belongs in a pure,
 * testable function, wording belongs next to the UI. Carrying the offending
 * value on each variant lets the message name it ("that file is 340 MB")
 * without re-deriving anything.
 */
export type FileRejection =
  | { code: "multiple-files"; count: number }
  | { code: "unsupported-extension"; filename: string; extension: string }
  | { code: "empty-file"; filename: string }
  | { code: "too-large"; filename: string; size: number };

/**
 * The upload as the UI sees it.
 *
 * Modelled as a union so that "uploading and finished at once", or a progress
 * value with no file attached, cannot be represented — the states are
 * mutually exclusive in the product, so they are mutually exclusive in the
 * type. Four independent booleans would make those combinations merely
 * unlikely rather than impossible.
 *
 * `rejected` and `failed` are separate states because they are different
 * events: `rejected` is this browser refusing to send a file, `failed` is the
 * server refusing one it received. Only the second has a request id, and only
 * the first leaves the dropzone as the thing to retry against.
 *
 * `progress` is nullable because a browser cannot always measure a request
 * body; `null` means "in flight, extent unknown" and renders as an
 * indeterminate bar rather than a dishonest 0%.
 */
export type UploadState =
  | { status: "idle" }
  | { status: "rejected"; rejection: FileRejection }
  | { status: "uploading"; file: File; progress: number | null }
  | { status: "success"; file: File; dataset: DatasetUploadResponse }
  | { status: "failed"; file: File; failure: UploadFailure };
