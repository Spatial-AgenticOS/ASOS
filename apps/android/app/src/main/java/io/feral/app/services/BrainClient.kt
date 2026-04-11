package ai.feral.app.services

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.*
import okhttp3.*
import java.util.concurrent.TimeUnit

enum class BrainConnectionState {
    DISCONNECTED, CONNECTING, REGISTERING, CONNECTED, RECONNECTING
}

data class ChatMessage(
    val text: String,
    val isUser: Boolean,
    val timestamp: Long = System.currentTimeMillis(),
)

class BrainClient(
    private var host: String = "10.0.2.2",
    private var port: Int = 9090,
    private var apiKey: String = "",
    private val nodeId: String = "feral-android-${android.os.Build.MODEL.lowercase().replace(" ", "-")}",
) {
    private var webSocket: WebSocket? = null
    private val httpClient = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private val _connectionState = MutableStateFlow(BrainConnectionState.DISCONNECTED)
    val connectionState: StateFlow<BrainConnectionState> = _connectionState

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    private val _streamingText = MutableStateFlow("")
    val streamingText: StateFlow<String> = _streamingText

    private val _transcript = MutableStateFlow("")
    val transcript: StateFlow<String> = _transcript

    private var reconnectAttempts = 0
    private val maxReconnectAttempts = 10

    val isConnected: Boolean get() = _connectionState.value == BrainConnectionState.CONNECTED

    fun configure(host: String, port: Int, apiKey: String) {
        this.host = host
        this.port = port
        this.apiKey = apiKey
    }

    fun connect() {
        if (_connectionState.value == BrainConnectionState.CONNECTED ||
            _connectionState.value == BrainConnectionState.CONNECTING) return

        _connectionState.value = BrainConnectionState.CONNECTING
        val url = "ws://$host:$port/v1/node?api_key=$apiKey"
        val request = Request.Builder().url(url).build()

        webSocket = httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _connectionState.value = BrainConnectionState.REGISTERING
                sendRegistration()
                sendVoiceConfig()
                _connectionState.value = BrainConnectionState.CONNECTED
                reconnectAttempts = 0
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                scope.launch { handleMessage(text) }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                _connectionState.value = BrainConnectionState.DISCONNECTED
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                _connectionState.value = BrainConnectionState.DISCONNECTED
                scheduleReconnect()
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "Client disconnect")
        _connectionState.value = BrainConnectionState.DISCONNECTED
    }

    fun sendTextCommand(text: String) {
        _messages.value = _messages.value + ChatMessage(text = text, isUser = true)
        _streamingText.value = ""

        val msg = buildJsonObject {
            put("type", "text_command")
            put("hop", "node")
            putJsonObject("payload") {
                put("text", text)
                put("node_id", nodeId)
            }
        }
        sendJson(msg)
    }

    fun sendAudioChunk(data: ByteArray, chunkIndex: Int, isFinal: Boolean) {
        val b64 = android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP)
        val msg = buildJsonObject {
            put("type", "audio_chunk")
            put("hop", "node")
            putJsonObject("payload") {
                put("node_id", nodeId)
                put("data_b64", b64)
                put("chunk_index", chunkIndex)
                put("is_final", isFinal)
                put("encoding", "pcm16")
                put("sample_rate", 24000)
            }
        }
        sendJson(msg)
    }

    fun sendSensorTelemetry(
        heartRate: Int? = null,
        spo2: Int? = null,
        steps: Int? = null,
        temperature: Double? = null,
    ) {
        val msg = buildJsonObject {
            put("type", "sensor_telemetry")
            put("hop", "node")
            putJsonObject("payload") {
                put("node_id", nodeId)
                heartRate?.let { put("heart_rate", it) }
                spo2?.let { put("spo2_pct", it) }
                steps?.let { put("step_count", it) }
                temperature?.let { put("skin_temp_c", it) }
            }
        }
        sendJson(msg)
    }

    private fun sendRegistration() {
        val msg = buildJsonObject {
            put("type", "register")
            put("hop", "node")
            putJsonObject("payload") {
                put("node_id", nodeId)
                put("node_type", "phone")
                put("platform", "android")
                put("os_version", android.os.Build.VERSION.RELEASE)
                put("device_model", android.os.Build.MODEL)
                putJsonArray("capabilities") {
                    add("voice"); add("sensors"); add("gps"); add("camera"); add("health_connect")
                }
            }
        }
        sendJson(msg)
    }

    private fun sendVoiceConfig() {
        val msg = buildJsonObject {
            put("type", "voice_config")
            put("hop", "node")
            putJsonObject("payload") {
                put("node_id", nodeId)
                put("supports_realtime", true)
                put("mode", "realtime")
                put("sample_rate", 24000)
                put("encoding", "pcm16")
            }
        }
        sendJson(msg)
    }

    private fun handleMessage(text: String) {
        try {
            val obj = json.parseToJsonElement(text).jsonObject
            val type = obj["type"]?.jsonPrimitive?.contentOrNull ?: return
            val payload = obj["payload"]?.jsonObject ?: JsonObject(emptyMap())

            when (type) {
                "registered" -> {
                    _connectionState.value = BrainConnectionState.CONNECTED
                }

                "text_response" -> {
                    val msg = payload["text"]?.jsonPrimitive?.contentOrNull ?: ""
                    _messages.value = _messages.value + ChatMessage(text = msg, isUser = false)
                    _streamingText.value = ""
                }

                "stream_delta" -> {
                    val delta = payload["delta"]?.jsonPrimitive?.contentOrNull
                        ?: payload["text"]?.jsonPrimitive?.contentOrNull ?: ""
                    _streamingText.value += delta
                }

                "stream_end" -> {
                    val final = _streamingText.value
                    if (final.isNotEmpty()) {
                        _messages.value = _messages.value + ChatMessage(text = final, isUser = false)
                    }
                    _streamingText.value = ""
                }

                "transcript" -> {
                    val t = payload["text"]?.jsonPrimitive?.contentOrNull ?: ""
                    _transcript.value = t
                }

                "audio_response", "speech_started", "execute" -> {
                    // Audio playback and execution handling delegated to platform layer
                }
            }
        } catch (_: Exception) {}
    }

    private fun sendJson(json: JsonObject) {
        webSocket?.send(json.toString())
    }

    private fun scheduleReconnect() {
        if (reconnectAttempts >= maxReconnectAttempts) return
        _connectionState.value = BrainConnectionState.RECONNECTING
        reconnectAttempts++
        val delay = minOf(reconnectAttempts * 2000L, 30_000L)
        scope.launch {
            delay(delay)
            if (_connectionState.value == BrainConnectionState.RECONNECTING) {
                connect()
            }
        }
    }

    fun clearMessages() {
        _messages.value = emptyList()
    }

    fun destroy() {
        disconnect()
        scope.cancel()
    }
}
