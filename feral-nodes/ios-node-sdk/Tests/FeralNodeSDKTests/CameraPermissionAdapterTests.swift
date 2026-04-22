import XCTest
@testable import FeralNodeSDK

final class CameraPermissionAdapterTests: XCTestCase {
    func testCameraPermissionAdapterCapabilities() {
        let adapter = CameraPermissionAdapter()
        XCTAssertEqual(adapter.capability, "iphone_camera")
        XCTAssertEqual(
            adapter.extraCapabilities,
            ["iphone_microphone", "iphone_scene_share"],
            "the adapter must advertise the three browser-share-compatible capabilities"
        )
    }

    func testAttachSucceedsWhenPermissionGranted() async {
        let adapter = CameraPermissionAdapter(
            permissionProbe: FixedPermissionProbe(video: true, audio: true)
        )
        let node = FeralNode(
            brainURL: URL(string: "wss://localhost:9090/v1/node")!,
            apiKey: "test",
            nodeID: "feral-phone-test"
        )
        do {
            try await adapter.attach(to: node)
        } catch {
            XCTFail("attach() should succeed when probe returns true, got: \(error)")
        }
    }

    func testAttachThrowsWhenVideoPermissionDenied() async {
        let adapter = CameraPermissionAdapter(
            permissionProbe: FixedPermissionProbe(video: false, audio: true)
        )
        let node = FeralNode(
            brainURL: URL(string: "wss://localhost:9090/v1/node")!,
            apiKey: "test",
            nodeID: "feral-phone-test"
        )
        do {
            try await adapter.attach(to: node)
            XCTFail("attach() should have thrown permissionDenied")
        } catch FeralNodeError.permissionDenied(let cap, _) {
            XCTAssertEqual(cap, "iphone_camera")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testAttachThrowsWhenAudioPermissionDenied() async {
        let adapter = CameraPermissionAdapter(
            permissionProbe: FixedPermissionProbe(video: true, audio: false)
        )
        let node = FeralNode(
            brainURL: URL(string: "wss://localhost:9090/v1/node")!,
            apiKey: "test",
            nodeID: "feral-phone-test"
        )
        do {
            try await adapter.attach(to: node)
            XCTFail("attach() should have thrown permissionDenied for microphone")
        } catch FeralNodeError.permissionDenied(let cap, _) {
            XCTAssertEqual(cap, "iphone_microphone")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testJpegEncoderProducesValidImage() throws {
        let encoder = CameraJPEGEncoder()
        let width = 4
        let height = 4
        // 4x4 BGRA checkerboard — deterministic, non-zero, fits the
        // BGRA size requirement so the encoder exercises the happy path.
        var bytes = [UInt8](repeating: 0, count: width * height * 4)
        for i in 0..<(width * height) {
            let base = i * 4
            let on = (i % 2 == 0)
            bytes[base + 0] = on ? 0xFF : 0x00  // B
            bytes[base + 1] = on ? 0xFF : 0x00  // G
            bytes[base + 2] = on ? 0xFF : 0x00  // R
            bytes[base + 3] = 0xFF              // A
        }
        let data = Data(bytes)
        let jpeg = try encoder.jpegFromBGRA(bytes: data, width: width, height: height, quality: 0.6)
        XCTAssertGreaterThan(jpeg.count, 50, "JPEG output should be non-trivial")
        // SOI marker present at the start of every valid JPEG.
        XCTAssertEqual(jpeg[0], 0xFF)
        XCTAssertEqual(jpeg[1], 0xD8)
        // EOI marker present at the end.
        XCTAssertEqual(jpeg[jpeg.count - 2], 0xFF)
        XCTAssertEqual(jpeg[jpeg.count - 1], 0xD9)
    }

    func testJpegEncoderRejectsBufferSizeMismatch() {
        let encoder = CameraJPEGEncoder()
        let mismatched = Data([0x00, 0x01, 0x02, 0x03])
        XCTAssertThrowsError(
            try encoder.jpegFromBGRA(bytes: mismatched, width: 8, height: 8, quality: 0.5)
        )
    }

    func testConfigMatchesPreset() {
        let standard = CameraPermissionAdapter(preset: .standard)
        XCTAssertEqual(standard.config.width, 1280)
        XCTAssertEqual(standard.config.height, 720)
        XCTAssertEqual(standard.config.fps, 2)

        let hd = CameraPermissionAdapter(preset: .hd)
        XCTAssertEqual(hd.config.width, 1920)
        XCTAssertEqual(hd.config.height, 1080)

        let custom = CameraPermissionAdapter(preset: .custom(width: 640, height: 480, fps: 5))
        XCTAssertEqual(custom.config.width, 640)
        XCTAssertEqual(custom.config.height, 480)
        XCTAssertEqual(custom.config.fps, 5)
    }
}
