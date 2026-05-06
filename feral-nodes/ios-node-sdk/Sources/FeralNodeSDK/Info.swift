import Foundation

public enum FeralNodeSDKInfo {
    public static let version = "0.2.0"
    /// HUP wire-protocol version this SDK implements. Bumped from 1.2.0
    /// when phone-as-peer envelopes (chat_request, voice_session_start,
    /// audio_chunk) and the action_response sender landed.
    /// `feral-core/models/protocol.py` reports 1.3.1; we declare 1.3.0
    /// because the SDK does not yet emit the v1.3.1-only `location_update`
    /// shape — adding it is a v0.3 follow-up.
    public static let hupVersion = "1.3.0"
}

public enum FeralNodeError: Error, LocalizedError {
    /// The vendor adapter was compiled into the package but its
    /// vendor-SDK wire-up has not been completed. Thrown deliberately
    /// so a build never silently succeeds with fake data.
    case adapterNotWired(capability: String, reason: String)
    case notConnected
    case brainRejected(code: Int, message: String)
    case malformedFrame(underlying: Error)
    /// The user denied a system permission prompt (camera, microphone,
    /// location, etc.). Never silently retried — the adapter surfaces
    /// this so the host app can either guide the user to Settings or
    /// disable the capability entirely.
    case permissionDenied(capability: String, reason: String)

    public var errorDescription: String? {
        switch self {
        case .adapterNotWired(let capability, let reason):
            return "FeralNodeSDK adapter \(capability) is not wired: \(reason). " +
                   "See feral-nodes/ios-node-sdk/README.md → Vendor adapter status."
        case .notConnected:
            return "FeralNode is not connected to the brain."
        case .brainRejected(let code, let message):
            return "Brain rejected the frame (code \(code)): \(message)."
        case .malformedFrame(let underlying):
            return "Malformed HUP frame: \(underlying.localizedDescription)."
        case .permissionDenied(let capability, let reason):
            return "FeralNodeSDK adapter \(capability) could not start: \(reason). " +
                   "The user must grant this permission in system Settings."
        }
    }
}
