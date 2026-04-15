import SwiftUI

struct ContentView: View {
    @EnvironmentObject var connection: ConnectionManager
    @State private var showScanner = false
    @State private var showSettings = false
    
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                VStack(spacing: 12) {
                    Circle()
                        .fill(connection.isConnected ? Color.green : Color.red)
                        .frame(width: 16, height: 16)
                    Text(connection.statusMessage)
                        .font(.headline)
                    if connection.isConnected {
                        Text("Connected to \(connection.brainHost):\(connection.brainPort)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(.ultraThinMaterial)
                .cornerRadius(16)
                
                if connection.isConnected {
                    HStack(spacing: 16) {
                        MetricCard(title: "Heart Rate", value: "\(connection.lastHeartRate)", unit: "bpm", color: .red)
                        MetricCard(title: "SpO2", value: "\(connection.lastSpO2)", unit: "%", color: .blue)
                    }
                }
                
                if !connection.isConnected {
                    Button("Scan QR Code to Pair") { showScanner = true }
                        .buttonStyle(.borderedProminent)
                    
                    Button("Manual Setup") { showSettings = true }
                        .buttonStyle(.bordered)
                } else {
                    Button("Disconnect", role: .destructive) { connection.disconnect() }
                        .buttonStyle(.bordered)
                }
                
                Spacer()
            }
            .padding()
            .navigationTitle("FERAL Node")
            .sheet(isPresented: $showScanner) {
                QRScannerView { info in
                    connection.configureFromPairing(info)
                    showScanner = false
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
        }
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
