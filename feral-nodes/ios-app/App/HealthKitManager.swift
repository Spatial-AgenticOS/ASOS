import Foundation
import HealthKit

class HealthKitManager: ObservableObject {
    private let healthStore = HKHealthStore()
    @Published var isAuthorized = false
    @Published var lastHeartRate: Double = 0
    @Published var lastSpO2: Double = 0
    @Published var todaySteps: Int = 0
    @Published var lastSleepHours: Double = 0
    
    private var brainClient: FeralBrainClient?
    private var timer: Timer?
    
    func setBrainClient(_ client: FeralBrainClient) {
        self.brainClient = client
    }
    
    func requestAuthorization() {
        guard HKHealthStore.isHealthDataAvailable() else { return }
        
        let readTypes: Set<HKObjectType> = [
            HKObjectType.quantityType(forIdentifier: .heartRate)!,
            HKObjectType.quantityType(forIdentifier: .oxygenSaturation)!,
            HKObjectType.quantityType(forIdentifier: .stepCount)!,
            HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN)!,
            HKObjectType.categoryType(forIdentifier: .sleepAnalysis)!,
            HKObjectType.quantityType(forIdentifier: .bodyTemperature)!,
            HKObjectType.quantityType(forIdentifier: .activeEnergyBurned)!,
        ]
        
        healthStore.requestAuthorization(toShare: nil, read: readTypes) { [weak self] success, error in
            DispatchQueue.main.async {
                self?.isAuthorized = success
                if success { self?.startPeriodicReads() }
            }
        }
    }
    
    func startPeriodicReads() {
        readLatestHeartRate()
        readLatestSpO2()
        readTodaySteps()
        readLastSleep()
        
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.readLatestHeartRate()
            self?.readLatestSpO2()
            self?.readTodaySteps()
        }
    }
    
    func stopReads() { timer?.invalidate() }
    
    private func readLatestHeartRate() {
        guard let type = HKQuantityType.quantityType(forIdentifier: .heartRate) else { return }
        let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        let query = HKSampleQuery(sampleType: type, predicate: nil, limit: 1, sortDescriptors: [sortDescriptor]) { [weak self] _, samples, _ in
            guard let sample = samples?.first as? HKQuantitySample else { return }
            let bpm = sample.quantity.doubleValue(for: HKUnit.count().unitDivided(by: .minute()))
            DispatchQueue.main.async {
                self?.lastHeartRate = bpm
                self?.brainClient?.sendSensorData(type: "heart_rate", data: ["bpm": bpm, "timestamp": sample.startDate.timeIntervalSince1970, "source": "healthkit"])
            }
        }
        healthStore.execute(query)
    }
    
    private func readLatestSpO2() {
        guard let type = HKQuantityType.quantityType(forIdentifier: .oxygenSaturation) else { return }
        let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        let query = HKSampleQuery(sampleType: type, predicate: nil, limit: 1, sortDescriptors: [sortDescriptor]) { [weak self] _, samples, _ in
            guard let sample = samples?.first as? HKQuantitySample else { return }
            let pct = sample.quantity.doubleValue(for: HKUnit.percent()) * 100
            DispatchQueue.main.async {
                self?.lastSpO2 = pct
                self?.brainClient?.sendSensorData(type: "spo2", data: ["percent": pct, "timestamp": sample.startDate.timeIntervalSince1970, "source": "healthkit"])
            }
        }
        healthStore.execute(query)
    }
    
    private func readTodaySteps() {
        guard let type = HKQuantityType.quantityType(forIdentifier: .stepCount) else { return }
        let startOfDay = Calendar.current.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(withStart: startOfDay, end: Date(), options: .strictStartDate)
        let query = HKStatisticsQuery(quantityType: type, quantitySamplePredicate: predicate, options: .cumulativeSum) { [weak self] _, result, _ in
            guard let sum = result?.sumQuantity() else { return }
            let steps = Int(sum.doubleValue(for: HKUnit.count()))
            DispatchQueue.main.async {
                self?.todaySteps = steps
                self?.brainClient?.sendSensorData(type: "steps", data: ["count": steps, "source": "healthkit"])
            }
        }
        healthStore.execute(query)
    }
    
    private func readLastSleep() {
        guard let type = HKCategoryType.categoryType(forIdentifier: .sleepAnalysis) else { return }
        let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: Calendar.current.startOfDay(for: Date()))!
        let predicate = HKQuery.predicateForSamples(withStart: yesterday, end: Date(), options: .strictStartDate)
        let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        let query = HKSampleQuery(sampleType: type, predicate: predicate, limit: 20, sortDescriptors: [sortDescriptor]) { [weak self] _, samples, _ in
            let totalSleep = (samples ?? []).compactMap { $0 as? HKCategorySample }
                .filter { $0.value == HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue || $0.value == HKCategoryValueSleepAnalysis.asleepCore.rawValue || $0.value == HKCategoryValueSleepAnalysis.asleepDeep.rawValue || $0.value == HKCategoryValueSleepAnalysis.asleepREM.rawValue }
                .reduce(0.0) { $0 + $1.endDate.timeIntervalSince($1.startDate) }
            let hours = totalSleep / 3600.0
            DispatchQueue.main.async {
                self?.lastSleepHours = hours
                self?.brainClient?.sendSensorData(type: "sleep", data: ["hours": hours, "source": "healthkit"])
            }
        }
        healthStore.execute(query)
    }
}
