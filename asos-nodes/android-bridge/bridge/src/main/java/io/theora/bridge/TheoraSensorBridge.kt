package io.theora.bridge

import android.content.Context
import kotlinx.coroutines.*

/**
 * THEORA Sensor Bridge for Android — Health Connect + Wearable sensors.
 * Reads health data and forwards it to the Brain via TheoraBrainClient.
 */
class TheoraSensorBridge(
    private val context: Context,
    private val brainClient: TheoraBrainClient,
) {
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var telemetryJob: Job? = null
    private var intervalMs: Long = 5000L

    var lastHeartRate: Int? = null
        private set
    var lastSpO2: Int? = null
        private set
    var lastSteps: Int? = null
        private set
    var lastTemperature: Double? = null
        private set

    fun startPolling(intervalMs: Long = 5000L) {
        this.intervalMs = intervalMs
        telemetryJob?.cancel()
        telemetryJob = scope.launch {
            while (isActive) {
                readAndSend()
                delay(intervalMs)
            }
        }
    }

    fun stopPolling() {
        telemetryJob?.cancel()
        telemetryJob = null
    }

    private suspend fun readAndSend() {
        try {
            readHealthConnect()
        } catch (_: Exception) {
            // Health Connect may not be available
        }

        brainClient.sendSensorTelemetry(
            heartRate = lastHeartRate,
            spo2 = lastSpO2,
            steps = lastSteps,
            temperature = lastTemperature,
        )
    }

    private suspend fun readHealthConnect() {
        try {
            val hcClient = androidx.health.connect.client.HealthConnectClient
                .getOrCreate(context)

            val now = java.time.Instant.now()
            val oneMinuteAgo = now.minusSeconds(60)
            val timeRange = androidx.health.connect.client.time.TimeRangeFilter
                .between(oneMinuteAgo, now)

            // Heart rate
            try {
                val hrRequest = androidx.health.connect.client.request.ReadRecordsRequest(
                    recordType = androidx.health.connect.client.records.HeartRateRecord::class,
                    timeRangeFilter = timeRange,
                )
                val hrResponse = hcClient.readRecords(hrRequest)
                val latest = hrResponse.records.lastOrNull()
                if (latest != null && latest.samples.isNotEmpty()) {
                    lastHeartRate = latest.samples.last().beatsPerMinute.toInt()
                }
            } catch (_: Exception) {}

            // SpO2
            try {
                val spo2Request = androidx.health.connect.client.request.ReadRecordsRequest(
                    recordType = androidx.health.connect.client.records.OxygenSaturationRecord::class,
                    timeRangeFilter = timeRange,
                )
                val spo2Response = hcClient.readRecords(spo2Request)
                val latest = spo2Response.records.lastOrNull()
                if (latest != null) {
                    lastSpO2 = latest.percentage.value.toInt()
                }
            } catch (_: Exception) {}

            // Steps
            try {
                val stepsRequest = androidx.health.connect.client.request.ReadRecordsRequest(
                    recordType = androidx.health.connect.client.records.StepsRecord::class,
                    timeRangeFilter = androidx.health.connect.client.time.TimeRangeFilter
                        .between(
                            java.time.Instant.now().atZone(java.time.ZoneId.systemDefault())
                                .toLocalDate().atStartOfDay(java.time.ZoneId.systemDefault()).toInstant(),
                            now,
                        ),
                )
                val stepsResponse = hcClient.readRecords(stepsRequest)
                lastSteps = stepsResponse.records.sumOf { it.count }.toInt()
            } catch (_: Exception) {}

        } catch (_: Exception) {
            // Health Connect not installed
        }
    }

    fun updateManualReading(heartRate: Int? = null, spo2: Int? = null, temperature: Double? = null) {
        heartRate?.let { lastHeartRate = it }
        spo2?.let { lastSpO2 = it }
        temperature?.let { lastTemperature = it }
    }

    fun destroy() {
        stopPolling()
        scope.cancel()
    }
}
