package ai.feral.bridge

import android.graphics.Bitmap
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import org.json.JSONObject

data class PairingInfo(
    val host: String,
    val port: Int,
    val apiKey: String,
    val nodeName: String
)

object PairingManager {
    fun generateQR(info: PairingInfo, size: Int = 512): Bitmap {
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

    fun parseQR(data: String): PairingInfo? {
        return try {
            val json = JSONObject(data)
            PairingInfo(
                host = json.getString("host"),
                port = json.getInt("port"),
                apiKey = json.getString("apiKey"),
                nodeName = json.optString("nodeName", "android-node")
            )
        } catch (e: Exception) {
            null
        }
    }
}
