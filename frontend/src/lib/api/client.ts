/**
 * The single HTTP client for talking to the backend.
 *
 * Every network call in the application goes through `apiFetch`. That is the
 * whole point: base URL resolution, correlation ids, timeouts, error
 * normalisation, and credential handling are decided once, not re-implemented
 * (slightly differently) at forty call sites.
 *
 * Built on the platform `fetch` rather than axios. Next.js extends `fetch`
 * with its caching and revalidation semantics, so using anything else means
 * opting out of the framework's data layer.
 */
import { apiBaseUrl } from "@/lib/env";
import { ApiError, type ApiErrorBody, NetworkError } from "@/lib/api/errors";

/** Header name shared with the backend; see `app/core/correlation.py`. */
const REQUEST_ID_HEADER = "X-Request-ID";

const DEFAULT_TIMEOUT_MS = 30_000;

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  /** Serialised as JSON unless it is FormData, which the browser must frame itself. */
  body?: unknown;
  /** Appended as a query string; null/undefined entries are dropped. */
  query?: Record<string, string | number | boolean | null | undefined>;
  /** Abort after this many milliseconds. */
  timeoutMs?: number;
}

function buildUrl(path: string, query?: ApiFetchOptions["query"]): string {
  const url = new URL(path.startsWith("/") ? path : `/${path}`, apiBaseUrl());
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/**
 * Generate a correlation id on the client.
 *
 * Sending it rather than letting the server invent one means a browser-side
 * error report and the server log share an identifier, so a support ticket
 * containing the id is enough to find the exact request.
 */
function newRequestId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

/**
 * Perform a request and return the parsed body.
 *
 * @throws {ApiError} The server responded with a non-2xx status.
 * @throws {NetworkError} No response was received at all.
 */
export async function apiFetch<TResponse>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<TResponse> {
  const { body, query, timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...init } = options;

  const isFormData = body instanceof FormData;
  const requestId = newRequestId();

  // Every request is bounded. Without a timeout a hung connection leaves a
  // spinner on screen indefinitely, which users read as "the app is broken".
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  // Honour a caller-supplied signal as well as our own timeout.
  if (init.signal) {
    init.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      ...init,
      signal: controller.signal,
      // Send cookies so session auth works without the caller remembering to.
      credentials: init.credentials ?? "include",
      headers: {
        Accept: "application/json",
        // Setting Content-Type on FormData would omit the multipart boundary
        // and the server would fail to parse the upload.
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        [REQUEST_ID_HEADER]: requestId,
        ...headers,
      },
      body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    throw new NetworkError(cause);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorBody(response, requestId));
  }

  // 204 and 205 carry no body; calling .json() on them throws.
  if (response.status === 204 || response.status === 205) {
    return undefined as TResponse;
  }

  return (await response.json()) as TResponse;
}

/**
 * What to report when the body tells us nothing useful.
 *
 * A proxy timeout or a WAF block returns HTML, not JSON. Without this
 * fallback the parse failure would mask the real status code with an opaque
 * "Unexpected token <" error.
 */
function fallbackErrorBody(status: number, requestId: string): ApiErrorBody {
  return {
    code: "unexpected_response",
    message: `Request failed with status ${status}.`,
    details: {},
    request_id: requestId,
  };
}

/** Unwrap the backend's `{ error: … }` envelope, or fall back. */
function coerceErrorBody(parsed: unknown, status: number, requestId: string): ApiErrorBody {
  const envelope = parsed as { error?: Partial<ApiErrorBody> } | null;
  if (envelope?.error?.code) {
    return { ...fallbackErrorBody(status, requestId), ...envelope.error } as ApiErrorBody;
  }
  return fallbackErrorBody(status, requestId);
}

async function readErrorBody(response: Response, requestId: string): Promise<ApiErrorBody> {
  const correlationId = response.headers.get(REQUEST_ID_HEADER) ?? requestId;
  try {
    return coerceErrorBody(await response.json(), response.status, correlationId);
  } catch {
    // Body was empty or not JSON; the fallback is the honest answer.
    return fallbackErrorBody(response.status, correlationId);
  }
}

function parseErrorBody(text: string, status: number, requestId: string): ApiErrorBody {
  try {
    return coerceErrorBody(JSON.parse(text) as unknown, status, requestId);
  } catch {
    return fallbackErrorBody(status, requestId);
  }
}

/** How far along an upload is. `null` when the browser cannot measure it. */
export interface UploadProgress {
  loaded: number;
  total: number | null;
  percent: number | null;
}

export interface ApiUploadOptions {
  /** Always FormData — this path exists for file transfers. */
  body: FormData;
  method?: string;
  onProgress?: (progress: UploadProgress) => void;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/**
 * An upload is not bounded the way a JSON call is.
 *
 * `apiFetch`'s 30 seconds is right for a request whose duration says
 * something about server health. A 200 MB file on a slow connection is not a
 * hung server, so the ceiling here is generous enough to be a genuine
 * backstop rather than a cap on large but healthy uploads.
 */
const UPLOAD_TIMEOUT_MS = 10 * 60_000;

/**
 * Send a file and report progress while it uploads.
 *
 * Built on `XMLHttpRequest` rather than `fetch`, and that is the entire
 * reason this function exists alongside `apiFetch`: `fetch` still has no way
 * to observe request-body progress, so a fetch-based upload could only show a
 * spinner. Everything else — base URL, correlation id, credentials, and the
 * error envelope — is shared, so callers get the same `ApiError` they would
 * from any other endpoint.
 *
 * @throws {ApiError} The server responded with a non-2xx status.
 * @throws {NetworkError} No response was received at all.
 * @throws {DOMException} Named `AbortError` when the caller aborts.
 */
export function apiUpload<TResponse>(path: string, options: ApiUploadOptions): Promise<TResponse> {
  const { body, method = "POST", onProgress, signal, timeoutMs = UPLOAD_TIMEOUT_MS } = options;
  const requestId = newRequestId();

  return new Promise<TResponse>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The upload was aborted.", "AbortError"));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open(method, buildUrl(path));
    xhr.timeout = timeoutMs;
    // Matches `credentials: "include"` in apiFetch, so session auth behaves
    // the same on both paths.
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader(REQUEST_ID_HEADER, requestId);
    // Content-Type is deliberately not set: the browser must add it itself to
    // include the multipart boundary, and setting it here omits the boundary.

    if (onProgress) {
      xhr.upload.addEventListener("progress", (event) => {
        const measurable = event.lengthComputable && event.total > 0;
        onProgress({
          loaded: event.loaded,
          total: measurable ? event.total : null,
          percent: measurable ? Math.min(100, (event.loaded / event.total) * 100) : null,
        });
      });
    }

    const abortUpload = () => xhr.abort();
    signal?.addEventListener("abort", abortUpload, { once: true });
    const detach = () => signal?.removeEventListener("abort", abortUpload);

    xhr.addEventListener("load", () => {
      detach();
      const correlationId = xhr.getResponseHeader(REQUEST_ID_HEADER) ?? requestId;

      if (xhr.status < 200 || xhr.status >= 300) {
        const failure = parseErrorBody(xhr.responseText, xhr.status, correlationId);
        reject(new ApiError(xhr.status, failure));
        return;
      }

      if (xhr.status === 204 || xhr.status === 205 || !xhr.responseText) {
        resolve(undefined as TResponse);
        return;
      }

      try {
        resolve(JSON.parse(xhr.responseText) as TResponse);
      } catch {
        // A 2xx we cannot read is still a failed call from the caller's side.
        reject(new ApiError(xhr.status, fallbackErrorBody(xhr.status, correlationId)));
      }
    });

    xhr.addEventListener("error", () => {
      detach();
      reject(new NetworkError(new Error("The upload could not reach the server.")));
    });

    xhr.addEventListener("timeout", () => {
      detach();
      reject(new NetworkError(new Error(`The upload timed out after ${timeoutMs}ms.`)));
    });

    xhr.addEventListener("abort", () => {
      detach();
      reject(new DOMException("The upload was aborted.", "AbortError"));
    });

    xhr.send(body);
  });
}

/** Convenience wrappers. Thin on purpose — all behaviour lives in apiFetch. */
export const api = {
  get: <T>(path: string, options?: ApiFetchOptions) =>
    apiFetch<T>(path, { ...options, method: "GET" }),

  post: <T>(path: string, body?: unknown, options?: ApiFetchOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),

  patch: <T>(path: string, body?: unknown, options?: ApiFetchOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),

  delete: <T>(path: string, options?: ApiFetchOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
