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
        XCTAssertEqual(decoded.hupVersion, "1.2.0")
        if case .string(let s) = decoded.payload["event_type"] ?? .null {
            XCTAssertEqual(s, "heart_rate")
        } else {
            XCTFail("event_type did not decode as string")
        }
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
