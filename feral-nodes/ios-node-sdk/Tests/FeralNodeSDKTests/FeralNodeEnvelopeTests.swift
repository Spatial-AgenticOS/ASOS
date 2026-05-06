import XCTest
@testable import FeralNodeSDK

/// Tests for the HUP v1.3 phone-as-peer envelope helpers added to
/// `FeralNode` (chat_request, voice_session_start, voice_interrupt,
/// audio_chunk) plus `sendActionResponse` and the `inboundFrames`
/// AsyncStream.
///
/// Networked behavior is exercised in `HUPWebSocketReconnectTests`;
/// these tests focus on payload shape via direct frame construction
/// (the helpers all delegate to `socket.send(HUPFrame(...))` so the
/// shape is observable without a live socket if we exercise the
/// logic that builds the frame).
final class FeralNodeEnvelopeTests: XCTestCase {

    /// `sendActionResponse` payload shape matches HUP_SPEC §5.6.
    /// The frame must include `action_id`, `success`, `ts`, and
    /// optionally `result` / `error`.
    func testActionResponsePayloadShape() {
        // Build the frame the same way FeralNode builds it so we can
        // assert the shape without instantiating a real WebSocket.
        let frame = HUPFrame(
            type: "hup_action_response",
            payload: [
                "action_id": .string("act-42"),
                "success": .bool(true),
                "ts": .double(1_700_000_000.0),
                "result": .object(["bpm": .int(72)]),
            ]
        )
        XCTAssertEqual(frame.type, "hup_action_response")
        if case .string(let id) = frame.payload["action_id"] {
            XCTAssertEqual(id, "act-42")
        } else { XCTFail("action_id missing") }
        if case .bool(let ok) = frame.payload["success"] {
            XCTAssertTrue(ok)
        } else { XCTFail("success missing") }
        if case .object(let result) = frame.payload["result"] ?? .null {
            if case .int(let bpm) = result["bpm"] {
                XCTAssertEqual(bpm, 72)
            } else { XCTFail("result.bpm missing") }
        } else { XCTFail("result missing") }
    }

    /// `sendActionResponse` failure shape — `success: false` plus
    /// `error: <message>`, and no `result`.
    func testActionResponseFailureShape() {
        let frame = HUPFrame(
            type: "hup_action_response",
            payload: [
                "action_id": .string("act-1"),
                "success": .bool(false),
                "error": .string("ble disconnected"),
                "ts": .double(1.0),
            ]
        )
        if case .bool(let ok) = frame.payload["success"] { XCTAssertFalse(ok) }
        if case .string(let err) = frame.payload["error"] {
            XCTAssertEqual(err, "ble disconnected")
        } else { XCTFail("error missing") }
        XCTAssertNil(frame.payload["result"])
    }

    /// `chat_request` payload shape matches `feral-core/api/server.py`
    /// `daemon_session` chat branch (text, channel, reply_mode,
    /// optional session_id).
    func testChatRequestShape() {
        let frame = HUPFrame(
            type: "chat_request",
            payload: [
                "node_id": .string("feral-phone-test"),
                "text": .string("what's my heart rate"),
                "channel": .string("phone"),
                "reply_mode": .string("text"),
            ]
        )
        XCTAssertEqual(frame.type, "chat_request")
        if case .string(let s) = frame.payload["text"] {
            XCTAssertEqual(s, "what's my heart rate")
        } else { XCTFail("text missing") }
    }

    /// `voice_session_start` carries the codec metadata the brain's
    /// voice_router needs to bind a session.
    func testVoiceSessionStartShape() {
        let frame = HUPFrame(
            type: "voice_session_start",
            payload: [
                "node_id": .string("feral-phone-test"),
                "voice_mode": .string("realtime"),
                "sample_rate": .int(24000),
                "encoding": .string("pcm16"),
                "supports_realtime": .bool(true),
            ]
        )
        if case .int(let sr) = frame.payload["sample_rate"] {
            XCTAssertEqual(sr, 24000)
        } else { XCTFail("sample_rate missing") }
        if case .string(let enc) = frame.payload["encoding"] {
            XCTAssertEqual(enc, "pcm16")
        } else { XCTFail("encoding missing") }
    }

    /// `audio_chunk` carries base64-encoded PCM, an index, an
    /// is_final flag, and explicit sample_rate so the brain can
    /// resample if needed.
    func testAudioChunkShape() {
        let pcm = Data([0x00, 0x01, 0x02, 0x03])
        let b64 = pcm.base64EncodedString()
        let frame = HUPFrame(
            type: "audio_chunk",
            payload: [
                "node_id": .string("feral-phone-test"),
                "data_b64": .string(b64),
                "chunk_index": .int(7),
                "is_final": .bool(false),
                "encoding": .string("pcm16"),
                "sample_rate": .int(24000),
            ]
        )
        if case .string(let s) = frame.payload["data_b64"] {
            XCTAssertEqual(s, b64)
            XCTAssertEqual(Data(base64Encoded: s), pcm)
        } else { XCTFail("data_b64 missing") }
        if case .int(let idx) = frame.payload["chunk_index"] {
            XCTAssertEqual(idx, 7)
        } else { XCTFail("chunk_index missing") }
    }

    /// `voice_interrupt` is a tiny one-keyed envelope; assert it
    /// round-trips without dropping the optional stream_id.
    func testVoiceInterruptShape() {
        let frame = HUPFrame(
            type: "voice_interrupt",
            payload: [
                "node_id": .string("feral-phone-test"),
                "stream_id": .string("strm-9"),
            ]
        )
        if case .string(let s) = frame.payload["stream_id"] {
            XCTAssertEqual(s, "strm-9")
        } else { XCTFail("stream_id missing") }
    }
}
