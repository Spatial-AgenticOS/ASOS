import Foundation

public enum FeralNodeSDKInfo {
    public static let version = "0.1.0-scaffold"
    public static let hupVersion = "1.1.0"
}

public enum FeralNodeError: Error, LocalizedError {
    /// The vendor adapter was compiled into the package but its
    /// vendor-SDK wire-up has not been completed. Thrown deliberately
    /// so a build never silently succeeds with fake data.
    case adapterNotWired(capability: String, reason: String)
    case notConnected
    case brainRejected(code: Int, message: String)
    case malformedFrame(underlying: Error)

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
        }
    }
}
