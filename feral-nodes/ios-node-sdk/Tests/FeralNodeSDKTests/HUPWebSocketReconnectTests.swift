import XCTest
@testable import FeralNodeSDK

/// Verifies the backoff policy math used by `HUPWebSocket` for
/// reconnect. We don't drive a real WebSocket here — `URLSession`
/// can't be cleanly mocked from the SDK target without exposing
/// internals — but we can assert the policy values match HUP_SPEC
/// §2 exactly: initial 100 ms, factor 2, cap 30 s.
///
/// The actual reconnect loop is exercised end-to-end by the
/// host-app integration smoke tests (which run against a live
/// brain on `wss://localhost:9090/v1/node`) outside this package.
final class HUPWebSocketReconnectTests: XCTestCase {

    func testSpecBackoffMatchesHUPSpec() {
        let policy = HUPWebSocket.BackoffPolicy.spec
        XCTAssertEqual(policy.initialMs, 100)
        XCTAssertEqual(policy.capMs, 30_000)
        XCTAssertEqual(policy.factor, 2.0, accuracy: 0.0001)
    }

    /// Manually compute the reconnect attempt delays the spec
    /// policy yields and assert they grow then plateau at the cap.
    /// We mirror the math in `HUPWebSocket.reconnectWithBackoff`.
    func testSpecBackoffGrowsThenPlateaus() {
        let policy = HUPWebSocket.BackoffPolicy.spec
        var delayMs = policy.initialMs
        var sequence: [Int] = [delayMs]
        for _ in 0..<10 {
            delayMs = min(Int(Double(delayMs) * policy.factor), policy.capMs)
            sequence.append(delayMs)
        }
        // First step: 100 → 200; second: 400; third: 800; ...
        // Ninth: would be 25_600; tenth: capped at 30_000.
        XCTAssertEqual(sequence[0], 100)
        XCTAssertEqual(sequence[1], 200)
        XCTAssertEqual(sequence[2], 400)
        XCTAssertEqual(sequence[3], 800)
        XCTAssertEqual(sequence[4], 1_600)
        XCTAssertEqual(sequence[5], 3_200)
        XCTAssertEqual(sequence[6], 6_400)
        XCTAssertEqual(sequence[7], 12_800)
        XCTAssertEqual(sequence[8], 25_600)
        // Geometric progression hits the 30s cap by step 9.
        XCTAssertEqual(sequence[9], 30_000)
        XCTAssertEqual(sequence[10], 30_000)
    }

    /// Custom backoff policy is accepted by the initializer (used
    /// by the host-app deterministic-time tests to shrink the cap
    /// for unit-test latency).
    func testCustomBackoffPolicy() {
        let policy = HUPWebSocket.BackoffPolicy(initialMs: 10, capMs: 50, factor: 3.0)
        XCTAssertEqual(policy.initialMs, 10)
        XCTAssertEqual(policy.capMs, 50)
        XCTAssertEqual(policy.factor, 3.0, accuracy: 0.0001)

        let url = URL(string: "wss://localhost:9090/v1/node")!
        let socket = HUPWebSocket(url: url, apiKey: "x", backoff: policy)
        // We can't observe the policy directly post-construction, but
        // we verify the actor was constructed without error.
        XCTAssertNotNil(socket)
    }

    /// Phase-0.5 stability hardening: the SDK must accept a `nil`
    /// session and own its own URLSession internally. The legacy
    /// signature `session: URLSession = .shared` shipped a session
    /// that drops long-lived WebSockets on iOS; the new default
    /// builds a per-instance session with `waitsForConnectivity`,
    /// 30 s request timeout, unlimited resource timeout, and
    /// extended-background-idle mode. Hosts can still inject their
    /// own URLSession (e.g. for tests) by passing it explicitly.
    func testSessionInjectionIsOptional() {
        let url = URL(string: "wss://localhost:9090/v1/node")!

        // Default — session gets built lazily inside the actor.
        let defaultSocket = HUPWebSocket(url: url, apiKey: "x")
        XCTAssertNotNil(defaultSocket)

        // Explicit injection still works for tests that want to
        // observe URLSessionConfiguration (e.g. inspect requests).
        let cfg = URLSessionConfiguration.ephemeral
        let injected = URLSession(configuration: cfg)
        let injectedSocket = HUPWebSocket(url: url, apiKey: "x", session: injected)
        XCTAssertNotNil(injectedSocket)
    }
}
