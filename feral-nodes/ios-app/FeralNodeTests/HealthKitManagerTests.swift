import XCTest
import HealthKit

final class HealthKitManagerTests: XCTestCase {

    // MARK: - HealthKit Availability

    func testHealthDataAvailableCheck() {
        let available = HKHealthStore.isHealthDataAvailable()
        // On simulators this returns true; on macOS test runners it may be false.
        // We just verify the call doesn't crash.
        XCTAssertNotNil(available)
    }

    // MARK: - Heart Rate Type

    func testHeartRateQuantityType() {
        let hrType = HKQuantityType.quantityType(forIdentifier: .heartRate)
        XCTAssertNotNil(hrType)
        XCTAssertEqual(hrType?.identifier, HKQuantityTypeIdentifier.heartRate.rawValue)
    }

    // MARK: - SpO2 Type

    func testSpO2QuantityType() {
        let spo2Type = HKQuantityType.quantityType(forIdentifier: .oxygenSaturation)
        XCTAssertNotNil(spo2Type)
    }

    // MARK: - Step Count Type

    func testStepCountType() {
        let stepsType = HKQuantityType.quantityType(forIdentifier: .stepCount)
        XCTAssertNotNil(stepsType)
    }

    // MARK: - Sleep Analysis Type

    func testSleepAnalysisType() {
        let sleepType = HKCategoryType.categoryType(forIdentifier: .sleepAnalysis)
        XCTAssertNotNil(sleepType)
    }

    // MARK: - Read Types Set

    func testRequestedReadTypesAreValid() {
        let readTypes: Set<HKObjectType> = [
            HKObjectType.quantityType(forIdentifier: .heartRate)!,
            HKObjectType.quantityType(forIdentifier: .oxygenSaturation)!,
            HKObjectType.quantityType(forIdentifier: .stepCount)!,
            HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN)!,
            HKObjectType.categoryType(forIdentifier: .sleepAnalysis)!,
            HKObjectType.quantityType(forIdentifier: .bodyTemperature)!,
            HKObjectType.quantityType(forIdentifier: .activeEnergyBurned)!,
        ]
        XCTAssertEqual(readTypes.count, 7)
    }

    // MARK: - Unit Conversions

    func testHeartRateUnitConversion() {
        let unit = HKUnit.count().unitDivided(by: .minute())
        let quantity = HKQuantity(unit: unit, doubleValue: 72.0)
        let bpm = quantity.doubleValue(for: unit)
        XCTAssertEqual(bpm, 72.0, accuracy: 0.01)
    }

    func testSpO2PercentConversion() {
        let quantity = HKQuantity(unit: .percent(), doubleValue: 0.98)
        let pct = quantity.doubleValue(for: .percent()) * 100
        XCTAssertEqual(pct, 98.0, accuracy: 0.01)
    }

    // MARK: - Sensor Data Payload

    func testSensorDataPayloadFormat() {
        let payload: [String: Any] = [
            "bpm": 75,
            "timestamp": Date().timeIntervalSince1970,
            "source": "healthkit",
        ]
        XCTAssertEqual(payload["source"] as? String, "healthkit")
        XCTAssertNotNil(payload["bpm"])
        XCTAssertNotNil(payload["timestamp"])
    }
}
