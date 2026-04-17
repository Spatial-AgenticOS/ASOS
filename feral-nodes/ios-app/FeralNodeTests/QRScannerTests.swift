import XCTest
@testable import FeralBridge

final class QRScannerTests: XCTestCase {

    // MARK: - Expected QR Format: feral://pair?brain=...&token=...

    func testParseFeralProtocolQR() {
        let urlString = "feral://pair?brain=192.168.1.100:9090&token=abc123&name=my-phone"
        guard let components = URLComponents(string: urlString) else {
            XCTFail("Invalid URL")
            return
        }

        XCTAssertEqual(components.scheme, "feral")
        XCTAssertEqual(components.host, "pair")

        let params = (components.queryItems ?? []).reduce(into: [String: String]()) { $0[$1.name] = $1.value }
        XCTAssertEqual(params["brain"], "192.168.1.100:9090")
        XCTAssertEqual(params["token"], "abc123")
        XCTAssertEqual(params["name"], "my-phone")
    }

    func testParseFeralProtocolQR_withTLS() {
        let urlString = "feral://pair?brain=brain.example.com:9443&token=secure-key&tls=true"
        guard let components = URLComponents(string: urlString) else {
            XCTFail("Invalid URL")
            return
        }

        let params = (components.queryItems ?? []).reduce(into: [String: String]()) { $0[$1.name] = $1.value }
        XCTAssertEqual(params["brain"], "brain.example.com:9443")
        XCTAssertEqual(params["tls"], "true")
    }

    // MARK: - JSON QR Format (current implementation)

    func testParseJSONQR_validPairing() throws {
        let json = """
        {"host":"192.168.1.50","port":9090,"apiKey":"test-key","nodeName":"iphone-14"}
        """.data(using: .utf8)!

        let info = try XCTUnwrap(FeralBrainClient.parsePairingQR(json))
        XCTAssertEqual(info.host, "192.168.1.50")
        XCTAssertEqual(info.port, 9090)
        XCTAssertEqual(info.apiKey, "test-key")
        XCTAssertEqual(info.nodeName, "iphone-14")
    }

    func testParseJSONQR_invalidData() {
        XCTAssertNil(FeralBrainClient.parsePairingQR(Data()))
        XCTAssertNil(FeralBrainClient.parsePairingQR("random text".data(using: .utf8)!))
        XCTAssertNil(FeralBrainClient.parsePairingQR("{}".data(using: .utf8)!))
    }

    func testParseJSONQR_extraFieldsIgnored() throws {
        let json = """
        {"host":"10.0.0.1","port":9090,"apiKey":"k","nodeName":"n","extra":"ignored"}
        """.data(using: .utf8)!

        let info = try XCTUnwrap(FeralBrainClient.parsePairingQR(json))
        XCTAssertEqual(info.host, "10.0.0.1")
    }

    // MARK: - Edge Cases

    func testParseQR_emptyHost() {
        let json = """
        {"host":"","port":9090,"apiKey":"k","nodeName":"n"}
        """.data(using: .utf8)!

        let info = FeralBrainClient.parsePairingQR(json)
        XCTAssertNotNil(info)
        XCTAssertEqual(info?.host, "")
    }

    func testParseQR_largePort() throws {
        let json = """
        {"host":"h","port":65535,"apiKey":"k","nodeName":"n"}
        """.data(using: .utf8)!

        let info = try XCTUnwrap(FeralBrainClient.parsePairingQR(json))
        XCTAssertEqual(info.port, 65535)
    }
}
