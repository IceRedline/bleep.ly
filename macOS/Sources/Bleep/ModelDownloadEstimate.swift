import Foundation

/// Full install estimates, including secondary models. Verified publisher file
/// sizes and revisions are recorded in docs/model-download-sizes.md.
struct ModelDownloadEstimate {
    let name: String
    let bytes: Int64
    let includesAligner: Bool

    init(backend: String, model: String) {
        includesAligner = backend == "mlx-qwen3-asr" || backend == "gigaam-mps"
        switch backend {
        case "whisperkit":
            name = "WhisperKit Large v3 Turbo"
            bytes = 1_626_165_383 + 2_993_180
        case "gigaam-mps":
            name = "GigaAM v3"
            bytes = 448_929_252 + 255_336 + 1_840_013_484
        case "mlx-qwen3-asr":
            name = "Qwen3-ASR 1.7B"
            bytes = 4_703_055_333 + 1_840_013_484
        case "parakeet-mlx":
            name = model == "parakeet-ultra" ? "Parakeet Ultra" : "Parakeet v3"
            bytes = model == "parakeet-ultra" ? 1_254_937_267 : 2_509_041_541
        case "mlx":
            name = model == "large-v3-turbo" ? "Whisper Large v3 Turbo · Apple GPU" : "Whisper Large v3 · Apple GPU"
            bytes = model == "large-v3-turbo" ? 1_613_977_880 : 3_083_520_685
        default:
            name = model == "large-v3-turbo" ? "Whisper Large v3 Turbo · CPU" : "Whisper Large v3 · CPU"
            bytes = model == "large-v3-turbo" ? 1_621_665_983 : 3_090_835_702
        }
    }

    var size: String { String(format: "%.1f GB", locale: Locale(identifier: "en_US_POSIX"), ceil(Double(bytes) / 100_000_000) / 10) }
    var summary: String {
        "\(name): approximately \(size) for a full download\(includesAligner ? ", including the required word alignment model" : "")."
    }
    var consentMessage: String {
        "\(summary) Cached files may reduce the download. Allow extra disk space for installation and processing.\n\nAllow this and future missing model downloads? Your recordings stay on your Mac. You can change this in Settings."
    }
}
