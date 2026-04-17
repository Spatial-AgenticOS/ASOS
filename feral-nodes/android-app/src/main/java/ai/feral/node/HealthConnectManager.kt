package ai.feral.node

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.*
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import kotlinx.coroutines.*
import java.time.Instant
import java.time.temporal.ChronoUnit

class HealthConnectManager(private val context: Context) {
    private var client: HealthConnectClient? = null
    private var onData: ((Map<String, Any>) -> Unit)? = null
    private var job: Job? = null

    companion object {
        val REQUIRED_PERMISSIONS = setOf(
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(OxygenSaturationRecord::class),
            HealthPermission.getReadPermission(SleepSessionRecord::class),
            HealthPermission.getReadPermission(StepsRecord::class),
            HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
        )
    }
    
    fun setCallback(callback: (Map<String, Any>) -> Unit) { onData = callback }
    
    fun initialize(): Boolean {
        return try {
            client = HealthConnectClient.getOrCreate(context)
            true
        } catch (e: Exception) { false }
    }
    
    fun startPeriodicReads(scope: CoroutineScope) {
        job = scope.launch {
            while (isActive) {
                readHeartRate()
                readSpO2()
                readSteps()
                readSleep()
                readActiveCalories()
                delay(30_000)
            }
        }
    }
    
    fun stop() { job?.cancel() }
    
    private suspend fun readHeartRate() {
        val c = client ?: return
        try {
            val now = Instant.now()
            val response = c.readRecords(ReadRecordsRequest(
                HeartRateRecord::class,
                timeRangeFilter = TimeRangeFilter.between(now.minus(5, ChronoUnit.MINUTES), now)
            ))
            val latest = response.records.lastOrNull()?.samples?.lastOrNull()
            if (latest != null) {
                onData?.invoke(mapOf("type" to "heart_rate", "bpm" to latest.beatsPerMinute, "source" to "health_connect"))
            }
        } catch (_: Exception) {}
    }
    
    private suspend fun readSpO2() {
        val c = client ?: return
        try {
            val now = Instant.now()
            val response = c.readRecords(ReadRecordsRequest(
                OxygenSaturationRecord::class,
                timeRangeFilter = TimeRangeFilter.between(now.minus(1, ChronoUnit.HOURS), now)
            ))
            val latest = response.records.lastOrNull()
            if (latest != null) {
                onData?.invoke(mapOf("type" to "spo2", "percent" to latest.percentage.value, "source" to "health_connect"))
            }
        } catch (_: Exception) {}
    }
    
    private suspend fun readSteps() {
        val c = client ?: return
        try {
            val startOfDay = Instant.now().truncatedTo(ChronoUnit.DAYS)
            val response = c.readRecords(ReadRecordsRequest(
                StepsRecord::class,
                timeRangeFilter = TimeRangeFilter.between(startOfDay, Instant.now())
            ))
            val total = response.records.sumOf { it.count }
            onData?.invoke(mapOf("type" to "steps", "count" to total, "source" to "health_connect"))
        } catch (_: Exception) {}
    }
    
    private suspend fun readSleep() {
        val c = client ?: return
        try {
            val yesterday = Instant.now().minus(1, ChronoUnit.DAYS)
            val response = c.readRecords(ReadRecordsRequest(
                SleepSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yesterday, Instant.now())
            ))
            val totalMinutes = response.records.sumOf { 
                ChronoUnit.MINUTES.between(it.startTime, it.endTime)
            }
            onData?.invoke(mapOf("type" to "sleep", "hours" to totalMinutes / 60.0, "source" to "health_connect"))
        } catch (_: Exception) {}
    }

    private suspend fun readActiveCalories() {
        val c = client ?: return
        try {
            val startOfDay = Instant.now().truncatedTo(ChronoUnit.DAYS)
            val response = c.readRecords(ReadRecordsRequest(
                ActiveCaloriesBurnedRecord::class,
                timeRangeFilter = TimeRangeFilter.between(startOfDay, Instant.now())
            ))
            val totalKcal = response.records.sumOf { it.energy.inKilocalories }
            onData?.invoke(mapOf("type" to "active_calories", "kcal" to totalKcal, "source" to "health_connect"))
        } catch (_: Exception) {}
    }
}
