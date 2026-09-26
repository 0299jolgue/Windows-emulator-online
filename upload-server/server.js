const http = require("node:http");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const crypto = require("node:crypto");
const Busboy = require("busboy");

const PORT = Number(process.env.PORT || 3000);
const UPLOAD_DIR = path.resolve(process.env.UPLOAD_DIR || "/shared");
const MAX_FILE_SIZE = Number(
  process.env.MAX_FILE_SIZE || 2 * 1024 * 1024 * 1024
);

async function ensureUploadDir() {
  await fsp.mkdir(UPLOAD_DIR, { recursive: true });
  await fsp.chmod(UPLOAD_DIR, 0o777).catch(() => {});
}

function json(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function safeName(original) {
  const base = path
    .basename(String(original || "file"))
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, "_")
    .trim();

  const cleaned = base || "file";
  const id = crypto.randomBytes(6).toString("hex");
  return String(Date.now()) + "-" + id + "-" + cleaned;
}

async function listFiles() {
  const entries = await fsp.readdir(UPLOAD_DIR, { withFileTypes: true });
  const rows = [];

  for (const entry of entries) {
    if (!entry.isFile()) continue;

    const full = path.join(UPLOAD_DIR, entry.name);
    try {
      const stat = await fsp.stat(full);
      rows.push({
        name: entry.name,
        size: stat.size,
        mtime: stat.mtime.toISOString(),
      });
    } catch {}
  }

  rows.sort((a, b) => Date.parse(b.mtime) - Date.parse(a.mtime));
  return rows.slice(0, 100);
}

function upload(req, res) {
  const contentType = req.headers["content-type"] || "";

  if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
    return json(res, 415, { error: "Use multipart/form-data." });
  }

  let busboy;
  try {
    busboy = Busboy({
      headers: req.headers,
      limits: {
        files: 20,
        fileSize: MAX_FILE_SIZE,
      },
    });
  } catch (error) {
    return json(res, 400, { error: error.message });
  }

  const files = [];
  let hadError = false;
  let fatalError = null;
  const pendingWrites = [];

  busboy.on("file", (fieldname, stream, info) => {
    const original = info?.filename || "file";
    const filename = safeName(original);
    const destination = path.join(UPLOAD_DIR, filename);
    const writer = fs.createWriteStream(destination, { flags: "wx" });
    let truncated = false;

    stream.on("limit", () => {
      truncated = true;
    });

    const finished = new Promise((resolve, reject) => {
      writer.on("finish", async () => {
        try {
          if (truncated) {
            await fsp.unlink(destination).catch(() => {});
            return reject(
              new Error("Ficheiro demasiado grande: " + original)
            );
          }

          const stat = await fsp.stat(destination);
          files.push({
            originalName: original,
            storedName: filename,
            size: stat.size,
          });
          resolve();
        } catch (error) {
          await fsp.unlink(destination).catch(() => {});
          reject(error);
        }
      });

      writer.on("error", reject);
      stream.on("error", reject);
    });

    stream.pipe(writer);

    stream.on("aborted", () => {
      hadError = true;
      writer.destroy();
      fsp.unlink(destination).catch(() => {});
    });

    pendingWrites.push(finished);
    finished.catch((error) => {
      hadError = true;
      fatalError = error;
    });
  });

  busboy.on("filesLimit", () => {
    hadError = true;
    fatalError = new Error("Limite de 20 ficheiros por envio atingido.");
  });

  busboy.on("error", (error) => {
    hadError = true;
    fatalError = error;
  });

  busboy.on("finish", async () => {
    const results = await Promise.allSettled(pendingWrites);
    const failed = results.find((result) => result.status === "rejected");
    if (failed) {
      hadError = true;
      fatalError = fatalError || failed.reason;
    }

    if (hadError || fatalError) {
      return json(res, 400, {
        error: fatalError?.message || "Falha ao receber o upload.",
        files,
      });
    }

    if (files.length === 0) {
      return json(res, 400, { error: "Nenhum ficheiro recebido." });
    }

    return json(res, 201, { files });
  });

  req.on("aborted", () => {
    hadError = true;
  });

  req.pipe(busboy);
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      return json(res, 200, { ok: true });
    }

    if (req.method === "GET" && req.url === "/files") {
      return json(res, 200, { files: await listFiles() });
    }

    if (req.method === "POST" && req.url === "/upload") {
      return upload(req, res);
    }

    json(res, 404, { error: "Not found" });
  } catch (error) {
    console.error(error);

    if (!res.headersSent) {
      json(res, 500, { error: "Erro interno." });
    } else {
      res.destroy();
    }
  }
});

server.requestTimeout = 0;
server.headersTimeout = 120000;
server.keepAliveTimeout = 65000;

ensureUploadDir()
  .then(() => {
    server.listen(PORT, "0.0.0.0", () => {
      console.log("Upload server listening on " + PORT);
      console.log("Upload directory: " + UPLOAD_DIR);
      console.log("Max file size: " + MAX_FILE_SIZE + " bytes");
    });
  })
  .catch((error) => {
    console.error("Could not prepare upload directory:", error);
    process.exit(1);
  });
