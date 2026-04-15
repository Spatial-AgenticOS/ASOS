package ai.feral.bridge

import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import okhttp3.*
import java.util.concurrent.TimeUnit

/**
 * FERAL Brain WebSocket Client for Android.
 * Mirrors the iOS FeralBrainClient.swift architecture.
 *
 * Connects to ws://host:9090/v1/node?api_key=...
 * Registers as node_type: "phone", platform: "android"
 */
interface FeralBrainDelegate {
    fun brainDidConnect()
    fun brainDidDisconnect(reason: String)
    fun brainDidReceiveText(text: String)
    fun brainDidReceiveSDUI(json: JsonObject)
    fun brainDidReceiveAudio(data: ByteArray, encoding: String, sampleRate: Int)
    fun brainDidRequestStopPlayback()
    fun brainDidReceiveTranscript(text: String, isPartial: Boolean)
    fun brainDidReceiveExecute(executor: String, action: String, args: JsonObject)
}

class FeralBrainClient(
    private val host: String,
    private val port: Int = 9090,
    private val apiKey: String,
    private val nodeId: String = "android-phone",
    private val delegate: FeralBrainDelegate? = null,
) {
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    var isConnected: Boolean = false
        private set

    fun connect() {
        val url = "ws://$host:$port/v1/node"
        val request = Request.Builder()
            .url(url)
            .addHeader("Authorization", "Bearer $apiKey")
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                isConnected = true
                sendRegistration()
                sendVoiceConfig()
                delegate?.brainDidConnect()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                scope.launch { handleMessage(text) }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                isConnected = false
                delegate?.brainDidDisconnect(reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                isConnected = false
                delegate?.brainDidDisconnect(t.message ?: "Connection failed")
                scheduleReconnect()
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "Client disconnect")
        isConnected = false
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
                    add("voice")
                    add("sensors")
                    add("gps")
                    add("camera")
                    add("wake_word")
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
                put("mode", "auto")
                put("sample_rate", 24000)
                put("encoding", "pcm16")
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
                put("data_b64", b64)
                put("chunk_index", chunkIndex)
                put("is_final", isFinal)
                put("encoding", "pcm16")
                put("sample_rate", 24000)
            }
        }
        sendJson(msg)
    }

    fun sendTextCommand(text: String) {
        val msg = buildJsonObject {
            put("type", "text_command")
            put("hop", "node")
            putJsonObject("payload") {
                put("text", text)
            }
        }
        sendJson(msg)
    }

    fun sendSensorTelemetry(
        heartRate: Int? = null,
        spo2: Int? = null,
        steps: Int? = null,
        temperature: Double? = null,
        batteryPct: Int? = null,
    ) {
        val msg = buildJsonObject {
            put("type", "sensor_telemetry")
            put("hop", "node")
            putJsonObject("payload") {
                heartRate?.let { put("heart_rate", it) }
                spo2?.let { put("spo2_pct", it) }
                steps?.let { put("step_count", it) }
                temperature?.let { put("skin_temp_c", it) }
                batteryPct?.let { put("battery_pct", it) }
            }
        }
        sendJson(msg)
    }

    fun sendGlassesStatus(
        glassesConnected: Boolean,
        glassesModel: String = "FERAL",
        glassesBattery: Int = 100,
    ) {
        val msg = buildJsonObject {
            put("type", "glasses_status")
            put("hop", "node")
            putJsonObject("payload") {
                put("connected", glassesConnected)
                put("model", glassesModel)
                put("battery_pct", glassesBattery)
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
                "text_response" -> {
                    val msg = payload["text"]?.jsonPrimitive?.contentOrNull ?: ""
                    delegate?.brainDidReceiveText(msg)
                }
                "sdui" -> delegate?.brainDidReceiveSDUI(payload)
                "audio_response" -> {
                    val dataB64 = payload["data_b64"]?.jsonPrimitive?.contentOrNull ?: return
                    val encoding = payload["encoding"]?.jsonPrimitive?.contentOrNull ?: "pcm16"
                    val sampleRate = payload["sample_rate"]?.jsonPrimitive?.intOrNull ?: 24000
                    val audioBytes = android.util.Base64.decode(dataB64, android.util.Base64.DEFAULT)
                    delegate?.brainDidReceiveAudio(audioBytes, encoding, sampleRate)
                }
                "speech_started" -> delegate?.brainDidRequestStopPlayback()
                "transcript" -> {
                    val transcript = payload["text"]?.jsonPrimitive?.contentOrNull ?: ""
                    val isPartial = payload["is_partial"]?.jsonPrimitive?.booleanOrNull ?: false
                    delegate?.brainDidReceiveTranscript(transcript, isPartial)
                }
                "execute" -> {
                    val executor = payload["executor"]?.jsonPrimitive?.contentOrNull ?: ""
                    val action = payload["action"]?.jsonPrimitive?.contentOrNull ?: ""
                    val args = payload["args"]?.jsonObject ?: JsonObject(emptyMap())
                    delegate?.brainDidReceiveExecute(executor, action, args)
                }
                "tts_chunk" -> {
                    val dataB64 = payload["data_b64"]?.jsonPrimitive?.contentOrNull ?: return
                    val encoding = payload["encoding"]?.jsonPrimitive?.contentOrNull ?: "mp3"
                    val audioBytes = android.util.Base64.decode(dataB64, android.util.Base64.DEFAULT)
                    delegate?.brainDidReceiveAudio(audioBytes, encoding, 16000)
                }
            }
        } catch (e: Exception) {
            // Ignore malformed messages
        }
    }

    private fun sendJson(json: JsonObject) {
        webSocket?.send(json.toString())
    }

    private fun scheduleReconnect() {
        scope.launch {
            delay(3000)
            if (!isConnected) connect()
        }
    }

    fun destroy() {
        disconnect()
        scope.cancel()
    }
}
