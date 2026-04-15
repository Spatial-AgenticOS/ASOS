/**
 FERAL Sensor Bridge
 =====================
 Connects the existing W300SensorManager (JWBle SDK) to the
 FERAL Brain via FeralBrainClient. Drop-in integration:

 1. W300SensorManager reads BLE sensor data from FERAL glasses
 2. FeralSensorBridge receives callbacks and forwards to Brain
 3. Brain fuses with other perception data (camera, audio, memory)

 Usage:
   let bridge = FeralSensorBridge(brainClient: client)
   bridge.startContinuousMonitoring()
*/

import Foundation

class FeralSensorBridge {
    
    private let brainClient: FeralBrainClient
    private var monitoringTimers: [FeralSensorType: Timer] = [:]
    private var isMonitoring = false
    
    struct MonitoringConfig {
        var heartRateInterval: TimeInterval = 5.0
        var spo2Interval: TimeInterval = 300.0
        var temperatureInterval: TimeInterval = 600.0
        var uvInterval: TimeInterval = 120.0
        var stepsInterval: TimeInterval = 60.0
    }
    
    var config = MonitoringConfig()
    
    init(brainClient: FeralBrainClient) {
        self.brainClient = brainClient
    }
    
    deinit {
        stopMonitoring()
    }
    
    // MARK: - Continuous Monitoring
    
    func startContinuousMonitoring() {
        guard !isMonitoring else { return }
        isMonitoring = true
        
        // HR — most frequent, critical for health awareness
        scheduleReading(.heartRate, interval: config.heartRateInterval) { [weak self] in
            self?.readHeartRate()
        }
        
        // Steps — moderate frequency
        scheduleReading(.steps, interval: config.stepsInterval) { [weak self] in
            self?.readSteps()
        }
        
        // SpO2 — less frequent (battery intensive)
        scheduleReading(.spo2, interval: config.spo2Interval) { [weak self] in
            self?.readSpO2()
        }
        
        // Temperature — infrequent
        scheduleReading(.temperature, interval: config.temperatureInterval) { [weak self] in
            self?.readTemperature()
        }
        
        // UV — moderate
        scheduleReading(.uv, interval: config.uvInterval) { [weak self] in
            self?.readUV()
        }
        
        // Notify Brain that glasses are connected
        brainClient.updateGlassesStatus(connected: true)
    }
    
    func stopMonitoring() {
        isMonitoring = false
        for (_, timer) in monitoringTimers {
            timer.invalidate()
        }
        monitoringTimers.removeAll()
        brainClient.updateGlassesStatus(connected: false)
    }
    
    // MARK: - Individual Sensor Reads
    
    /**
     These methods call into W300SensorManager.shared and forward
     the results to the Brain. They mirror the existing
     W300SensorManager API but route through FERAL instead of
     directly to OpenAI.
     
     NOTE: Requires W300SensorManager to be available in the
     build target. Import your existing JWBleDemo code alongside
     this bridge.
    */
    
    func readHeartRate() {
        #if canImport(JWBle)
        W300SensorManager.shared.getHeartRate { [weak self] result in
            switch result {
            case .success(let reading):
                self?.brainClient.sendSensorData(.heartRate, value: [
                    "bpm": reading.bpm,
                    "is_wearing": reading.isWearing,
                ])
            case .failure(let error):
                print("[FERAL Bridge] HR error: \(error)")
            }
        }
        #else
        brainClient.sendSensorData(.heartRate, value: [
            "bpm": 0,
            "status": "sdk_not_available"
        ])
        #endif
    }
    
    func readSpO2() {
        #if canImport(JWBle)
        W300SensorManager.shared.getSpO2 { [weak self] result in
            switch result {
            case .success(let reading):
                self?.brainClient.sendSensorData(.spo2, value: [
                    "current": reading.current,
                    "high": reading.high,
                    "low": reading.low,
                ])
            case .failure(let error):
                print("[FERAL Bridge] SpO2 error: \(error)")
            }
        }
        #else
        brainClient.sendSensorData(.spo2, value: [
            "current": 0,
            "status": "sdk_not_available"
        ])
        #endif
    }
    
    func readTemperature() {
        #if canImport(JWBle)
        W300SensorManager.shared.getTemperature { [weak self] result in
            switch result {
            case .success(let reading):
                self?.brainClient.sendSensorData(.temperature, value: [
                    "celsius": reading.celsius,
                    "fahrenheit": reading.fahrenheit,
                    "is_wearing": reading.isWearing,
                ])
            case .failure(let error):
                print("[FERAL Bridge] Temp error: \(error)")
            }
        }
        #else
        brainClient.sendSensorData(.temperature, value: [
            "celsius": 0,
            "status": "sdk_not_available"
        ])
        #endif
    }
    
    func readUV() {
        #if canImport(JWBle)
        W300SensorManager.shared.getUVLevel { [weak self] result in
            switch result {
            case .success(let reading):
                self?.brainClient.sendSensorData(.uv, value: [
                    "level": reading.level,
                ])
            case .failure(let error):
                print("[FERAL Bridge] UV error: \(error)")
            }
        }
        #else
        brainClient.sendSensorData(.uv, value: [
            "level": 0,
            "status": "sdk_not_available"
        ])
        #endif
    }
    
    func readSteps() {
        #if canImport(JWBle)
        W300SensorManager.shared.getSteps { [weak self] result in
            switch result {
            case .success(let reading):
                self?.brainClient.sendSensorData(.steps, value: [
                    "steps": reading.steps,
                    "distance_m": reading.distance,
                    "calories_kcal": reading.calories,
                ])
            case .failure(let error):
                print("[FERAL Bridge] Steps error: \(error)")
            }
        }
        #else
        brainClient.sendSensorData(.steps, value: [
            "steps": 0,
            "status": "sdk_not_available"
        ])
        #endif
    }
    
    // MARK: - Snapshot (all sensors at once)
    
    func readAllSensors() {
        readHeartRate()
        readSpO2()
        readTemperature()
        readUV()
        readSteps()
    }
    
    // MARK: - Private
    
    private func scheduleReading(_ sensor: FeralSensorType, interval: TimeInterval, action: @escaping () -> Void) {
        action() // Read immediately
        
        let timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { _ in
            action()
        }
        monitoringTimers[sensor] = timer
    }
}
