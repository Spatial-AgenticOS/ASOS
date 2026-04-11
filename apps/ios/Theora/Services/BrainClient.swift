import Foundation
import Combine

// MARK: - Connection State

enum BrainConnectionState: String, Equatable {
    case disconnected
    case connecting
    case registering
    case connected
    case reconnecting
}

// MARK: - Message Types

struct BrainTextResponse {
    let text: String
    let sdui: [String: Any]?
}

struct BrainTranscript {
    let text: String
    let isFinal: Bool
}

// MARK: - Brain Client (adapted from ASOSBrainClient)

final class BrainClient: NSObject, ObservableObject {

    @Published var connectionState: BrainConnectionState = .disconnected
    @Published var lastTextResponse: String = ""
    @Published var lastTranscript: BrainTranscript?
    @Published var streamDelta: String = ""

    var onTextResponse: ((BrainTextResponse) -> Void)?
    var onStreamDelta: ((String) -> Void)?
    var onAudioResponse: ((Data, String, Int, Bool) -> Void)?
    var onStopPlayback: (() -> Void)?

    private var host: String
    private var port: Int
    private var apiKey: String
    private let nodeId: String

    private var urlSession: URLSession?
    private var webSocket: URLSessionWebSocketTask?
    private var sessionId: String?

    private var reconnectAttempts = 0
    private let maxReconnectAttempts = 10
    private var sensorBuffer: [[String: Any]] = []
    private var flushTimer: Timer?
    private let sendQueue = DispatchQueue(label: "io.theora.brain.send", qos: .userInitiated)

    var isConnected: Bool { connectionState == .connected }

    init(host: String = "localhost", port: Int = 9090, apiKey: String = "") {
        self.host = host
        self.port = port
        self.apiKey = apiKey
        #if os(iOS)
        self.nodeId = "theora-iphone-\(UIDevice.current.name.lowercased().replacingOccurrences(of: " ", with: "-"))"
        #else
        self.nodeId = "theora-apple-device"
        #endif
        super.init()
    }

    // MARK: - Public API

    func configure(host: String, port: Int, apiKey: String) {
        self.host = host
        self.port = port
        self.apiKey = apiKey
    }

    func connect() {
        guard connectionState != .connected && connectionState != .connecting else { return }
        connectionState = .connecting

        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = true
        urlSession = URLSession(configuration: config, delegate: self, delegateQueue: nil)

        let urlString = "ws://\(host):\(port)/v1/node?api_key=\(apiKey)"
        guard let url = URL(string: urlString) else {
            connectionState = .disconnected
            return
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 15
        webSocket = urlSession?.webSocketTask(with: request)
        webSocket?.resume()
        startReceiving()
    }

    func disconnect() {
        flushTimer?.invalidate()
        webSocket?.cancel(with: .normalClosure, reason: nil)
        DispatchQueue.main.async { self.connectionState = .disconnected }
    }

    func sendTextCommand(_ text: String) {
        let msg: [String: Any] = [
            "hop": "node",
            "type": "text_command",
            "payload": [
                "text": text,
                "node_id": nodeId
            ]
        ]
        sendJSON(msg)
    }

    func sendAudioChunk(base64: String, chunkIndex: Int, isFinal: Bool = false) {
        let msg: [String: Any] = [
            "hop": "node",
            "type": "audio_chunk",
            "payload": [
                "node_id": nodeId,
                "data_b64": base64,
                "chunk_index": chunkIndex,
                "is_final": isFinal,
                "encoding": "pcm16",
                "sample_rate": 24000
            ]
        ]
        sendJSON(msg)
    }

    func sendSensorData(sensor: String, value: [String: Any]) {
        let telemetry: [String: Any] = [
            "hop": "node",
            "type": "sensor_telemetry",
            "payload": [
                "node_id": nodeId,
                "sensor": sensor,
                "data": value,
                "timestamp": ISO8601DateFormatter().string(from: Date()),
                "source": "healthkit"
            ]
        ]
        sensorBuffer.append(telemetry)
    }

    func sendBatchSensorData(_ readings: [String: Any]) {
        let batch: [String: Any] = [
            "hop": "node",
            "type": "sensor_batch",
            "payload": [
                "node_id": nodeId,
                "readings": readings,
                "timestamp": ISO8601DateFormatter().string(from: Date())
            ]
        ]
        sendJSON(batch)
    }

    // MARK: - Registration

    private func registerAsNode() {
        connectionState = .registering

        var capabilities = ["microphone", "gps", "accelerometer", "gyroscope"]
        #if os(iOS)
        capabilities.append(contentsOf: ["camera", "healthkit"])
        #endif

        let registration: [String: Any] = [
            "hop": "node",
            "type": "register",
            "payload": [
                "node_id": nodeId,
                "node_type": "phone",
                "capabilities": capabilities,
                "platform": "ios",
                "os_version": ProcessInfo.processInfo.operatingSystemVersionString,
                "glasses_connected": false
            ]
        ]
        sendJSON(registration)
    }

    private func sendVoiceConfig() {
        let config: [String: Any] = [
            "hop": "node",
            "type": "voice_config",
            "payload": [
                "node_id": nodeId,
                "supports_realtime": true,
                "mode": "realtime",
                "sample_rate": 24000,
                "encoding": "pcm16"
            ]
        ]
        sendJSON(config)
    }

    // MARK: - WebSocket receive loop

    private func startReceiving() {
        webSocket?.receive { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    self.handleMessage(text)
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) {
                        self.handleMessage(text)
                    }
                @unknown default:
                    break
                }
                self.startReceiving()

            case .failure(let error):
                self.handleDisconnect(reason: error.localizedDescription)
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

        let type = json["type"] as? String ?? ""
        let payload = json["payload"] as? [String: Any] ?? [:]

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            switch type {
            case "registered":
                self.connectionState = .connected
                self.sessionId = json["session_id"] as? String ?? ""
                self.reconnectAttempts = 0
                self.startSensorFlushTimer()
                self.sendVoiceConfig()

            case "text_response":
                let responseText = payload["text"] as? String ?? ""
                let sdui = payload["sdui"] as? [String: Any]
                self.lastTextResponse = responseText
                self.onTextResponse?(BrainTextResponse(text: responseText, sdui: sdui))

            case "stream_delta":
                let delta = payload["delta"] as? String ?? payload["text"] as? String ?? ""
                self.streamDelta += delta
                self.onStreamDelta?(delta)

            case "stream_end":
                let finalText = self.streamDelta
                self.lastTextResponse = finalText
                self.onTextResponse?(BrainTextResponse(text: finalText, sdui: nil))
                self.streamDelta = ""

            case "audio_response":
                let audioB64 = payload["data_b64"] as? String ?? ""
                let encoding = payload["encoding"] as? String ?? "pcm16"
                let sampleRate = payload["sample_rate"] as? Int ?? 24000
                let isFinal = payload["is_final"] as? Bool ?? false
                if let audioData = Data(base64Encoded: audioB64) {
                    self.onAudioResponse?(audioData, encoding, sampleRate, isFinal)
                }

            case "speech_started":
                self.onStopPlayback?()

            case "transcript":
                let transcriptText = payload["text"] as? String ?? ""
                let isPartial = payload["is_partial"] as? Bool ?? false
                self.lastTranscript = BrainTranscript(text: transcriptText, isFinal: !isPartial)

            default:
                break
            }
        }
    }

    // MARK: - Reconnection

    private func handleDisconnect(reason: String) {
        flushTimer?.invalidate()
        DispatchQueue.main.async { self.connectionState = .disconnected }
        attemptReconnect()
    }

    private func attemptReconnect() {
        guard reconnectAttempts < maxReconnectAttempts else { return }
        DispatchQueue.main.async { self.connectionState = .reconnecting }
        reconnectAttempts += 1

        let delay = min(Double(reconnectAttempts) * 2.0, 30.0)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, self.connectionState == .reconnecting else { return }
            self.connect()
        }
    }

    // MARK: - Send helpers

    private func sendJSON(_ dict: [String: Any]) {
        sendQueue.async { [weak self] in
            guard let data = try? JSONSerialization.data(withJSONObject: dict),
                  let text = String(data: data, encoding: .utf8) else { return }
            self?.webSocket?.send(.string(text)) { _ in }
        }
    }

    private func startSensorFlushTimer() {
        DispatchQueue.main.async {
            self.flushTimer?.invalidate()
            self.flushTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
                self?.flushSensorBuffer()
            }
        }
    }

    private func flushSensorBuffer() {
        guard !sensorBuffer.isEmpty else { return }
        let batch = sensorBuffer
        sensorBuffer.removeAll()
        for msg in batch { sendJSON(msg) }
    }
}

// MARK: - URLSessionWebSocketDelegate

extension BrainClient: URLSessionWebSocketDelegate {
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        registerAsNode()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let reasonStr = reason.flatMap { String(data: $0, encoding: .utf8) } ?? "Connection closed"
        handleDisconnect(reason: reasonStr)
    }
}
