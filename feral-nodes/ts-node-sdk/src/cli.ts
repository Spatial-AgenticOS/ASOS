#!/usr/bin/env node
/*
 * Shippable CLI for @feral-ai/node-sdk.
 * Mirrors the Python SDK's `python -m feral_node_sdk` entrypoint so
 * vendors can document a single pairing command regardless of language.
 */

import { discoverBrain } from "./discovery";
import { loadKey, pair } from "./pairing";

function usage(): void {
  // eslint-disable-next-line no-console
  console.log(`feral-node <command> [options]

Commands:
  pair      --node-id <id> [--brain <wss://...>] [--name <name>] [--code <123456>] [--insecure]
  discover  [--timeout <seconds>]
  key       --node-id <id>
`);
}

function getArg(argv: string[], name: string): string | undefined {
  const idx = argv.indexOf(`--${name}`);
  if (idx >= 0 && idx + 1 < argv.length) return argv[idx + 1];
  return undefined;
}

function hasFlag(argv: string[], name: string): boolean {
  return argv.includes(`--${name}`);
}

async function main(): Promise<number> {
  const [, , cmd, ...rest] = process.argv;
  if (!cmd || cmd === "-h" || cmd === "--help") {
    usage();
    return 0;
  }
  if (cmd === "pair") {
    const nodeId = getArg(rest, "node-id");
    if (!nodeId) {
      // eslint-disable-next-line no-console
      console.error("error: --node-id is required");
      return 2;
    }
    let brain = getArg(rest, "brain");
    if (!brain) brain = (await discoverBrain(3000)) ?? undefined;
    if (!brain) {
      // eslint-disable-next-line no-console
      console.error("error: no --brain provided and mDNS discovery found nothing.");
      return 2;
    }
    const timeout = Number(getArg(rest, "timeout") ?? "300") * 1000;
    try {
      await pair({
        nodeId,
        brainUrl: brain,
        code: getArg(rest, "code"),
        name: getArg(rest, "name"),
        timeoutMs: timeout,
        verifyTls: !hasFlag(rest, "insecure"),
      });
      return 0;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`error: ${(err as Error).message}`);
      return 3;
    }
  }
  if (cmd === "discover") {
    const timeout = Number(getArg(rest, "timeout") ?? "3") * 1000;
    const url = await discoverBrain(timeout);
    if (url) {
      // eslint-disable-next-line no-console
      console.log(url);
      return 0;
    }
    // eslint-disable-next-line no-console
    console.error("no brain found");
    return 1;
  }
  if (cmd === "key") {
    const nodeId = getArg(rest, "node-id");
    if (!nodeId) {
      // eslint-disable-next-line no-console
      console.error("error: --node-id is required");
      return 2;
    }
    const k = await loadKey(nodeId);
    if (k) {
      // eslint-disable-next-line no-console
      console.log(k);
      return 0;
    }
    // eslint-disable-next-line no-console
    console.error("no key stored");
    return 1;
  }
  usage();
  return 2;
}

main().then((c) => process.exit(c)).catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});
