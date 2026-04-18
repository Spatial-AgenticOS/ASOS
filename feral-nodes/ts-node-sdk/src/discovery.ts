/*
 * mDNS discovery of FERAL brains on the LAN (HUP_SPEC.md §4.3).
 * Uses bonjour-service to resolve `_feral-brain._tcp.local.`.
 */

import { Bonjour, Service } from "bonjour-service";

export async function discoverBrain(
  timeoutMs = 3000,
): Promise<string | null> {
  return new Promise((resolve) => {
    const bj = new Bonjour();
    let resolved = false;

    const finish = (url: string | null) => {
      if (resolved) return;
      resolved = true;
      try {
        browser.stop();
      } catch {
        /* ignore */
      }
      try {
        bj.destroy();
      } catch {
        /* ignore */
      }
      resolve(url);
    };

    const browser = bj.find({ type: "feral-brain" }, (service: Service) => {
      const host =
        service.addresses?.find((a) => a.includes(".")) ??
        service.referer?.address ??
        service.host;
      if (!host) return;
      const txt = (service.txt ?? {}) as Record<string, string>;
      const path = txt["node_path"] ?? "/v1/node";
      const scheme =
        txt["tls"] === "0" || txt["tls"] === "false" ? "ws" : "wss";
      finish(`${scheme}://${host}:${service.port}${path}`);
    });

    setTimeout(() => finish(null), timeoutMs);
  });
}
