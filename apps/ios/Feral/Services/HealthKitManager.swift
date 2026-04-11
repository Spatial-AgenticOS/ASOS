import Foundation
import HealthKit
import Combine

final class HealthKitManager: ObservableObject {

    @Published var heartRate: Double = 0
    @Published var steps: Int = 0
    @Published var spo2: Double = 0
    @Published var activeCalories: Double = 0
    @Published var isAuthorized: Bool = false

    private let store = HKHealthStore()
    private var queries: [HKQuery] = []
    private weak var brainClient: BrainClient?

    private let readTypes: Set<HKObjectType> = {
        var types = Set<HKObjectType>()
        if let hr = HKQuantityType.quantityType(forIdentifier: .heartRate) { types.insert(hr) }
        if let spo2 = HKQuantityType.quantityType(forIdentifier: .oxygenSaturation) { types.insert(spo2) }
        if let steps = HKQuantityType.quantityType(forIdentifier: .stepCount) { types.insert(steps) }
        if let cal = HKQuantityType.quantityType(forIdentifier: .activeEnergyBurned) { types.insert(cal) }
        return types
    }()

    init(brainClient: BrainClient? = nil) {
        self.brainClient = brainClient
    }

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func requestAuthorization() {
        guard isAvailable else { return }
        store.requestAuthorization(toShare: nil, read: readTypes) { [weak self] success, _ in
            DispatchQueue.main.async { self?.isAuthorized = success }
            if success { self?.startObserving() }
        }
    }

    // MARK: - Live Observation

    func startObserving() {
        observeHeartRate()
        fetchTodaySteps()
        fetchLatestSpO2()
        fetchTodayCalories()
    }

    func stopObserving() {
        for q in queries { store.stop(q) }
        queries.removeAll()
    }

    // MARK: - Heart Rate (anchored query for live updates)

    private func observeHeartRate() {
        guard let hrType = HKQuantityType.quantityType(forIdentifier: .heartRate) else { return }

        let query = HKAnchoredObjectQuery(
            type: hrType,
            predicate: nil,
            anchor: nil,
            limit: HKObjectQueryNoLimit
        ) { [weak self] _, samples, _, _, _ in
            self?.processHeartRateSamples(samples as? [HKQuantitySample])
        }

        query.updateHandler = { [weak self] _, samples, _, _, _ in
            self?.processHeartRateSamples(samples as? [HKQuantitySample])
        }

        store.execute(query)
        queries.append(query)
    }

    private func processHeartRateSamples(_ samples: [HKQuantitySample]?) {
        guard let latest = samples?.last else { return }
        let bpm = latest.quantity.doubleValue(for: HKUnit.count().unitDivided(by: .minute()))
        DispatchQueue.main.async { self.heartRate = bpm }
        brainClient?.sendSensorData(sensor: "heart_rate", value: ["bpm": bpm])
    }

    // MARK: - Steps (today cumulative)

    func fetchTodaySteps() {
        guard let stepsType = HKQuantityType.quantityType(forIdentifier: .stepCount) else { return }

        let calendar = Calendar.current
        let startOfDay = calendar.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(withStart: startOfDay, end: Date())

        let query = HKStatisticsQuery(
            quantityType: stepsType,
            quantitySamplePredicate: predicate,
            options: .cumulativeSum
        ) { [weak self] _, stats, _ in
            let count = stats?.sumQuantity()?.doubleValue(for: .count()) ?? 0
            DispatchQueue.main.async { self?.steps = Int(count) }
            self?.brainClient?.sendSensorData(sensor: "steps", value: ["steps": Int(count)])
        }

        store.execute(query)
        queries.append(query)
    }

    // MARK: - SpO2

    func fetchLatestSpO2() {
        guard let spo2Type = HKQuantityType.quantityType(forIdentifier: .oxygenSaturation) else { return }

        let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        let query = HKSampleQuery(
            sampleType: spo2Type,
            predicate: nil,
            limit: 1,
            sortDescriptors: [sortDescriptor]
        ) { [weak self] _, samples, _ in
            guard let sample = samples?.first as? HKQuantitySample else { return }
            let pct = sample.quantity.doubleValue(for: .percent()) * 100
            DispatchQueue.main.async { self?.spo2 = pct }
            self?.brainClient?.sendSensorData(sensor: "spo2", value: ["current": pct])
        }

        store.execute(query)
        queries.append(query)
    }

    // MARK: - Active Calories

    func fetchTodayCalories() {
        guard let calType = HKQuantityType.quantityType(forIdentifier: .activeEnergyBurned) else { return }

        let startOfDay = Calendar.current.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(withStart: startOfDay, end: Date())

        let query = HKStatisticsQuery(
            quantityType: calType,
            quantitySamplePredicate: predicate,
            options: .cumulativeSum
        ) { [weak self] _, stats, _ in
            let kcal = stats?.sumQuantity()?.doubleValue(for: .kilocalorie()) ?? 0
            DispatchQueue.main.async { self?.activeCalories = kcal }
        }

        store.execute(query)
        queries.append(query)
    }
}
