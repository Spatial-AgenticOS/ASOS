const DB_NAME = "feral-phone-pairing";
const STORE_NAME = "phone_bearers";
const DB_VERSION = 1;

const memoryFallback = new Map();
let dbPromise = null;

function supportsIndexedDB() {
  return (
    typeof globalThis !== "undefined"
    && !!globalThis.indexedDB
    && typeof globalThis.indexedDB.open === "function"
  );
}

function asPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB request failed"));
  });
}

function openDB() {
  if (!supportsIndexedDB()) return Promise.resolve(null);
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      const request = globalThis.indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: "paired_device_id" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

function normalizeRecord(record) {
  if (!record) return null;
  return {
    paired_device_id: String(record.paired_device_id || ""),
    phone_bearer: String(record.phone_bearer || ""),
    pair_claim_marker: String(record.pair_claim_marker || ""),
    updated_at: Number(record.updated_at || Date.now()),
  };
}

export async function setPhoneBearer({ paired_device_id, phone_bearer, pair_claim_marker }) {
  const deviceId = String(paired_device_id || "").trim();
  const bearer = String(phone_bearer || "").trim();
  const marker = String(pair_claim_marker || "").trim();
  if (!deviceId || !bearer || !marker) {
    throw new Error("paired_device_id, phone_bearer, and pair_claim_marker are required");
  }
  const record = normalizeRecord({
    paired_device_id: deviceId,
    phone_bearer: bearer,
    pair_claim_marker: marker,
    updated_at: Date.now(),
  });

  const db = await openDB();
  if (!db) {
    memoryFallback.set(deviceId, record);
    return record;
  }
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error("IndexedDB transaction failed"));
      tx.objectStore(STORE_NAME).put(record);
    });
  } catch {
    memoryFallback.set(deviceId, record);
  }
  return record;
}

export async function getPhoneBearer(paired_device_id) {
  const deviceId = String(paired_device_id || "").trim();
  if (!deviceId) return null;

  const db = await openDB();
  if (!db) {
    return normalizeRecord(memoryFallback.get(deviceId));
  }
  try {
    const tx = db.transaction(STORE_NAME, "readonly");
    const value = await asPromise(tx.objectStore(STORE_NAME).get(deviceId));
    return normalizeRecord(value);
  } catch {
    return normalizeRecord(memoryFallback.get(deviceId));
  }
}

export async function getLatestPhoneBearer() {
  const db = await openDB();
  if (!db) {
    const values = Array.from(memoryFallback.values())
      .map((row) => normalizeRecord(row))
      .filter(Boolean)
      .sort((a, b) => b.updated_at - a.updated_at);
    return values[0] || null;
  }
  try {
    const tx = db.transaction(STORE_NAME, "readonly");
    const values = await asPromise(tx.objectStore(STORE_NAME).getAll());
    const normalized = (values || [])
      .map((row) => normalizeRecord(row))
      .filter(Boolean)
      .sort((a, b) => b.updated_at - a.updated_at);
    return normalized[0] || null;
  } catch {
    const values = Array.from(memoryFallback.values())
      .map((row) => normalizeRecord(row))
      .filter(Boolean)
      .sort((a, b) => b.updated_at - a.updated_at);
    return values[0] || null;
  }
}

export async function clearPhoneBearer(paired_device_id) {
  const deviceId = String(paired_device_id || "").trim();
  if (!deviceId) return;
  memoryFallback.delete(deviceId);
  const db = await openDB();
  if (!db) return;
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error("IndexedDB transaction failed"));
      tx.objectStore(STORE_NAME).delete(deviceId);
    });
  } catch {
    // Memory fallback already cleared.
  }
}

export async function clearAllPhoneBearers() {
  memoryFallback.clear();
  const db = await openDB();
  if (!db) return;
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error || new Error("IndexedDB transaction failed"));
      tx.objectStore(STORE_NAME).clear();
    });
  } catch {
    // Memory fallback already cleared.
  }
}
