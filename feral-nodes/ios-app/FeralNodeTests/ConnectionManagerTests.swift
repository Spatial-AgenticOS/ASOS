import XCTest
@testable import FeralBridge

final class ConnectionManagerTests: XCTestCase {

    // MARK: - PairingInfo Parsing

    func testParsePairingQR_validJSON() throws {
        let json = """
        {"host":"192.168.1.50","port":9090,"apiKey":"test-key-123","nodeName":"test-iphone"}
        """.data(using: .utf8)!

        let info = FeralBrainClient.parsePairingQR(json)
        XCTAssertNotNil(info)
        XCTAssertEqual(info?.host, "192.168.1.50")
        XCTAssertEqual(info?.port, 9090)
        XCTAssertEqual(info?.apiKey, "test-key-123")
        XCTAssertEqual(info?.nodeName, "test-iphone")
    }

    func testParsePairingQR_invalidJSON() {
        let garbage = "not-a-json-string".data(using: .utf8)!
        let info = FeralBrainClient.parsePairingQR(garbage)
        XCTAssertNil(info)
    }

    func testParsePairingQR_missingFields() {
        let partial = """
        {"host":"10.0.0.1"}
        """.data(using: .utf8)!
        let info = FeralBrainClient.parsePairingQR(partial)
        XCTAssertNil(info, "Should fail when required fields are missing")
    }

    func testParsePairingQR_expectedFormat() throws {
        let qr = """
        {"host":"brain.local","port":9443,"apiKey":"abc","nodeName":"My iPhone"}
        """.data(using: .utf8)!
        let info = try XCTUnwrap(FeralBrainClient.parsePairingQR(qr))
        XCTAssertEqual(info.host, "brain.local")
        XCTAssertEqual(info.port, 9443)
    }

    // MARK: - Connection State

    func testClientInitialState() {
        let client = FeralBrainClient(host: "localhost", port: 9090)
        XCTAssertFalse(client.isConnected)
        XCTAssertEqual(client.connectionState, .disconnected)
    }

    func testClientDisconnect() {
        let client = FeralBrainClient(host: "localhost", port: 9090)
        client.disconnect()
        XCTAssertFalse(client.isConnected)
        XCTAssertEqual(client.connectionState, .disconnected)
    }

    // MARK: - Reconnect Logic

    func testReconnectCounterIncrements() {
        let client = FeralBrainClient(host: "unreachable.invalid", port: 9999)
        XCTAssertFalse(client.isConnected)
        client.disconnect()
        XCTAssertEqual(client.connectionState, .disconnected)
    }

    // MARK: - URL Construction

    func testWSURLConstruction() {
        let client = FeralBrainClient(host: "192.168.1.100", port: 9090, useTLS: false)
        XCTAssertFalse(client.useTLS)

        let tlsClient = FeralBrainClient(host: "brain.example.com", port: 9443, useTLS: true)
        XCTAssertTrue(tlsClient.useTLS)
    }

    // MARK: - Message Parsing

    func testPairingInfoEncodeDecode() throws {
        let original = PairingInfo(host: "10.0.0.5", port: 9090, apiKey: "key-abc", nodeName: "dev-phone")
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(PairingInfo.self, from: data)
        XCTAssertEqual(decoded.host, original.host)
        XCTAssertEqual(decoded.port, original.port)
        XCTAssertEqual(decoded.apiKey, original.apiKey)
        XCTAssertEqual(decoded.nodeName, original.nodeName)
    }
}
