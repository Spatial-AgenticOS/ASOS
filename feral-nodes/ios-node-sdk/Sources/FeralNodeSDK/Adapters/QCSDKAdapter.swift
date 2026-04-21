import Foundation

/// W610 open-source Meta-Ray-Ban-style glasses adapter — wraps
/// QCSDK.framework. The Moshi voice-streaming LLM scaffolding that
/// ships alongside (moshi-swift) is separately wired; this adapter
/// focuses on the BLE + camera + audio pipeline, not the LLM.
///
/// Awaiting SDK wire-up. Wire-up checklist:
///
/// 1. Drag `~/Desktop/Theora-backend-ML/W610/QCSDKDemo/QCSDK.framework`
///    into the host Xcode project.
/// 2. Follow the scan + connect sequence in
///    `~/Desktop/Theora-backend-ML/W610/QCSDKDemo/
///    iOS_SDK_Development_Guide.pdf`.
/// 3. Route video frames through `node.emitVideoFrame(jpegBase64:
///    width: height: sequence: keyframe:)` — brain enforces 512 KiB
///    per JPEG.
/// 4. Route audio frames through `node.emitAudioFrame(opusBase64:
///    sampleRate: channels: sequence: frameMs:)` — brain enforces
///    64 KiB per Opus packet.
/// 5. If the Moshi pipeline is desired, bridge moshi-swift here
///    behind a `w610_moshi` capability flag so builds without it
///    don't advertise a surface they can't service.
public final class QCSDKAdapter: VendorAdapter {
    public let capability: String = "w610_glasses"

    public init() {}

    public func attach(to node: FeralNode) async throws {
        throw FeralNodeError.adapterNotWired(
            capability: capability,
            reason: "QCSDK.framework is not linked into the host app. " +
                    "See feral-nodes/ios-node-sdk/README.md → Vendor " +
                    "adapter status → QCSDKAdapter for the five-step " +
                    "wire-up checklist."
        )
    }

    public func detach() async {
        // No-op until wire-up.
    }

    public func canHandleAction(named name: String) async -> Bool {
        return ["display_hud", "capture_frame", "start_recording", "stop_recording"].contains(name)
    }

    public func handleAction(frame: HUPFrame, node: FeralNode) async {
        NSLog("QCSDKAdapter.handleAction(%@) awaiting SDK wire-up", String(describing: frame.type))
    }
}
