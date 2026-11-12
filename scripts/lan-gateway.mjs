import http from "node:http";

const listenHost = process.env.RADAR_LAN_HOST || "0.0.0.0";
const listenPort = Number(process.env.RADAR_LAN_PORT || "80");
const webPort = Number(process.env.RADAR_WEB_PORT || "13000");
const apiPort = Number(process.env.RADAR_API_PORT || "18000");

function isApiRequest(pathname = "/") {
  return (
    pathname === "/health" ||
    pathname === "/docs" ||
    pathname === "/openapi.json" ||
    pathname.startsWith("/api/")
  );
}

function forwardedHeaders(request, targetPort) {
  const headers = { ...request.headers };
  const originalHost = request.headers.host || "";
  delete headers.connection;
  delete headers["proxy-connection"];
  delete headers["keep-alive"];
  delete headers["transfer-encoding"];
  delete headers.upgrade;
  headers.host = `127.0.0.1:${targetPort}`;
  headers["x-forwarded-host"] = originalHost;
  headers["x-forwarded-proto"] = "http";
  headers["x-forwarded-for"] =
    request.socket.remoteAddress || "127.0.0.1";
  return headers;
}

const server = http.createServer((request, response) => {
  const pathname = new URL(request.url || "/", "http://signal-radar.local")
    .pathname;
  const targetPort = isApiRequest(pathname) ? apiPort : webPort;
  const proxyRequest = http.request(
    {
      hostname: "127.0.0.1",
      port: targetPort,
      method: request.method,
      path: request.url,
      headers: forwardedHeaders(request, targetPort),
    },
    (proxyResponse) => {
      const headers = { ...proxyResponse.headers };
      delete headers.connection;
      delete headers["keep-alive"];
      delete headers["transfer-encoding"];
      response.writeHead(proxyResponse.statusCode || 502, headers);
      proxyResponse.pipe(response);
    },
  );

  proxyRequest.on("error", (error) => {
    if (response.headersSent) {
      response.destroy(error);
      return;
    }
    response.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("行业新闻简报服务暂时不可用，请稍后重试。");
  });
  request.on("aborted", () => proxyRequest.destroy());
  request.pipe(proxyRequest);
});

server.requestTimeout = 0;
server.headersTimeout = 65_000;
server.keepAliveTimeout = 5_000;

server.listen(listenPort, listenHost, () => {
  console.log(`LAN_GATEWAY_READY http://${listenHost}:${listenPort}`);
});
