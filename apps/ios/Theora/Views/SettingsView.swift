import SwiftUI

struct SettingsView: View {

    @ObservedObject var brainClient: BrainClient
    @ObservedObject var healthKit: HealthKitManager

    @AppStorage("brain_host") private var host = "localhost"
    @AppStorage("brain_port") private var port = 9090
    @AppStorage("brain_api_key") private var apiKey = ""

    @State private var editHost = ""
    @State private var editPort = ""
    @State private var editKey = ""

    var body: some View {
        NavigationView {
            Form {
                connectionSection
                brainConfigSection
                healthSection
                aboutSection
            }
            .navigationTitle("Settings")
            .onAppear {
                editHost = host
                editPort = "\(port)"
                editKey = apiKey
            }
        }
    }

    // MARK: - Sections

    private var connectionSection: some View {
        Section {
            HStack {
                statusDot
                VStack(alignment: .leading) {
                    Text("Brain Connection")
                        .font(.headline)
                    Text(brainClient.connectionState.rawValue.capitalized)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                connectionButton
            }
        } header: {
            Text("Status")
        }
    }

    private var brainConfigSection: some View {
        Section {
            HStack {
                Text("Host")
                    .frame(width: 60, alignment: .leading)
                TextField("192.168.1.100", text: $editHost)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }

            HStack {
                Text("Port")
                    .frame(width: 60, alignment: .leading)
                TextField("9090", text: $editPort)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.numberPad)
            }

            HStack {
                Text("API Key")
                    .frame(width: 60, alignment: .leading)
                SecureField("your-api-key", text: $editKey)
                    .textFieldStyle(.roundedBorder)
            }

            Button("Save & Reconnect") {
                host = editHost
                port = Int(editPort) ?? 9090
                apiKey = editKey
                brainClient.configure(host: host, port: port, apiKey: apiKey)
                brainClient.disconnect()
                brainClient.connect()
            }
            .disabled(editHost.isEmpty)
        } header: {
            Text("Brain Configuration")
        } footer: {
            Text("Enter the IP address and port of the THEORA Brain running on your local network.")
        }
    }

    private var healthSection: some View {
        Section {
            HStack {
                Image(systemName: "heart.fill")
                    .foregroundColor(.red)
                Text("HealthKit")
                Spacer()
                Text(healthKit.isAuthorized ? "Authorized" : "Not Authorized")
                    .foregroundColor(.secondary)
            }

            if !healthKit.isAuthorized {
                Button("Request Access") {
                    healthKit.requestAuthorization()
                }
            }
        } header: {
            Text("Health Data")
        }
    }

    private var aboutSection: some View {
        Section {
            HStack {
                Text("Version")
                Spacer()
                Text("1.0.0")
                    .foregroundColor(.secondary)
            }
            HStack {
                Text("Node ID")
                Spacer()
                Text("theora-iphone")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        } header: {
            Text("About THEORA")
        }
    }

    // MARK: - Helpers

    @ViewBuilder
    private var statusDot: some View {
        Circle()
            .fill(statusColor)
            .frame(width: 12, height: 12)
    }

    private var statusColor: Color {
        switch brainClient.connectionState {
        case .connected: return .green
        case .connecting, .registering, .reconnecting: return .orange
        case .disconnected: return .red
        }
    }

    @ViewBuilder
    private var connectionButton: some View {
        if brainClient.isConnected {
            Button("Disconnect") { brainClient.disconnect() }
                .foregroundColor(.red)
        } else {
            Button("Connect") { brainClient.connect() }
        }
    }
}
