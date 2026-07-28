/**
 * The datasets feature's entire network surface.
 *
 * Components call hooks, hooks call this, and this calls the shared client —
 * so there is exactly one place to look when the contract changes, and
 * exactly one place a request header or a base URL can come from.
 */

import { apiUpload, type UploadProgress } from "@/lib/api/client";
import type { components } from "@/types/api.generated";

/**
 * Generated from the backend's OpenAPI document by `make types`.
 *
 * Aliased rather than re-declared: a hand-written copy would keep compiling
 * after the Pydantic model changed, and the drift would surface as a blank
 * field in the UI rather than a type error.
 */
export type DatasetUploadResponse = components["schemas"]["DatasetUploadResponse"];

const UPLOAD_PATH = "/api/v1/datasets/upload";

/**
 * The multipart field name the endpoint expects.
 *
 * Must match the `file` parameter of `upload_dataset` in
 * `backend/app/api/v1/routes/datasets.py`. Getting it wrong produces a 422
 * from FastAPI's own validation, before any of our code runs.
 */
const FILE_FIELD = "file";

export interface UploadDatasetOptions {
  onProgress?: (progress: UploadProgress) => void;
  signal?: AbortSignal;
}

/** Upload one dataset and return its measured size and shape. */
export function uploadDataset(
  file: File,
  options: UploadDatasetOptions = {},
): Promise<DatasetUploadResponse> {
  const body = new FormData();
  body.append(FILE_FIELD, file);

  return apiUpload<DatasetUploadResponse>(UPLOAD_PATH, {
    body,
    onProgress: options.onProgress,
    signal: options.signal,
  });
}
