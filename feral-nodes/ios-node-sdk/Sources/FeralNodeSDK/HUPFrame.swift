import Foundation

/// Codable mirror of the HUP wire frame. Matches
/// `feral-nodes/HUP_SPEC.md` §5 — any drift here breaks the
/// handshake with the brain.
///
/// Decoding is deliberately tolerant:
///   * `hup_version` is optional on inbound (some brain frames in
///     ad-hoc routes — mesh `hup_action_request`, raw `node_ack` over
///     `tts_chunk` — historically omit it). Outbound always sets it.
///   * `ts` is optional on inbound for the same reason. Outbound
///     always sets it to `Date().timeIntervalSince1970`.
///   * `payload` defaults to an empty dictionary.
public struct HUPFrame: Codable {
    public let hupVersion: String?
    public let type: String
    public let timestamp: Double?
    public let payload: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case hupVersion = "hup_version"
        case type
        case timestamp = "ts"
        case payload
    }

    public init(type: String, payload: [String: AnyCodable]) {
        self.hupVersion = FeralNodeSDKInfo.hupVersion
        self.type = type
        self.timestamp = Date().timeIntervalSince1970
        self.payload = payload
    }

    /// Memberwise initializer used by tests and by helpers that
    /// reconstruct a frame from a known wire dump. Production code
    /// should use the two-argument `init(type:payload:)` so the
    /// version + timestamp default to canonical values.
    public init(
        hupVersion: String?,
        type: String,
        timestamp: Double?,
        payload: [String: AnyCodable]
    ) {
        self.hupVersion = hupVersion
        self.type = type
        self.timestamp = timestamp
        self.payload = payload
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.hupVersion = try c.decodeIfPresent(String.self, forKey: .hupVersion)
        self.type = try c.decode(String.self, forKey: .type)
        self.timestamp = try c.decodeIfPresent(Double.self, forKey: .timestamp)
        self.payload = (try c.decodeIfPresent([String: AnyCodable].self, forKey: .payload)) ?? [:]
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        // Always emit hup_version + ts on outbound so brain Pydantic
        // schemas validate without falling into the lenient branch.
        let hv = self.hupVersion ?? FeralNodeSDKInfo.hupVersion
        try c.encode(hv, forKey: .hupVersion)
        try c.encode(self.type, forKey: .type)
        try c.encode(self.timestamp ?? Date().timeIntervalSince1970, forKey: .timestamp)
        try c.encode(self.payload, forKey: .payload)
    }
}

/// node_register payload shape. See HUP_SPEC.md §5.1.
public struct NodeRegisterPayload: Codable {
    public let nodeId: String
    public let nodeType: String
    public let capabilities: [String]
    public let platform: String
    public let manufacturer: String
    public let model: String
    public let firmwareVersion: String

    enum CodingKeys: String, CodingKey {
        case nodeId = "node_id"
        case nodeType = "node_type"
        case capabilities
        case platform
        case manufacturer
        case model
        case firmwareVersion = "firmware_version"
    }

    public init(
        nodeId: String,
        nodeType: String = "phone",
        capabilities: [String],
        platform: String = "ios",
        manufacturer: String = "Apple",
        model: String = "iPhone",
        firmwareVersion: String = FeralNodeSDKInfo.version
    ) {
        self.nodeId = nodeId
        self.nodeType = nodeType
        self.capabilities = capabilities
        self.platform = platform
        self.manufacturer = manufacturer
        self.model = model
        self.firmwareVersion = firmwareVersion
    }
}

/// Minimal type-erased JSON value. Enough to carry arbitrary
/// `device_event.data` payloads without pulling in SwiftyJSON.
public enum AnyCodable: Codable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case array([AnyCodable])
    case object([String: AnyCodable])
    case null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        if let v = try? c.decode(Int.self) { self = .int(v); return }
        if let v = try? c.decode(Double.self) { self = .double(v); return }
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode([AnyCodable].self) { self = .array(v); return }
        if let v = try? c.decode([String: AnyCodable].self) { self = .object(v); return }
        throw DecodingError.dataCorruptedError(
            in: c, debugDescription: "unsupported JSON value"
        )
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        }
    }
}
