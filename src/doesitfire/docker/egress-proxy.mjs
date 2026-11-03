// Minimal egress proxy: the only way out of the internal Docker network.
// Allows HTTP CONNECT (HTTPS) and plain HTTP forwarding to an allowlist of
// host:port pairs given in DOESITFIRE_ALLOW (comma separated). Everything
// else gets 403. No logging of request bodies.
import http from "node:http";
import net from "node:net";

const allow = new Set(
  (process.env.DOESITFIRE_ALLOW || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
);
const port = Number(process.env.DOESITFIRE_PROXY_PORT || 8888);
// Ollama's OpenAI Responses endpoint drops input messages with role "developer", which is
// where Codex puts its skill list. For local Ollama only (plain HTTP), rewrite them to
// "system", which Ollama keeps. HTTPS traffic to paid APIs is tunnelled and never touched.
const developerAsSystem = process.env.DOESITFIRE_DEVELOPER_AS_SYSTEM === "1";

function rewriteDeveloper(buf) {
  try {
    const body = JSON.parse(buf.toString("utf8"));
    if (!Array.isArray(body.input)) return buf;
    let changed = false;
    for (const item of body.input) {
      if (item && item.role === "developer") {
        item.role = "system";
        changed = true;
      }
    }
    return changed ? Buffer.from(JSON.stringify(body), "utf8") : buf;
  } catch {
    return buf;
  }
}

function allowed(host, p) {
  return allow.has(`${String(host).toLowerCase()}:${p}`);
}

const server = http.createServer((req, res) => {
  req.on("error", () => {});
  res.on("error", () => {});
  let url;
  try {
    url = new URL(req.url);
  } catch {
    res.writeHead(400).end("absolute URL required\n");
    return;
  }
  const p = url.port || (url.protocol === "https:" ? 443 : 80);
  if (url.protocol !== "http:" || !allowed(url.hostname, p)) {
    console.error(`deny ${req.method} ${url.hostname}:${p}`);
    res.writeHead(403).end("blocked by doesitfire egress proxy\n");
    return;
  }
  console.error(`allow ${req.method} ${url.hostname}:${p}${url.pathname}`);
  const headers = { ...req.headers };
  delete headers["proxy-connection"];
  delete headers["proxy-authorization"];
  const forward = (body) => {
    if (body) {
      headers["content-length"] = String(body.length);
      delete headers["transfer-encoding"];
    }
    const upstream = http.request(
      { host: url.hostname, port: p, method: req.method, path: url.pathname + url.search, headers },
      (up) => {
        res.writeHead(up.statusCode || 502, up.headers);
        up.pipe(res);
      },
    );
    upstream.on("error", () => {
      if (!res.headersSent) res.writeHead(502);
      res.end();
    });
    res.on("close", () => upstream.destroy());
    if (body) upstream.end(body);
    else req.pipe(upstream);
  };
  if (developerAsSystem && req.method === "POST" && url.pathname.endsWith("/responses")) {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => forward(rewriteDeveloper(Buffer.concat(chunks))));
  } else {
    forward(null);
  }
});

server.on("connect", (req, socket, head) => {
  socket.on("error", () => {});
  const [host, p] = String(req.url).split(":");
  if (!allowed(host, p || 443)) {
    console.error(`deny CONNECT ${req.url}`);
    socket.end("HTTP/1.1 403 Forbidden\r\n\r\n");
    return;
  }
  console.error(`allow CONNECT ${req.url}`);
  const upstream = net.connect(Number(p || 443), host, () => {
    socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
    upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
  socket.on("close", () => upstream.destroy());
});

server.on("clientError", (err, socket) => socket.destroy());
// A proxy must never die because one client hung up mid-stream.
process.on("uncaughtException", (err) => console.error(`proxy error: ${err.code || err.message}`));

server.listen(port, "0.0.0.0", () => {
  console.error(`egress proxy on :${port}, allow=${[...allow].join(",") || "(nothing)"}`);
});
