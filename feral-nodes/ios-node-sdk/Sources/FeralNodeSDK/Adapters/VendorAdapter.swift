import Foundation

/// Protocol every vendor-SDK adapter in this package conforms to.
/// A FeralNode hosts N adapters concurrently; each translates a
/// vendor SDK's delegate callbacks into HUP v1.1 device_event frames
/// via ``FeralNode.emit(eventType:data:)`` / ``emitVideoFrame`` /
/// ``emitAudioFrame``.
public protocol VendorAdapter: AnyObject {
    /// Short identifier surfaced in node_register.capabilities.
    /// Examples: "veepoo_wristband", "jw_health_glasses",
    /// "w610_glasses". Must be unique within a single FeralNode.
    var capability: String { get }

    /// Wire the vendor SDK callbacks onto the node's emit path.
    /// Called once after FeralNode has completed its node_register
    /// handshake with the brain.
    ///
    /// Throws ``FeralNodeError.adapterNotWired`` while the adapter
    /// is in its scaffold state — no fake data, no pretend BLE.
    func attach(to node: FeralNode) async throws

    /// Clean shutdown when the node disconnects or the app moves
    /// to background. Must release every BLE subscription the SDK
    /// holds.
    func detach() async

    /// Called on inbound hup_action_request frames. Return true if
    /// this adapter handles the named action (e.g. VeepooAdapter
    /// handles "buzz").
    func canHandleAction(named name: String) async -> Bool

    /// Actually execute the action. Only called when
    /// ``canHandleAction(named:)`` returned true.
    func handleAction(frame: HUPFrame, node: FeralNode) async
}
