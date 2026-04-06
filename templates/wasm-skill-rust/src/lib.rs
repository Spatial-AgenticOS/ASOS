// THEORA WASM Skill Template (Rust)
//
// Host functions available:
//   theora_log(ptr, len)     — log a message
//   theora_http(ptr, len)    — make an HTTP request (returns response ptr)
//   theora_read_result(ptr, len) — read HTTP response into buffer
//   theora_store_get(key_ptr, key_len) — read from skill storage
//   theora_store_set(key_ptr, key_len, val_ptr, val_len) — write to skill storage

extern "C" {
    fn theora_log(ptr: *const u8, len: u32);
    fn theora_http(ptr: *const u8, len: u32) -> u32;
    fn theora_read_result(ptr: *mut u8, len: u32) -> u32;
}

fn log(msg: &str) {
    unsafe { theora_log(msg.as_ptr(), msg.len() as u32) }
}

/// Entry point — called by THEORA when this skill is invoked.
/// `input_ptr` points to a JSON string with the skill arguments.
/// Returns a pointer to a JSON response string.
#[no_mangle]
pub extern "C" fn execute(input_ptr: *const u8, input_len: u32) -> u64 {
    let input = unsafe {
        let slice = std::slice::from_raw_parts(input_ptr, input_len as usize);
        String::from_utf8_lossy(slice).to_string()
    };

    log(&format!("Skill invoked with: {}", &input[..input.len().min(100)]));

    let response = serde_json::json!({
        "success": true,
        "data": {
            "message": "Hello from WASM skill!",
            "input_length": input.len(),
        }
    });

    let response_str = response.to_string();
    let ptr = response_str.as_ptr() as u64;
    let len = response_str.len() as u64;
    std::mem::forget(response_str);

    (len << 32) | ptr
}

#[no_mangle]
pub extern "C" fn allocate(size: u32) -> *mut u8 {
    let mut buf = Vec::with_capacity(size as usize);
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

#[no_mangle]
pub extern "C" fn deallocate(ptr: *mut u8, size: u32) {
    unsafe { drop(Vec::from_raw_parts(ptr, 0, size as usize)) }
}
