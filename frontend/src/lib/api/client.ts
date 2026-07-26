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
 * Extract the error envelope, tolerating a response that is not our envelope.
 *
 * A proxy timeout or a WAF block returns HTML, not JSON. Without this
 * fallback the parse failure would mask the real status code with an opaque
 * "Unexpected token <" error.
 */
async function readErrorBody(response: Response, requestId: string): Promise<ApiErrorBody> {
  const fallback: ApiErrorBody = {
    code: "unexpected_response",
    message: `Request failed with status ${response.status}.`,
    details: {},
    request_id: response.headers.get(REQUEST_ID_HEADER) ?? requestId,
  };

  try {
    const parsed = (await response.json()) as { error?: Partial<ApiErrorBody> };
    if (parsed?.error?.code) {
      return { ...fallback, ...parsed.error } as ApiErrorBody;
    }
  } catch {
    // Body was empty or not JSON; the fallback is the honest answer.
  }
  return fallback;
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
