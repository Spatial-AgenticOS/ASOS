package ai.feral.bridge

import android.graphics.Bitmap
import android.net.Uri
import android.util.Base64
import android.util.Log
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import org.json.JSONObject

/**
 * Legacy QR JSON shape (pre-2026.5.8). Preserved for backward compat —
 * brains still emitting `mode=app` JSON encode this shape. The unified
 * v1 payload (see `PairingDecoded`) replaces it for ≥ 2026.5.8.
 */
data class PairingInfo(
    val host: String,
    val port: Int,
    val apiKey: String,
    val nodeName: String
)

/**
 * Normalized pair-payload result. Whatever shape the QR carried (v1
 * unified, legacy `apiKey`, legacy `token`, `feral://pair?p=…`,
 * `https://<brain>/pair?t=…`), callers see the same fields.
 */
data class PairingDecoded(
    val brainUrl: String,
    val token: String,
    val brainId: String?,
    val name: String?,
    val isLegacy: Boolean,
)

object PairingManager {
    private const val TAG = "FeralPair"

    fun generateQR(info: PairingInfo, size: Int = 512): Bitmap {
        // Generators continue to emit the legacy shape because brains
        // ≥ 2026.5.8 emit the unified payload directly via
        // /api/devices/pair/qr — the daemon-side generator is only used
        // for offline test paths and self-pair flows. Updating both
        // sides at once would force every test fixture to upgrade in
        // lock-step. Sunset: 2026.7.0.
        val json = JSONObject().apply {
            put("host", info.host)
            put("port", info.port)
            put("apiKey", info.apiKey)
            put("nodeName", info.nodeName)
        }.toString()

        val writer = QRCodeWriter()
        val bitMatrix = writer.encode(json, BarcodeFormat.QR_CODE, size, size)
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.RGB_565)
        for (x in 0 until size) {
            for (y in 0 until size) {
                bitmap.setPixel(x, y, if (bitMatrix[x, y]) 0xFF000000.toInt() else 0xFFFFFFFF.toInt())
            }
        }
        return bitmap
    }

    /**
     * Backward-compatible single-shape parser. Prefer [parsePayload]
     * for new code; this one stays around for callers that only need
     * `host/port/apiKey/nodeName`.
     */
    fun parseQR(data: String): PairingInfo? {
        return try {
            val json = JSONObject(data)
            val token = json.optString("token", "").ifEmpty { json.optString("apiKey", "") }
            if (token.isEmpty()) return null
            PairingInfo(
                host = json.getString("host"),
                port = json.getInt("port"),
                apiKey = token,
                nodeName = json.optString("nodeName", json.optString("name", "android-node"))
            )
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Decode any supported QR or deep-link payload into a uniform
     * [PairingDecoded]. Accepts:
     *
     *   1. Unified v1 JSON `{v:1, mode, url, token, brain_id, …}`
     *      (preferred; emitted by brains ≥ 2026.5.8).
     *   2. Legacy `{host, port, token|apiKey, name|nodeName}`
     *      (pre-2026.5.8 brain `mode=app` and pre-2026.5.8 Android QR).
     *   3. URL form `feral://pair?p=<base64url-json-payload>`.
     *   4. Plain `https://<brain>/pair?t=<token>` (web QR scanned with
     *      the camera and routed through the deep-link handler).
     *
     * Logs a deprecation warning on legacy shapes; sunset 2026.7.0.
     */
    fun parsePayload(data: String): PairingDecoded? {
        // 1. Unified v1.
        try {
            val json = JSONObject(data)
            if (json.optInt("v", 0) == 1 && json.has("url") && json.has("token")) {
                return PairingDecoded(
                    brainUrl = json.getString("url"),
                    token = json.getString("token"),
                    brainId = json.optString("brain_id").ifEmpty { null },
                    name = json.optString("name").ifEmpty { null },
                    isLegacy = false,
                )
            }
        } catch (_: Exception) { /* fall through */ }

        // 2. Legacy {host, port, token|apiKey, …}.
        try {
            val json = JSONObject(data)
            val host = json.optString("host", "")
            val port = json.optInt("port", 0)
            val token = json.optString("token", "").ifEmpty { json.optString("apiKey", "") }
            if (host.isNotEmpty() && port > 0 && token.isNotEmpty()) {
                Log.w(TAG, "parsePayload: accepted legacy {host,port,*} shape; sunset 2026.7.0")
                return PairingDecoded(
                    brainUrl = "http://$host:$port",
                    token = token,
                    brainId = null,
                    name = json.optString("name").ifEmpty { json.optString("nodeName").ifEmpty { null } },
                    isLegacy = true,
                )
            }
        } catch (_: Exception) { /* fall through */ }

        // 3. feral:// URL.
        if (data.startsWith("feral://pair")) {
            val uri = Uri.parse(data)
            val payloadParam = uri.getQueryParameter("p")
            if (payloadParam != null) {
                try {
                    val decoded = String(Base64.decode(payloadParam, Base64.URL_SAFE or Base64.NO_PADDING))
                    return parsePayload(decoded)
                } catch (_: Exception) { /* fall through */ }
            }
        }

        // 4. https://<brain>/pair?t=<token>.
        if (data.startsWith("http://") || data.startsWith("https://")) {
            val uri = Uri.parse(data)
            val token = uri.getQueryParameter("t").orEmpty()
            if (token.isNotEmpty() && uri.host != null) {
                val portStr = if (uri.port > 0) ":${uri.port}" else ""
                return PairingDecoded(
                    brainUrl = "${uri.scheme}://${uri.host}$portStr",
                    token = token,
                    brainId = null,
                    name = null,
                    isLegacy = false,
                )
            }
        }

        return null
    }
}
