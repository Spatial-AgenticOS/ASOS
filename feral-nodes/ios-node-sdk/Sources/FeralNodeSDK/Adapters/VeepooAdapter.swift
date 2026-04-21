import Foundation

/// Theora wristband adapter — wraps VeepooBleSDK.framework.
///
/// Awaiting SDK wire-up. When you're ready to ship this for real:
///
/// 1. Drag `~/Desktop/Theora-backend-ML/wristband/iOS_sdk_source/
///    Framework/2.2.XX.15/VeepooBleSDK.framework` into the host
///    Xcode project. SwiftPM can't consume static frameworks in
///    this repo layout, so linkage happens at the app target level.
/// 2. Add the Obj-C bridging imports:
///      import VeepooBleSDK
///      // or via an umbrella header if using a bridging header
/// 3. Replace the `attach(to:)` body below with the real
///    `VPBleCentralManager.sharedBleManager` setup + peripheral
///    delegate wiring.
/// 4. Translate per-metric callbacks into `node.emit(eventType:data:)`
///    with the kind strings the brain expects (`heart_rate`, `spo2`,
///    `skin_temperature`, `steps`).
/// 5. For haptic: bind the brain's inbound `hup_action_request`
///    with `name: "buzz"` to the Veepoo vibration method.
///
/// Reference docs:
///   ~/Desktop/Theora-backend-ML/wristband/iOS_sdk_source/doc/
///     VeepooSDK iOS Api_en.md
public final class VeepooAdapter: VendorAdapter {
    public let capability: String = "veepoo_wristband"

    public init() {}

    public func attach(to node: FeralNode) async throws {
        throw FeralNodeError.adapterNotWired(
            capability: capability,
            reason: "VeepooBleSDK.framework is not linked into the host app. " +
                    "See feral-nodes/ios-node-sdk/README.md → Vendor adapter " +
                    "status → VeepooAdapter for the five-step wire-up checklist."
        )
    }

    public func detach() async {
        // No-op until wire-up; at that point this unsubscribes every
        // Veepoo delegate callback the adapter holds.
    }

    public func canHandleAction(named name: String) async -> Bool {
        // Reserved for the production wire-up — Veepoo's haptic
        // is the main inbound action we care about.
        return name == "buzz"
    }

    public func handleAction(frame: HUPFrame, node: FeralNode) async {
        // After wire-up this calls into VPBleCentralManager for
        // the vibration command. Right now it logs + no-ops so the
        // intent is documented but no fake GATT write fires.
        NSLog("VeepooAdapter.handleAction(%@) awaiting SDK wire-up", String(describing: frame.type))
    }
}
