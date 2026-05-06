import XCTest
@testable import FeralNodeSDK

final class HUPFrameTests: XCTestCase {
    /// HUP v1.1 frames must round-trip through JSON without drift —
    /// the brain decodes them with the canonical Python pydantic
    /// model in feral-nodes/python-node-sdk/src/feral_node_sdk/
    /// schemas.py, so any serialisation asymmetry here breaks the
    /// handshake.
    func testHUPFrameRoundTrip() throws {
        let frame = HUPFrame(type: "device_event", payload: [
            "event_type": .string("heart_rate"),
            "node_id": .string("feral-phone-abcd"),
            "data": .object([
                "bpm": .int(72),
                "confidence": .double(0.94),
            ]),
            "ts": .double(1734369931.21),
        ])

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(frame)
        let decoded = try JSONDecoder().decode(HUPFrame.self, from: data)

        XCTAssertEqual(decoded.type, "device_event")
        XCTAssertEqual(decoded.hupVersion, FeralNodeSDKInfo.hupVersion)
        if case .string(let s) = decoded.payload["event_type"] ?? .null {
            XCTAssertEqual(s, "heart_rate")
        } else {
            XCTFail("event_type did not decode as string")
        }
    }

    /// Inbound frames in the wild sometimes omit `hup_version` and/or
    /// `ts` — the brain's mesh-level `hup_action_request` and
    /// `tts_chunk` paths historically did this. Decoding must be
    /// tolerant: missing fields decode to `nil`, never throw.
    func testHUPFrameToleratesMissingVersionAndTs() throws {
        let json = """
        {"type": "node_ack", "payload": {"heartbeat_ms": 5000}}
        """.data(using: .utf8)!
        let frame = try JSONDecoder().decode(HUPFrame.self, from: json)
        XCTAssertEqual(frame.type, "node_ack")
        XCTAssertNil(frame.hupVersion)
        XCTAssertNil(frame.timestamp)
        if case .int(let ms) = frame.payload["heartbeat_ms"] {
            XCTAssertEqual(ms, 5000)
        } else {
            XCTFail("heartbeat_ms should decode as int")
        }
    }

    /// And a frame that omits `payload` entirely — defaults to empty.
    func testHUPFrameToleratesMissingPayload() throws {
        let json = """
        {"hup_version": "1.3.0", "type": "node_bye"}
        """.data(using: .utf8)!
        let frame = try JSONDecoder().decode(HUPFrame.self, from: json)
        XCTAssertEqual(frame.type, "node_bye")
        XCTAssertEqual(frame.payload.count, 0)
    }

    /// Outbound frames MUST always carry `hup_version` and `ts` — the
    /// brain Pydantic model is strict on these even though our decoder
    /// is lenient on inbound. Verifies the encoder fills in defaults
    /// when the host constructs a frame with optional fields nil.
    func testHUPFrameEncodeFillsInDefaultsForOutbound() throws {
        let frame = HUPFrame(
            hupVersion: nil,
            type: "audio_chunk",
            timestamp: nil,
            payload: [:]
        )
        let data = try JSONEncoder().encode(frame)
        let dict = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertEqual(dict["hup_version"] as? String, FeralNodeSDKInfo.hupVersion)
        XCTAssertNotNil(dict["ts"])
        XCTAssertEqual(dict["type"] as? String, "audio_chunk")
    }

    func testNodeRegisterPayloadUsesSnakeCase() throws {
        let payload = NodeRegisterPayload(
            nodeId: "feral-phone-x",
            capabilities: ["veepoo_wristband", "w610_glasses"]
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(payload)
        let json = String(data: data, encoding: .utf8) ?? ""
        // Must emit snake_case keys to match the brain's pydantic model.
        XCTAssertTrue(json.contains("\"node_id\""))
        XCTAssertTrue(json.contains("\"node_type\""))
        XCTAssertFalse(json.contains("\"nodeId\""))
    }
}
