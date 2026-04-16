import SwiftUI

struct ContentView: View {
    @EnvironmentObject var connection: ConnectionManager
    @StateObject private var healthKit = HealthKitManager()
    @StateObject private var voice = VoiceManager()
    @State private var showScanner = false
    @State private var selectedTab = 0
    
    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack {
                ChatView()
                    .navigationTitle("Chat")
                    .toolbar {
                        ToolbarItem(placement: .navigationBarTrailing) {
                            Button(action: { voice.isRecording ? voice.stopRecording() : voice.startRecording() }) {
                                Image(systemName: voice.isRecording ? "mic.fill" : "mic")
                                    .foregroundColor(voice.isRecording ? .red : .cyan)
                            }
                        }
                    }
            }
            .tabItem { Label("Chat", systemImage: "message") }
            .tag(0)
            
            NavigationStack {
                VStack(spacing: 20) {
                    HStack {
                        Circle().fill(connection.isConnected ? Color.green : Color.red).frame(width: 10, height: 10)
                        Text(connection.isConnected ? "Connected" : "Disconnected").font(.caption)
                        Spacer()
                    }.padding(.horizontal)
                    
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                        MetricCard(title: "Heart Rate", value: "\(Int(healthKit.lastHeartRate))", unit: "bpm", color: .red)
                        MetricCard(title: "SpO2", value: "\(Int(healthKit.lastSpO2))", unit: "%", color: .blue)
                        MetricCard(title: "Steps", value: "\(healthKit.todaySteps)", unit: "today", color: .green)
                        MetricCard(title: "Sleep", value: String(format: "%.1f", healthKit.lastSleepHours), unit: "hrs", color: .purple)
                    }.padding()
                    
                    if !healthKit.isAuthorized {
                        Button("Authorize HealthKit") { healthKit.requestAuthorization() }
                            .buttonStyle(.borderedProminent)
                    }
                    
                    Spacer()
                }
                .navigationTitle("Health")
            }
            .tabItem { Label("Health", systemImage: "heart") }
            .tag(1)
            
            NavigationStack {
                SettingsView()
                    .toolbar {
                        if !connection.isConnected {
                            ToolbarItem(placement: .navigationBarTrailing) {
                                Button("Scan QR") { showScanner = true }
                            }
                        }
                    }
            }
            .tabItem { Label("Settings", systemImage: "gear") }
            .tag(2)
        }
        .sheet(isPresented: $showScanner) {
            QRScannerView { info in
                connection.configureFromPairing(info)
                showScanner = false
            }
        }
        .onAppear {
            if connection.isConnected, let client = connection.client {
                healthKit.setBrainClient(client)
                voice.setBrainClient(client)
                healthKit.requestAuthorization()
            }
        }
        .preferredColorScheme(.dark)
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    let unit: String
    let color: Color
    
    var body: some View {
        VStack(spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(value).font(.title).fontWeight(.bold)
                Text(unit).font(.caption)
            }
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(color.opacity(0.1))
        .cornerRadius(12)
    }
}
