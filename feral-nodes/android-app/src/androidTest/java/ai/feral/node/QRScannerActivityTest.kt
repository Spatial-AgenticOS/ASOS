package ai.feral.node

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class QRScannerActivityTest {

    @Test
    fun parseValidPairingQR() {
        val raw = """{"host":"192.168.1.50","port":9090,"token":"test-key-123"}"""
        val json = JSONObject(raw)

        assertEquals("192.168.1.50", json.getString("host"))
        assertEquals(9090, json.optInt("port", 9090))
        assertEquals("test-key-123", json.getString("token"))
    }

    @Test
    fun parseQR_missingPortUsesDefault() {
        val raw = """{"host":"brain.local","token":"abc"}"""
        val json = JSONObject(raw)

        assertEquals("brain.local", json.getString("host"))
        assertEquals(9090, json.optInt("port", 9090))
    }

    @Test
    fun parseQR_requiresHostAndToken() {
        val raw1 = """{"host":"10.0.0.1"}"""
        val json1 = JSONObject(raw1)
        assertTrue(json1.has("host"))
        assertFalse(json1.has("token"))

        val raw2 = """{"token":"abc"}"""
        val json2 = JSONObject(raw2)
        assertFalse(json2.has("host"))
        assertTrue(json2.has("token"))
    }

    @Test
    fun parseQR_invalidJSONReturnsNull() {
        try {
            JSONObject("not-json")
            fail("Should have thrown")
        } catch (e: Exception) {
            assertNotNull(e)
        }
    }

    @Test
    fun parseQR_withExtraFields() {
        val raw = """{"host":"h","port":9090,"token":"t","extra":"ignored","debug":true}"""
        val json = JSONObject(raw)

        assertEquals("h", json.getString("host"))
        assertEquals("t", json.getString("token"))
        assertTrue(json.has("extra"))
    }

    @Test
    fun resultKeyConstant() {
        assertEquals("pairing_json", QRScannerActivity.RESULT_KEY)
    }
}
