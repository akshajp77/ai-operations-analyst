import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Trace the module graph and emit a self-contained server bundle.
   * This is what lets the Docker runtime stage ship ~150 MB instead of
   * ~1.2 GB — node_modules never enters the final image.
   */
  output: "standalone",

  /**
   * Fail the build on a type error or lint violation.
   *
   * Next.js does this by default; stating it explicitly is a guard against
   * the future pull request that "temporarily" sets ignoreBuildErrors to
   * unblock a release. A broken type is a broken build.
   */
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },

  /**
   * Do not advertise the framework version to every visitor. Free
   * reconnaissance for anyone scanning for known CVEs.
   */
  poweredByHeader: false,

  /**
   * Surface accidental double-invocation and unsafe lifecycles in
   * development. On by default in Next 15; pinned so it is never quietly
   * disabled to silence a warning rather than fix it.
   */
  reactStrictMode: true,

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            // Deny device APIs this product has no reason to touch. Cheap,
            // and it limits the damage of a future third-party script.
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
