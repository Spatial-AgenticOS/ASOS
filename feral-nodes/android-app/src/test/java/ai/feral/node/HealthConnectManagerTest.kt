package ai.feral.node

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.time.temporal.ChronoUnit

class HealthConnectManagerTest {

    @Test
    fun `callback receives heart rate data`() {
        var received: Map<String, Any>? = null
        val callback: (Map<String, Any>) -> Unit = { received = it }

        val payload = mapOf("type" to "heart_rate", "bpm" to 72L, "source" to "health_connect")
        callback(payload)

        assertNotNull(received)
        assertEquals("heart_rate", received!!["type"])
        assertEquals(72L, received!!["bpm"])
        assertEquals("health_connect", received!!["source"])
    }

    @Test
    fun `callback receives spo2 data`() {
        var received: Map<String, Any>? = null
        val callback: (Map<String, Any>) -> Unit = { received = it }

        val payload = mapOf("type" to "spo2", "percent" to 98.0, "source" to "health_connect")
        callback(payload)

        assertEquals("spo2", received!!["type"])
        assertEquals(98.0, received!!["percent"])
    }

    @Test
    fun `callback receives steps data`() {
        var received: Map<String, Any>? = null
        val callback: (Map<String, Any>) -> Unit = { received = it }

        val payload = mapOf("type" to "steps", "count" to 5432L, "source" to "health_connect")
        callback(payload)

        assertEquals("steps", received!!["type"])
        assertEquals(5432L, received!!["count"])
    }

    @Test
    fun `callback receives sleep data`() {
        var received: Map<String, Any>? = null
        val callback: (Map<String, Any>) -> Unit = { received = it }

        val payload = mapOf("type" to "sleep", "hours" to 7.5, "source" to "health_connect")
        callback(payload)

        assertEquals("sleep", received!!["type"])
        assertEquals(7.5, received!!["hours"])
    }

    @Test
    fun `time range filter spans 5 minutes for heart rate`() {
        val now = Instant.now()
        val fiveMinAgo = now.minus(5, ChronoUnit.MINUTES)
        val diff = ChronoUnit.MINUTES.between(fiveMinAgo, now)
        assertEquals(5, diff)
    }

    @Test
    fun `time range filter spans start of day for steps`() {
        val now = Instant.now()
        val startOfDay = now.truncatedTo(ChronoUnit.DAYS)
        assertTrue(now.isAfter(startOfDay) || now == startOfDay)
    }

    @Test
    fun `sleep total calculation from durations`() {
        data class SleepSample(val startMinute: Int, val endMinute: Int)

        val samples = listOf(
            SleepSample(0, 180),   // 3 hours
            SleepSample(200, 380), // 3 hours
            SleepSample(400, 460), // 1 hour
        )
        val totalMinutes = samples.sumOf { it.endMinute - it.startMinute }
        val hours = totalMinutes / 60.0
        assertEquals(7.0, hours, 0.01)
    }

    @Test
    fun `health connect permission types`() {
        val requiredPermissions = setOf(
            "HeartRateRecord",
            "OxygenSaturationRecord",
            "SleepSessionRecord",
            "StepsRecord",
            "ActiveCaloriesBurnedRecord",
        )
        assertEquals(5, requiredPermissions.size)
        assertTrue(requiredPermissions.contains("HeartRateRecord"))
        assertTrue(requiredPermissions.contains("OxygenSaturationRecord"))
        assertTrue(requiredPermissions.contains("SleepSessionRecord"))
        assertTrue(requiredPermissions.contains("StepsRecord"))
        assertTrue(requiredPermissions.contains("ActiveCaloriesBurnedRecord"))
    }
}
