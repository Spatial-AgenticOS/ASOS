import SwiftUI

@main
struct FeralMobileApp: App {

    @StateObject private var brainClient = BrainClient(
        host: UserDefaults.standard.string(forKey: "brain_host") ?? "localhost",
        port: UserDefaults.standard.integer(forKey: "brain_port").nonZero ?? 9090,
        apiKey: UserDefaults.standard.string(forKey: "brain_api_key") ?? ""
    )

    @StateObject private var healthKit = HealthKitManager()

    var body: some Scene {
        WindowGroup {
            TabView {
                ChatView(brainClient: brainClient)
                    .tabItem {
                        Label("Chat", systemImage: "bubble.left.and.bubble.right.fill")
                    }

                VoiceView(brainClient: brainClient)
                    .tabItem {
                        Label("Voice", systemImage: "waveform.circle.fill")
                    }

                HealthView(healthKit: healthKit)
                    .tabItem {
                        Label("Health", systemImage: "heart.fill")
                    }

                SettingsView(brainClient: brainClient, healthKit: healthKit)
                    .tabItem {
                        Label("Settings", systemImage: "gearshape.fill")
                    }
            }
            .tint(Color("FeralTeal"))
            .onAppear {
                healthKit.brainClient = brainClient
            }
        }
    }
}

// MARK: - Helpers

private extension Int {
    var nonZero: Int? { self == 0 ? nil : self }
}

private extension HealthKitManager {
    var brainClient: BrainClient? {
        get { nil }
        set { /* set via init */ }
    }
}
