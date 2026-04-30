import { beforeEach, describe, expect, it } from "vitest";
import {
  clearAllPhoneBearers,
  clearPhoneBearer,
  getLatestPhoneBearer,
  getPhoneBearer,
  setPhoneBearer,
} from "../../lib/phoneBearerStore";

describe("phoneBearerStore", () => {
  beforeEach(async () => {
    await clearAllPhoneBearers();
  });

  it("round-trips set/get/clear for one device", async () => {
    const input = {
      paired_device_id: "device-1",
      phone_bearer: "a".repeat(64),
      pair_claim_marker: "claim-1",
    };
    await setPhoneBearer(input);

    const stored = await getPhoneBearer("device-1");
    expect(stored).toMatchObject(input);
    expect(typeof stored.updated_at).toBe("number");

    await clearPhoneBearer("device-1");
    expect(await getPhoneBearer("device-1")).toBeNull();
  });

  it("keeps records isolated by paired_device_id", async () => {
    await setPhoneBearer({
      paired_device_id: "device-alpha",
      phone_bearer: "b".repeat(64),
      pair_claim_marker: "claim-alpha",
    });
    await setPhoneBearer({
      paired_device_id: "device-beta",
      phone_bearer: "c".repeat(64),
      pair_claim_marker: "claim-beta",
    });

    const alpha = await getPhoneBearer("device-alpha");
    const beta = await getPhoneBearer("device-beta");
    expect(alpha.phone_bearer).toBe("b".repeat(64));
    expect(beta.phone_bearer).toBe("c".repeat(64));

    const latest = await getLatestPhoneBearer();
    expect(["device-alpha", "device-beta"]).toContain(latest.paired_device_id);
  });
});
