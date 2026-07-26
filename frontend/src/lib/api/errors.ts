/**
 * The client-side counterpart to the backend's error envelope.
 *
 * Because the backend guarantees one error shape for every failure
 * (see `backend/app/core/exceptions.py`), the frontend needs exactly one
 * error class. UI code branches on a stable `code`, never on a message
 * string — messages are written for humans and will be reworded.
 */

/** Mirrors `ErrorDetail` in `backend/app/schemas/common.py`. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string | null;
}

/** One field-level validation failure, for rendering next to a form input. */
export interface FieldError {
  field: string;
  message: string;
  type: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  /** Correlation id. Surface it in error UI so support can find the request. */
  readonly requestId: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
    this.requestId = body.request_id ?? null;
  }

  /** Field-level failures from a 422, if present. */
  get fieldErrors(): FieldError[] {
    const fields = this.details.fields;
    return Array.isArray(fields) ? (fields as FieldError[]) : [];
  }

  /**
   * Whether retrying the identical request could plausibly succeed.
   *
   * Used by the query layer to decide what to retry. Retrying a 422 just
   * wastes the user's time and our capacity; retrying a 502 is often the
   * right thing.
   */
  get isRetryable(): boolean {
    return this.status === 408 || this.status === 429 || this.status >= 500;
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

/**
 * Raised when the request never produced an HTTP response at all — offline,
 * DNS failure, CORS rejection, or an aborted fetch.
 *
 * Kept distinct from `ApiError` because the user-facing remedy is different:
 * "check your connection", not "the server rejected this".
 */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("Could not reach the server. Check your connection and try again.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
