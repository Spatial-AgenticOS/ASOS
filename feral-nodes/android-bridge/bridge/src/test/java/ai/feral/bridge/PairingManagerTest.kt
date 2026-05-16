package ai.feral.bridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Phase 5 / C5.2 — unified QR v1 + legacy backward-compat decoder
 * tests for the canonical Android pairing parser.
 *
 * Mirrors UnifiedPairPayloadTests.swift in the iOS app so the two
 * platforms can never silently drift on which QR shapes they accept.
 */
class PairingManagerTest {

    // ── 1. Unified v1 payload ────────────────────────────────────

    @Test
    fun parseV1_localMode_succeeds() {
        val json = """{"v":1,"mode":"local","url":"http://192.168.1.50:9090/pair?t=abc",
            "token":"abc","brain_id":"bid-1","expires":9999999999,"name":"FERAL Brain"}""".trimIndent()
        val decoded = PairingManager.parsePayload(json)
        assertNotNull(decoded)
        assertFalse(decoded!!.isLegacy)
        assertEquals("abc", decoded.token)
        assertEquals("bid-1", decoded.brainId)
        assertTrue(decoded.brainUrl.contains("192.168.1.50"))
    }

    @Test
    fun parseV1_remoteMode_httpsTunnel() {
        val json = """{"v":1,"mode":"remote","url":"https://feral.tail123.ts.net/pair?t=tt",
            "token":"tt","brain_id":"bid-2","expires":1,"name":"FERAL Brain"}""".trimIndent()
        val decoded = PairingManager.parsePayload(json)!!
        assertTrue(decoded.brainUrl.startsWith("https://"))
        assertFalse(decoded.isLegacy)
    }

    // ── 2. Legacy {host, port, apiKey, nodeName} ────────────────

    @Test
    fun parseLegacy_apiKeyShape_marksLegacy() {
        val json = """{"host":"192.168.1.50","port":9090,"apiKey":"k1","nodeName":"phone"}"""
        val decoded = PairingManager.parsePayload(json)!!
        assertTrue(decoded.isLegacy)
        assertEquals("k1", decoded.token)
        assertEquals("http://192.168.1.50:9090", decoded.brainUrl)
        assertNull(decoded.brainId)
    }

    // ── 3. Legacy {host, port, token, name} ─────────────────────

    @Test
    fun parseLegacy_tokenShape_marksLegacy() {
        val json = """{"host":"10.0.0.1","port":9090,"token":"tt","name":"FERAL Brain"}"""
        val decoded = PairingManager.parsePayload(json)!!
        assertTrue(decoded.isLegacy)
        assertEquals("tt", decoded.token)
        assertEquals("FERAL Brain", decoded.name)
    }

    // ── 4. feral://pair?p=<base64url-json> ──────────────────────

    @Test
    fun parseFeralDeepLink_unwrapsPayload() {
        val payloadJson = """{"v":1,"mode":"local","url":"http://10.0.0.5:9090/pair?t=zz",
            "token":"zz","brain_id":"b","expires":1,"name":"FERAL Brain"}""".trimIndent()
        val b64 = java.util.Base64.getUrlEncoder().withoutPadding()
            .encodeToString(payloadJson.toByteArray())
        val url = "feral://pair?p=$b64"
        val decoded = PairingManager.parsePayload(url)!!
        assertEquals("zz", decoded.token)
        assertFalse(decoded.isLegacy)
    }

    // ── 5. https://<brain>/pair?t=<token> ───────────────────────

    @Test
    fun parseHttpsPairURL() {
        val decoded = PairingManager.parsePayload("https://feral.tail123.ts.net/pair?t=https-token")!!
        assertEquals("https-token", decoded.token)
        assertEquals("https://feral.tail123.ts.net", decoded.brainUrl)
    }

    // ── Negative ────────────────────────────────────────────────

    @Test
    fun rejectsGarbage() {
        assertNull(PairingManager.parsePayload(""))
        assertNull(PairingManager.parsePayload("not json"))
        assertNull(PairingManager.parsePayload("{}"))
        assertNull(PairingManager.parsePayload("https://no-token-here"))
    }

    // ── Backward compat for parseQR() helper ────────────────────

    @Test
    fun parseQR_legacy_returnsPairingInfo() {
        val info = PairingManager.parseQR(
            """{"host":"h","port":1234,"apiKey":"k","nodeName":"n"}"""
        )!!
        assertEquals("h", info.host)
        assertEquals(1234, info.port)
        assertEquals("k", info.apiKey)
    }

    @Test
    fun parseQR_acceptsTokenAlias() {
        val info = PairingManager.parseQR(
            """{"host":"h","port":1234,"token":"k","name":"n"}"""
        )!!
        assertEquals("k", info.apiKey)
        assertEquals("n", info.nodeName)
    }
}
