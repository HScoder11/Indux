// Development: `npm run dev` serves the app on :3000 and forwards /api and
// /figures to the Python backend on :8000. The browser opens the WebSocket
// straight to :8000 (see lib/live.jsx).
// Production: `npm run build` writes a static site to web/out, which the
// backend serves at http://localhost:8000, so demo day is one command.
const isProd = process.env.NODE_ENV === "production";
const BACKEND = process.env.INDUX_BACKEND || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const config = isProd
  ? { output: "export", trailingSlash: true, images: { unoptimized: true } }
  : {
      images: { unoptimized: true },
      async rewrites() {
        return [
          { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
          { source: "/figures/:path*", destination: `${BACKEND}/figures/:path*` },
        ];
      },
    };

export default config;
