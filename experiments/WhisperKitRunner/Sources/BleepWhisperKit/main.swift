import Foundation
import WhisperKit
import ArgmaxCore
import Darwin
import CoreML

// Model acquisition belongs to Python's explicit, pinned download step. Even a
// tokenizer fallback inside the SDK must not silently access the network here.
final class NoNetwork: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool {
        ["http", "https"].contains(request.url?.scheme ?? "")
    }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)) }
    override func stopLoading() {}
}

struct Request: Decodable {
    var audio: String
    var modelFolder: String
    var output: String
    var language: String?
    var computeUnits: String?
}
struct Word: Encodable {
    var word: String
    var start: Double
    var end: Double
}
struct Result: Encodable {
    var words: [Word]
    var loadSeconds: Double
    var inferenceSeconds: Double
    var peakMemoryBytes: Int
    var computeUnits: String
    var sdkVersion = "1.1.0"
}
func emit(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value), let line = String(data: data, encoding: .utf8) {
        print(line); fflush(stdout)
    }
}

@main
struct Runner {
    static func main() async {
        do {
            _ = URLProtocol.registerClass(NoNetwork.self)
            guard CommandLine.arguments.count == 2 else { throw NSError(domain: "Supply a request JSON path", code: 1) }
            let request = try JSONDecoder().decode(Request.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
            let language = request.language ?? "ru"
            guard ["ru", "en"].contains(language) else { throw NSError(domain: "Unsupported media language", code: 1) }
            let computeUnits = request.computeUnits ?? "default"
            guard ["default", "cpuAndNeuralEngine"].contains(computeUnits) else {
                throw NSError(domain: "Unsupported compute units", code: 1)
            }
            // Benchmark policy excludes GPU; Core ML still chooses CPU or ANE
            // per operation. Normal application requests keep SDK defaults.
            let computeOptions: ModelComputeOptions? = computeUnits == "cpuAndNeuralEngine"
                ? ModelComputeOptions(melCompute: .cpuOnly, audioEncoderCompute: .cpuAndNeuralEngine,
                                      textDecoderCompute: .cpuAndNeuralEngine) : nil
            let folder = URL(fileURLWithPath: request.modelFolder)
            let output = URL(fileURLWithPath: request.output)
            guard !FileManager.default.fileExists(atPath: output.path) else { throw NSError(domain: "Output already exists", code: 1) }
            // Validate locally before the SDK's tokenizer loader (which has a Hub fallback).
            _ = try await AutoTokenizerWrapper.from(modelFolder: folder)
            emit(["event": "stage", "stage": "Preparing WhisperKit · first run may take a few minutes"])
            let start = ProcessInfo.processInfo.systemUptime
            let pipe = try await WhisperKit(WhisperKitConfig(
                modelFolder: folder.path, tokenizerFolder: folder,
                computeOptions: computeOptions,
                verbose: false, prewarm: true, load: true, download: false))
            let loaded = ProcessInfo.processInfo.systemUptime
            pipe.segmentDiscoveryCallback = { segments in
                if let end = segments.map(\.end).max() { emit(["event": "progress", "seconds": end]) }
            }
            emit(["event": "stage", "stage": "Recognizing with WhisperKit (experimental)"])
            let options = DecodingOptions(language: language, temperature: 0, temperatureFallbackCount: 5,
                skipSpecialTokens: true, wordTimestamps: true, maxInitialTimestamp: 1,
                suppressBlank: true, concurrentWorkerCount: 1, chunkingStrategy: .vad)
            let results = try await pipe.transcribe(audioPath: request.audio,
                audioInputOptions: AudioInputOptions(audioLoadingMode: .incremental), decodeOptions: options)
            let finished = ProcessInfo.processInfo.systemUptime
            var words: [Word] = []
            for segment in results.flatMap(\.segments) {
                guard let timings = segment.words else {
                    if !segment.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        throw NSError(domain: "WhisperKit returned speech without word timestamps", code: 2)
                    }
                    continue
                }
                words += timings.map { Word(word: $0.word.trimmingCharacters(in: .whitespacesAndNewlines),
                                           start: Double($0.start), end: Double($0.end)) }
            }
            var usage = rusage()
            getrusage(RUSAGE_SELF, &usage)
            let result = Result(words: words, loadSeconds: loaded - start, inferenceSeconds: finished - loaded,
                                peakMemoryBytes: Int(usage.ru_maxrss), computeUnits: computeUnits)
            let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
            try encoder.encode(result).write(to: output, options: .atomic)
        } catch {
            emit(["event": "error", "message": error.localizedDescription])
            exit(1)
        }
    }
}
