import XCTest
@testable import FeralNodeSDK

/// Every adapter must:
///   * Declare a unique, non-empty capability string.
///   * Refuse to pretend to be wired — `attach(to:)` must throw
///     `FeralNodeError.adapterNotWired` until the vendor SDK is
///     linked in.
final class AdapterConformanceTests: XCTestCase {
    func testAllAdaptersExposeUniqueNonEmptyCapability() {
        let adapters: [VendorAdapter] = [
            VeepooAdapter(),
            JWBleAdapter(),
            QCSDKAdapter(),
        ]
        let caps = adapters.map(\.capability)
        XCTAssertEqual(Set(caps).count, caps.count, "adapter capability strings must be unique")
        for cap in caps {
            XCTAssertFalse(cap.isEmpty, "empty capability string")
        }
    }

    func testVeepooAdapterThrowsNotWired() async {
        let adapter = VeepooAdapter()
        let node = FeralNode(
            brainURL: URL(string: "wss://localhost:9090/v1/node")!,
            apiKey: "test",
            nodeID: "feral-phone-test"
        )
        do {
            try await adapter.attach(to: node)
            XCTFail("attach() should have thrown adapterNotWired")
        } catch FeralNodeError.adapterNotWired(let cap, _) {
            XCTAssertEqual(cap, "veepoo_wristband")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testJWBleAdapterThrowsNotWired() async {
        let adapter = JWBleAdapter()
        let node = FeralNode(
            brainURL: URL(string: "wss://localhost:9090/v1/node")!,
            apiKey: "test",
            nodeID: "feral-phone-test"
        )
        do {
            try await adapter.attach(to: node)
            XCTFail("attach() should have thrown adapterNotWired")
        } catch FeralNodeError.adapterNotWired(let cap, _) {
            XCTAssertEqual(cap, "jw_health_glasses")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testQCSDKAdapterThrowsNotWired() async {
        let adapter = QCSDKAdapter()
        let node = FeralNode(
            brainURL: URL(string: "wss://localhost:9090/v1/node")!,
            apiKey: "test",
            nodeID: "feral-phone-test"
        )
        do {
            try await adapter.attach(to: node)
            XCTFail("attach() should have thrown adapterNotWired")
        } catch FeralNodeError.adapterNotWired(let cap, _) {
            XCTAssertEqual(cap, "w610_glasses")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }
}
