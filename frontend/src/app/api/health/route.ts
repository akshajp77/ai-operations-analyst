/**
 * Liveness endpoint for the Next.js server itself.
 *
 * Separate from the backend's `/health/live`: this one answers "is the web
 * container serving?" and is what the container HEALTHCHECK and any frontend
 * load balancer probe hit. It deliberately does not call the API, for the
 * same reason the backend's liveness probe does not touch PostgreSQL — a
 * backend outage should not cause every web container to be restarted.
 */
import { NextResponse } from "next/server";

// Never prerendered or cached: a cached health check is not a health check.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok" }, { status: 200 });
}
