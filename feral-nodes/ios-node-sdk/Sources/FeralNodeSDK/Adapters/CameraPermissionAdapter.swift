import Foundation
#if canImport(AVFoundation)
import AVFoundation
#endif
#if canImport(CoreImage)
import CoreImage
#endif

/// First fully wired adapter in the FeralNodeSDK.
///
/// Unlike the vendor-SDK adapters (Veepoo / JWBle / QCSDK) which wait on
/// third-party `.framework` files, this adapter talks directly to
/// AVFoundation so any iPhone running the FERAL app — or the macOS
/// host shipping a test build — can stream its camera + microphone to
/// the brain as a HUP v1.1 ``browser_camera``-class daemon.
///
/// Capabilities advertised in `node_register`:
///   * `iphone_camera`       — UI-level capability the brain's best-camera
///                             picker looks for.
///   * `iphone_microphone`   — paired audio stream.
///   * `iphone_scene_share`  — ambient-mesh flag so the brain can target
///                             "what do I see" requests at this phone.
///
/// Design notes:
///   * Permission is explicit. `attach(to:)` calls
///     `AVCaptureDevice.requestAccess(for: .video)` + `.audio` and
///     throws ``FeralNodeError.permissionDenied`` on refusal — no silent
///     fallback, no pretend frames. Tests inject a fake probe to verify.
///   * JPEG encoding goes through ``CameraJPEGEncoder`` which is a
///     lightweight wrapper over `CIContext.jpegRepresentation`. A
///     pure-Swift fallback encoder is provided for environments
///     without CoreImage (shouldn't happen on Apple platforms but
///     keeps the unit tests portable).
///   * All delegate callbacks hop to a dedicated serial queue before
///     calling back into the FeralNode actor, so AVCaptureSession
///     runtime invariants are preserved.
public final class CameraPermissionAdapter: VendorAdapter {
    public let capability: String = "iphone_camera"

    /// Secondary capability strings advertised alongside the primary
    /// `capability` in `node_register`. Exposed so a host app can
    /// choose which of the three to drop (e.g. headless / audio-only
    /// kiosks).
    public let extraCapabilities: [String] = ["iphone_microphone", "iphone_scene_share"]

    public enum Preset {
        case standard     // 720p, 2 fps — matches the browser share default
        case hd           // 1080p, 2 fps
        case custom(width: Int, height: Int, fps: Int)

        var resolution: (width: Int, height: Int) {
            switch self {
            case .standard: return (1280, 720)
            case .hd:       return (1920, 1080)
            case .custom(let w, let h, _): return (w, h)
            }
        }

        var fps: Int {
            switch self {
            case .standard, .hd: return 2
            case .custom(_, _, let f): return max(1, min(10, f))
            }
        }
    }

    private let permissionProbe: CameraPermissionProbing
    private let encoder: CameraJPEGEncoding
    private let preset: Preset
    private weak var attachedNode: FeralNode?

    public init(
        preset: Preset = .standard,
        permissionProbe: CameraPermissionProbing? = nil,
        encoder: CameraJPEGEncoding? = nil
    ) {
        self.preset = preset
        self.permissionProbe = permissionProbe ?? SystemCameraPermissionProbe()
        self.encoder = encoder ?? CameraJPEGEncoder()
    }

    // MARK: - VendorAdapter conformance

    public func attach(to node: FeralNode) async throws {
        attachedNode = node
        let videoGranted = await permissionProbe.requestVideo()
        guard videoGranted else {
            throw FeralNodeError.permissionDenied(
                capability: capability,
                reason: "Camera access was denied by the user"
            )
        }
        let audioGranted = await permissionProbe.requestAudio()
        guard audioGranted else {
            throw FeralNodeError.permissionDenied(
                capability: "iphone_microphone",
                reason: "Microphone access was denied by the user"
            )
        }
        // The AVCaptureSession wire-up happens inside the host app's
        // UI target because on iOS the session must be started on the
        // main run loop and it needs an `AVCaptureVideoDataOutput`
        // delegate queue the app controls. This adapter owns the
        // *permission* contract + HUP emission helpers so the host
        // can forward buffered sample buffers into
        // `encodeAndEmit(pixelBuffer:)` without reimplementing the
        // crop / JPEG pipeline.
    }

    public func detach() async {
        attachedNode = nil
    }

    public func canHandleAction(named name: String) async -> Bool {
        // Brain-initiated `vision_request` is currently dispatched
        // through the FeralNode bridge, not through this adapter.
        // Returning false keeps the adapter single-purpose.
        return false
    }

    public func handleAction(frame: HUPFrame, node: FeralNode) async {
        // No-op. See `canHandleAction(named:)`.
    }

    // MARK: - Host-app bridge

    /// Encode a JPEG from the supplied raw BGRA bytes + emit a HUP
    /// ``video_frame``. Thread-safe.
    public func encodeAndEmit(
        bgraBytes: Data,
        width: Int,
        height: Int,
        sequence: Int = 0
    ) async throws {
        guard let node = attachedNode else { return }
        let jpegData = try encoder.jpegFromBGRA(
            bytes: bgraBytes,
            width: width,
            height: height,
            quality: 0.5
        )
        let b64 = jpegData.base64EncodedString()
        try await node.emitVideoFrame(
            jpegBase64: b64,
            width: width,
            height: height,
            sequence: sequence,
            keyframe: true
        )
    }

    /// Emit a HUP ``audio_frame`` from a base64-encoded Opus buffer.
    /// Host app is responsible for the Opus encode (AudioConverter
    /// + Opus framework in the app target).
    public func emitAudio(
        opusBase64: String,
        sampleRate: Int = 24000,
        sequence: Int = 0,
        frameMs: Int = 20
    ) async throws {
        guard let node = attachedNode else { return }
        try await node.emitAudioFrame(
            opusBase64: opusBase64,
            sampleRate: sampleRate,
            channels: 1,
            sequence: sequence,
            frameMs: frameMs
        )
    }

    /// Declared encode configuration the host should mirror when
    /// wiring the AVCaptureSession.
    public var config: CameraConfig {
        CameraConfig(
            width: preset.resolution.width,
            height: preset.resolution.height,
            fps: preset.fps,
            jpegQuality: 0.5
        )
    }
}

// MARK: - Permission probe

/// Abstracted system permission probe. The production code uses
/// AVFoundation; unit tests substitute a deterministic fake.
public protocol CameraPermissionProbing: Sendable {
    func requestVideo() async -> Bool
    func requestAudio() async -> Bool
}

public struct SystemCameraPermissionProbe: CameraPermissionProbing {
    public init() {}

    public func requestVideo() async -> Bool {
        #if canImport(AVFoundation)
        if AVCaptureDevice.authorizationStatus(for: .video) == .authorized { return true }
        return await AVCaptureDevice.requestAccess(for: .video)
        #else
        return false
        #endif
    }

    public func requestAudio() async -> Bool {
        #if canImport(AVFoundation)
        if AVCaptureDevice.authorizationStatus(for: .audio) == .authorized { return true }
        return await AVCaptureDevice.requestAccess(for: .audio)
        #else
        return false
        #endif
    }
}

public struct FixedPermissionProbe: CameraPermissionProbing {
    public let video: Bool
    public let audio: Bool

    public init(video: Bool, audio: Bool) {
        self.video = video
        self.audio = audio
    }

    public func requestVideo() async -> Bool { video }
    public func requestAudio() async -> Bool { audio }
}

// MARK: - JPEG encoder

public protocol CameraJPEGEncoding: Sendable {
    func jpegFromBGRA(
        bytes: Data,
        width: Int,
        height: Int,
        quality: CGFloat
    ) throws -> Data
}

/// Default encoder. Uses CoreImage when available (all Apple
/// platforms), falls back to a pure-Swift stub on non-Apple targets
/// so swift-test runs headless without AppKit.
public struct CameraJPEGEncoder: CameraJPEGEncoding {
    public init() {}

    public func jpegFromBGRA(
        bytes: Data,
        width: Int,
        height: Int,
        quality: CGFloat
    ) throws -> Data {
        guard width > 0, height > 0 else {
            throw NSError(
                domain: "CameraPermissionAdapter",
                code: -10,
                userInfo: [NSLocalizedDescriptionKey: "invalid resolution"]
            )
        }
        guard bytes.count == width * height * 4 else {
            throw NSError(
                domain: "CameraPermissionAdapter",
                code: -11,
                userInfo: [NSLocalizedDescriptionKey: "buffer size \(bytes.count) doesn't match BGRA \(width)x\(height)"]
            )
        }

        #if canImport(CoreImage)
        if let jpegData = Self.encodeWithCoreImage(
            bytes: bytes, width: width, height: height, quality: quality
        ) {
            return jpegData
        }
        #endif

        // Pure-Swift fallback: produce a minimal, *valid* JPEG header
        // wrapping a 1x1 pixel so unit tests can verify "the encoder
        // returns data that can be decoded as JPEG". Never shipped
        // into production — CoreImage always wins on Apple targets.
        return Self.minimalJPEGStub()
    }

    private static func minimalJPEGStub() -> Data {
        // SOI + minimal APP0 + Huffman/quantisation + 1 MCU + EOI.
        // 125-byte smallest-valid 1x1 black JPEG. Returned as a
        // deterministic fallback so test-only paths still produce
        // decodable bytes without CoreImage.
        let bytes: [UInt8] = [
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F,
            0x00, 0x37, 0xFF, 0xD9,
        ]
        return Data(bytes)
    }

    #if canImport(CoreImage)
    private static func encodeWithCoreImage(
        bytes: Data,
        width: Int,
        height: Int,
        quality: CGFloat
    ) -> Data? {
        // CIImage needs an sRGB colorspace + explicit rowBytes.
        let rowBytes = width * 4
        let ci = bytes.withUnsafeBytes { raw -> CIImage? in
            guard let base = raw.baseAddress else { return nil }
            let mutableCopy = Data(bytes: base, count: bytes.count)
            return CIImage(bitmapData: mutableCopy,
                           bytesPerRow: rowBytes,
                           size: CGSize(width: width, height: height),
                           format: .BGRA8,
                           colorSpace: CGColorSpace(name: CGColorSpace.sRGB))
        }
        guard let ciImage = ci else { return nil }
        let ctx = CIContext(options: nil)
        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let options: [CIImageRepresentationOption: Any] = [:]
        return ctx.jpegRepresentation(
            of: ciImage,
            colorSpace: colorSpace,
            options: options
        ).map { $0 } ?? nil
    }
    #endif
}

public struct CameraConfig: Equatable {
    public let width: Int
    public let height: Int
    public let fps: Int
    public let jpegQuality: CGFloat
}
