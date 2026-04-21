import Foundation

/// Theora health glasses adapter — wraps JWBle.framework (Obj-C).
///
/// Awaiting SDK wire-up. Wire-up checklist:
///
/// 1. Drag these frameworks into the host Xcode project from
///    `~/Desktop/Theora-backend-ML/Ble-Demo-iOS/iOS/SDK/`:
///      - JWBle.framework
///      - CocoaLumberjack.framework
///      - FMDB
///      - RTKAudioConnectSDK.framework
///      - RTKLEFoundation.framework
///      - RTKOTASDK.framework
/// 2. Disable ENABLE_BITCODE on the target (per JW docs).
/// 3. Add `NSBluetoothAlwaysUsageDescription` to Info.plist.
/// 4. During `attach(to:)` call
///      `[JWBleManager.shareInstance setUpWithUid:@"programmer"];`
///    (substitute a real uid in production).
/// 5. Route JW delegate callbacks into
///    `node.emit(eventType:data:)` for the live telemetry streams
///    the glasses expose.
///
/// Reference docs:
///   ~/Desktop/Theora-backend-ML/Ble-Demo-iOS/iOS/Document/
///     English Description.md
public final class JWBleAdapter: VendorAdapter {
    public let capability: String = "jw_health_glasses"

    public init() {}

    public func attach(to node: FeralNode) async throws {
        throw FeralNodeError.adapterNotWired(
            capability: capability,
            reason: "JWBle.framework and its four companion frameworks " +
                    "are not linked into the host app. See feral-nodes/" +
                    "ios-node-sdk/README.md → Vendor adapter status → " +
                    "JWBleAdapter for the five-step wire-up checklist."
        )
    }

    public func detach() async {
        // No-op until wire-up.
    }

    public func canHandleAction(named name: String) async -> Bool {
        // Known JW actions — add to this list as the SDK surface
        // is explored. OTA is gated behind a separate capability
        // string so the brain won't dispatch it unless explicitly
        // enabled in the host app build.
        return ["health_measure", "display_text"].contains(name)
    }

    public func handleAction(frame: HUPFrame, node: FeralNode) async {
        NSLog("JWBleAdapter.handleAction(%@) awaiting SDK wire-up", String(describing: frame.type))
    }
}
