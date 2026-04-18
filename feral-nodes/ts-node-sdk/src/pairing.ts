/*
 * Client side of the 6-digit pairing flow (HUP_SPEC.md §4.1).
 * Generates a code, announces it to the brain, polls for the API key,
 * and persists the key to ~/.feral/node-keys/<node_id>.key (mode 0600).
 */

import { promises as fs } from "fs";
import * as os from "os";
import * as path from "path";
import * as http from "http";
import * as https from "https";
import { URL } from "url";

const KEYS_DIR = path.join(os.homedir(), ".feral", "node-keys");

function keyPath(nodeId: string): string {
  const safe = nodeId.replace(/[^A-Za-z0-9._:-]/g, "_");
  return path.join(KEYS_DIR, `${safe}.key`);
}

export async function loadKey(nodeId: string): Promise<string | null> {
  try {
    const data = await fs.readFile(keyPath(nodeId), "utf8");
    const t = data.trim();
    return t.length > 0 ? t : null;
  } catch {
    return null;
  }
}

export async function saveKey(nodeId: string, apiKey: string): Promise<string> {
  await fs.mkdir(KEYS_DIR, { recursive: true });
  const p = keyPath(nodeId);
  await fs.writeFile(p, apiKey.trim() + "\n", { mode: 0o600 });
  try {
    await fs.chmod(p, 0o600);
  } catch {
    /* ignore */
  }
  return p;
}

export function generateCode(): string {
  const n = Math.floor(Math.random() * 1_000_000);
  return n.toString().padStart(6, "0");
}

function httpBase(brainUrl: string): string {
  let u = brainUrl;
  if (u.startsWith("wss://")) u = "https://" + u.slice("wss://".length);
  else if (u.startsWith("ws://")) u = "http://" + u.slice("ws://".length);
  const idx = u.indexOf("/v1/node");
  if (idx >= 0) u = u.slice(0, idx);
  return u.replace(/\/$/, "");
}

interface RequestOpts {
  method: "GET" | "POST";
  url: string;
  body?: string;
  verifyTls: boolean;
  timeoutMs: number;
}

function request(opts: RequestOpts): Promise<string> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(opts.url);
    const isHttps = parsed.protocol === "https:";
    const lib = isHttps ? https : http;
    const req = lib.request(
      {
        method: opts.method,
        hostname: parsed.hostname,
        port: parsed.port || (isHttps ? 443 : 80),
        path: parsed.pathname + parsed.search,
        headers: {
          "Content-Type": "application/json",
          ...(opts.body ? { "Content-Length": Buffer.byteLength(opts.body) } : {}),
        },
        rejectUnauthorized: opts.verifyTls,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
      },
    );
    req.setTimeout(opts.timeoutMs, () => req.destroy(new Error("timeout")));
    req.on("error", reject);
    if (opts.body) req.write(opts.body);
    req.end();
  });
}

export interface PairOptions {
  nodeId: string;
  brainUrl: string;
  name?: string;
  code?: string;
  pollIntervalMs?: number;
  timeoutMs?: number;
  verifyTls?: boolean;
}

export async function pair(opts: PairOptions): Promise<string> {
  const code = opts.code ?? generateCode();
  const base = httpBase(opts.brainUrl);
  const verifyTls = opts.verifyTls !== false;
  const timeoutMs = opts.timeoutMs ?? 300_000;
  const pollIntervalMs = opts.pollIntervalMs ?? 2000;

  // eslint-disable-next-line no-console
  console.log(`\n  FERAL pairing code: ${code.slice(0, 3)} ${code.slice(3)}`);
  // eslint-disable-next-line no-console
  console.log("  → Open FERAL → Settings → Devices → Pair and enter the code.");
  // eslint-disable-next-line no-console
  console.log(`  (Will wait up to ${Math.round(timeoutMs / 1000)}s against ${base})\n`);

  try {
    await request({
      method: "POST",
      url: `${base}/api/devices/pair/announce`,
      body: JSON.stringify({
        code,
        node_id: opts.nodeId,
        name: opts.name ?? opts.nodeId,
      }),
      verifyTls,
      timeoutMs: 5000,
    });
  } catch {
    /* announce is best-effort */
  }

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const body = await request({
        method: "GET",
        url: `${base}/api/devices/pair/status?code=${code}&node_id=${encodeURIComponent(opts.nodeId)}`,
        verifyTls,
        timeoutMs: 5000,
      });
      const data = JSON.parse(body);
      if (data.status === "paired" && typeof data.token === "string") {
        const where = await saveKey(opts.nodeId, data.token);
        // eslint-disable-next-line no-console
        console.log(`  ✓ Paired. API key saved to ${where}`);
        return data.token as string;
      }
    } catch {
      /* ignore + retry */
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }
  throw new Error("Pairing timed out; ask the user to try again.");
}
