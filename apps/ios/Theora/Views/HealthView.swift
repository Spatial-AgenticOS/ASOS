import SwiftUI

struct HealthView: View {

    @ObservedObject var healthKit: HealthKitManager

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 20) {
                    if !healthKit.isAuthorized {
                        authorizationCard
                    }

                    LazyVGrid(columns: [
                        GridItem(.flexible(), spacing: 16),
                        GridItem(.flexible(), spacing: 16)
                    ], spacing: 16) {
                        MetricCard(
                            title: "Heart Rate",
                            value: healthKit.heartRate > 0
                                ? String(format: "%.0f", healthKit.heartRate)
                                : "--",
                            unit: "BPM",
                            icon: "heart.fill",
                            color: .red
                        )

                        MetricCard(
                            title: "SpO\u{2082}",
                            value: healthKit.spo2 > 0
                                ? String(format: "%.0f", healthKit.spo2)
                                : "--",
                            unit: "%",
                            icon: "lungs.fill",
                            color: .blue
                        )

                        MetricCard(
                            title: "Steps",
                            value: healthKit.steps > 0
                                ? "\(healthKit.steps)"
                                : "--",
                            unit: "today",
                            icon: "figure.walk",
                            color: .green
                        )

                        MetricCard(
                            title: "Calories",
                            value: healthKit.activeCalories > 0
                                ? String(format: "%.0f", healthKit.activeCalories)
                                : "--",
                            unit: "kcal",
                            icon: "flame.fill",
                            color: .orange
                        )
                    }
                    .padding(.horizontal)

                    wristbandSection
                }
                .padding(.vertical)
            }
            .navigationTitle("Health")
            .navigationBarTitleDisplayMode(.large)
            .refreshable {
                healthKit.startObserving()
            }
        }
    }

    // MARK: - Subviews

    private var authorizationCard: some View {
        VStack(spacing: 12) {
            Image(systemName: "heart.text.square.fill")
                .font(.system(size: 40))
                .foregroundColor(.accentColor)

            Text("Health Data Access")
                .font(.headline)

            Text("Allow THEORA to read your health data from HealthKit to provide personalized insights.")
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            Button("Enable HealthKit") {
                healthKit.requestAuthorization()
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
        .frame(maxWidth: .infinity)
        .background(Color(.systemGray6))
        .cornerRadius(16)
        .padding(.horizontal)
    }

    private var wristbandSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "applewatch")
                    .foregroundColor(.accentColor)
                Text("THEORA Wristband")
                    .font(.headline)
            }

            HStack(spacing: 8) {
                Circle()
                    .fill(Color.gray)
                    .frame(width: 8, height: 8)
                Text("Not connected")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }

            Text("Connect your THEORA wristband via Bluetooth to stream real-time sensor data to the Brain.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.systemGray6))
        .cornerRadius(16)
        .padding(.horizontal)
    }
}

// MARK: - Metric Card

struct MetricCard: View {
    let title: String
    let value: String
    let unit: String
    let icon: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(color)
                Text(title)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value)
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                Text(unit)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.systemGray6))
        .cornerRadius(16)
    }
}
