// THEORA WASM Skill Template (AssemblyScript)
//
// Host functions imported from THEORA runtime:

@external("env", "theora_log")
declare function theora_log(ptr: usize, len: u32): void;

@external("env", "theora_http")
declare function theora_http(ptr: usize, len: u32): u32;

function log(msg: string): void {
  const encoded = String.UTF8.encode(msg);
  theora_log(changetype<usize>(encoded), encoded.byteLength);
}

// Entry point called by THEORA
export function execute(inputPtr: usize, inputLen: u32): u64 {
  const input = String.UTF8.decodeUnsafe(inputPtr, inputLen);
  log("Skill invoked with: " + input.substring(0, 100));

  const response = '{"success":true,"data":{"message":"Hello from AssemblyScript WASM skill!"}}';
  const responseEncoded = String.UTF8.encode(response);
  const ptr = changetype<usize>(responseEncoded);
  const len = responseEncoded.byteLength;

  return (u64(len) << 32) | u64(ptr);
}

// Memory allocation for the host
export function allocate(size: u32): usize {
  return heap.alloc(size);
}

export function deallocate(ptr: usize, size: u32): void {
  heap.free(changetype<usize>(ptr));
}
