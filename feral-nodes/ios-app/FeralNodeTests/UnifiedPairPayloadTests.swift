import XCTest
@testable import FeralBridge

/// Phase 5 / C5.1 — unified QR v1 payload + legacy backward-compat
/// decoder tests. Asserts the contract from
/// `.internal/audit-v2026.5.5/A4-pairing-redesign.md` §4 + §7.
final class UnifiedPairPayloadTests: XCTestCase {

    // ── 1. Unified v1 payload ──────────────────────────────────────

    func testParseV1_localMode_succeeds() throws {
        let json = """
        {"v":1,"mode":"local","url":"http://192.168.1.50:9090/pair?t=abc",
         "token":"abc","brain_id":"bid-1","expires":9999999999,"name":"FERAL Brain"}
        """.data(using: .utf8)!
        let decoded = try XCTUnwrap(FeralBrainClient.parsePairingPayload(json))
        XCTAssertFalse(decoded.isLegacy)
        XCTAssertEqual(decoded.token, "abc")
        XCTAssertEqual(decoded.brainId, "bid-1")
        XCTAssertEqual(decoded.brainURL.absoluteString, "http://192.168.1.50:9090/pair?t=abc")
    }

    func testParseV1_remoteMode_httpsTunnel() throws {
        let json = """
        {"v":1,"mode":"remote","url":"https://feral.tail123.ts.net/pair?t=tt",
         "token":"tt","brain_id":"bid-2","expires":1,"name":"FERAL Brain"}
        """.data(using: .utf8)!
        let decoded = try XCTUnwrap(FeralBrainClient.parsePairingPayload(json))
        XCTAssertEqual(decoded.brainURL.scheme, "https")
        XCTAssertEqual(decoded.brainURL.host, "feral.tail123.ts.net")
        XCTAssertFalse(decoded.isLegacy)
    }

    // ── 2. Legacy {host,port,apiKey,nodeName} (pre-2026.5.8 iOS QR) ─

    func testParseLegacy_apiKeyShape_marksLegacy() throws {
        let json = """
        {"host":"192.168.1.50","port":9090,"apiKey":"k1","nodeName":"iphone"}
        """.data(using: .utf8)!
        let decoded = try XCTUnwrap(FeralBrainClient.parsePairingPayload(json))
        XCTAssertTrue(decoded.isLegacy)
        XCTAssertEqual(decoded.token, "k1")
        XCTAssertEqual(decoded.name, "iphone")
        XCTAssertEqual(decoded.brainURL.absoluteString, "http://192.168.1.50:9090")
        XCTAssertNil(decoded.brainId)
    }

    // ── 3. Legacy {host,port,token,name} (pre-2026.5.8 brain mode=app) ─

    func testParseLegacy_tokenShape_marksLegacy() throws {
        let json = """
        {"host":"10.0.0.1","port":9090,"token":"tt","name":"FERAL Brain"}
        """.data(using: .utf8)!
        let decoded = try XCTUnwrap(FeralBrainClient.parsePairingPayload(json))
        XCTAssertTrue(decoded.isLegacy)
        XCTAssertEqual(decoded.token, "tt")
        XCTAssertEqual(decoded.name, "FERAL Brain")
    }

    // ── 4. feral://pair?p=<base64url-json> deep-link form ──────────

    func testParseFeralDeepLink_unwrapsPayload() throws {
        // Base64url-encode the v1 payload; FERAL deep links carry the
        // payload via ?p=…
        let payloadJSON = """
        {"v":1,"mode":"local","url":"http://10.0.0.5:9090/pair?t=zz",
         "token":"zz","brain_id":"b","expires":1,"name":"FERAL Brain"}
        """
        let raw = payloadJSON.data(using: .utf8)!
        let b64url = raw.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        let url = "feral://pair?p=\(b64url)".data(using: .utf8)!

        let decoded = try XCTUnwrap(FeralBrainClient.parsePairingPayload(url))
        XCTAssertEqual(decoded.token, "zz")
        XCTAssertFalse(decoded.isLegacy)
    }

    // ── 5. Plain https://<brain>/pair?t=<token> ───────────────────

    func testParseHttpsPairURL() throws {
        let url = "https://feral.tail123.ts.net/pair?t=https-token".data(using: .utf8)!
        let decoded = try XCTUnwrap(FeralBrainClient.parsePairingPayload(url))
        XCTAssertEqual(decoded.token, "https-token")
        XCTAssertEqual(decoded.brainURL.scheme, "https")
        XCTAssertEqual(decoded.brainURL.host, "feral.tail123.ts.net")
    }

    // ── Negative ──────────────────────────────────────────────────

    func testRejectsArbitraryGarbage() {
        XCTAssertNil(FeralBrainClient.parsePairingPayload(Data()))
        XCTAssertNil(FeralBrainClient.parsePairingPayload("not json".data(using: .utf8)!))
        XCTAssertNil(FeralBrainClient.parsePairingPayload("{}".data(using: .utf8)!))
        XCTAssertNil(FeralBrainClient.parsePairingPayload("https://no-token".data(using: .utf8)!))
    }
}
