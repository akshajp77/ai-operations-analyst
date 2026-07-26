/**
 * Validated environment access.
 *
 * `process.env.FOO` is typed `string | undefined` everywhere, so a missing
 * variable becomes the literal string "undefined" inside a URL and surfaces
 * as a confusing 404 at runtime. Parsing once here turns that into a clear
 * failure at module load, with a message naming the variable.
 *
 * The client/server split is a security boundary, not organisation:
 *
 * - `clientEnv` may only read NEXT_PUBLIC_* variables. Next.js inlines them
 *   into the browser bundle, so they are public by definition.
 * - `serverEnv` may read anything, and must never be imported from a client
 *   component. The guard below turns that mistake into an immediate error
 *   rather than a secret shipped to every visitor.
 */
import { z } from "zod";

const clientSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z
    .string()
    .url("NEXT_PUBLIC_API_BASE_URL must be an absolute URL, e.g. http://localhost:8000"),
});

const serverSchema = z.object({
  API_INTERNAL_BASE_URL: z.string().url().optional(),
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
});

function parse<T extends z.ZodTypeAny>(schema: T, source: unknown, scope: string): z.infer<T> {
  const result = schema.safeParse(source);
  if (!result.success) {
    const issues = result.error.issues
      .map((issue) => `  - ${issue.path.join(".")}: ${issue.message}`)
      .join("\n");
    throw new Error(`Invalid ${scope} environment configuration:\n${issues}`);
  }
  return result.data;
}

/**
 * Safe to read from anywhere, including client components.
 *
 * Properties are listed explicitly rather than spread from `process.env`:
 * Next.js replaces `process.env.NEXT_PUBLIC_X` at build time by static text
 * substitution, so a dynamic lookup would resolve to undefined in the bundle.
 */
export const clientEnv = parse(
  clientSchema,
  { NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL },
  "client",
);

/**
 * The correct API base URL for the current execution context.
 *
 * In the browser, requests go out over the public URL. On the server they can
 * take the internal network path, which avoids a pointless hairpin through
 * the load balancer and works inside Docker Compose, where `localhost` would
 * resolve to the web container itself.
 */
export function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_INTERNAL_BASE_URL ?? clientEnv.NEXT_PUBLIC_API_BASE_URL;
  }
  return clientEnv.NEXT_PUBLIC_API_BASE_URL;
}

/**
 * Server-only configuration.
 *
 * A function rather than a module-level constant so that merely importing
 * this module from a client component is harmless; only *calling* it throws.
 * Evaluating eagerly would break the client bundle at import time, which is a
 * far more confusing failure than a precise error at the call site.
 */
export function serverEnv(): z.infer<typeof serverSchema> {
  if (typeof window !== "undefined") {
    throw new Error(
      "serverEnv() was called from client code. Use clientEnv instead — " +
        "server variables must never reach the browser bundle.",
    );
  }
  return parse(
    serverSchema,
    {
      API_INTERNAL_BASE_URL: process.env.API_INTERNAL_BASE_URL,
      NODE_ENV: process.env.NODE_ENV,
    },
    "server",
  );
}
