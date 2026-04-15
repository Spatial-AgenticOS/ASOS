import SwiftUI
import AVFoundation

struct QRScannerView: UIViewControllerRepresentable {
    let onScan: (PairingInfo) -> Void
    
    func makeUIViewController(context: Context) -> QRScannerViewController {
        let vc = QRScannerViewController()
        vc.onScan = onScan
        return vc
    }
    
    func updateUIViewController(_ vc: QRScannerViewController, context: Context) {}
}

class QRScannerViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onScan: ((PairingInfo) -> Void)?
    private let session = AVCaptureSession()
    
    override func viewDidLoad() {
        super.viewDidLoad()
        
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device) else { return }
        
        session.addInput(input)
        
        let output = AVCaptureMetadataOutput()
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        
        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.frame = view.bounds
        preview.videoGravity = .resizeAspectFill
        view.layer.addSublayer(preview)
        
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.session.startRunning()
        }
    }
    
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput results: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard let result = results.first as? AVMetadataMachineReadableCodeObject,
              let string = result.stringValue,
              let data = string.data(using: .utf8),
              let info = FeralBrainClient.parsePairingQR(data) else { return }
        
        session.stopRunning()
        onScan?(info)
    }
}
