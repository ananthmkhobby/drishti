// Custom production server: terminates HTTPS directly (needed for camera
// access — getUserMedia requires a secure context) in front of a pre-built
// Next.js app. `next start` alone has no HTTPS option; `next dev
// --experimental-https` works but recompiles every route on first visit,
// which is far too slow on constrained hardware (e.g. a Raspberry Pi).
const { createServer: createHttpsServer } = require("https");
const { createServer: createHttpServer, request: httpRequest } = require("http");
const { readFileSync } = require("fs");
const path = require("path");
const next = require("next");

// Same backend the /api/backend/* rewrite in next.config.ts points HTTP
// requests at. Next's rewrites() only proxies plain HTTP — it never forwards
// a WebSocket Upgrade handshake — so anything that opens a WS through
// /api/backend/* (e.g. useWakeWord.ts, whose WS_URL falls back to this
// relative path whenever NEXT_PUBLIC_API_URL isn't an absolute http(s) URL)
// got back a bogus non-101 response and failed with ERR_INVALID_HTTP_RESPONSE
// (confirmed 2026-09-17). This manually proxies the upgrade at the TCP level,
// the same way the standard `http-proxy` library does it, without pulling in
// the dependency.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const backendUrl = new URL(BACKEND_URL);

function proxyWebSocketUpgrade(req, socket, head) {
  const url = new URL(req.url, "http://internal");
  if (!url.pathname.startsWith("/api/backend/")) {
    socket.destroy();
    return;
  }
  const backendPath = url.pathname.replace(/^\/api\/backend/, "/v1") + url.search;

  const proxyReq = httpRequest({
    hostname: backendUrl.hostname,
    port: backendUrl.port || 80,
    path: backendPath,
    method: req.method,
    headers: { ...req.headers, host: `${backendUrl.hostname}:${backendUrl.port || 80}` },
  });

  proxyReq.on("upgrade", (proxyRes, proxySocket, proxyHead) => {
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\n" +
        Object.entries(proxyRes.headers)
          .map(([k, v]) => `${k}: ${v}`)
          .join("\r\n") +
        "\r\n\r\n"
    );
    if (proxyHead && proxyHead.length) socket.write(proxyHead);
    if (head && head.length) proxySocket.write(head);
    proxySocket.pipe(socket);
    socket.pipe(proxySocket);
  });

  proxyReq.on("error", () => socket.destroy());
  socket.on("error", () => proxyReq.destroy());

  proxyReq.end();
}

const port = parseInt(process.env.PORT || "3000", 10);
// Plain-HTTP listener, loopback-only — never reachable from the LAN. Browsers
// treat `localhost` as a secure context even over HTTP, so the on-device
// kiosk browser (Chromium + local camera, driving a TV) can use this and
// skip the self-signed cert warning entirely. Phones on the LAN keep using
// the HTTPS listener above, where a real cert is unavoidable.
const localPort = parseInt(process.env.LOCAL_HTTP_PORT || "3001", 10);
const app = next({ dev: false, hostname: "0.0.0.0", port, dir: __dirname });
const handle = app.getRequestHandler();

const httpsOptions = {
  key: readFileSync(path.join(__dirname, "key.pem")),
  cert: readFileSync(path.join(__dirname, "cert.pem")),
};

app.prepare().then(() => {
  const httpsServer = createHttpsServer(httpsOptions, (req, res) => {
    handle(req, res);
  }).listen(port, "0.0.0.0", (err) => {
    if (err) throw err;
    console.log(`> Ready on https://0.0.0.0:${port}`);
  });
  httpsServer.on("upgrade", proxyWebSocketUpgrade);

  const httpServer = createHttpServer((req, res) => {
    handle(req, res);
  }).listen(localPort, "127.0.0.1", (err) => {
    if (err) throw err;
    console.log(`> Ready on http://127.0.0.1:${localPort} (loopback-only, for the on-device kiosk browser)`);
  });
  httpServer.on("upgrade", proxyWebSocketUpgrade);
});
