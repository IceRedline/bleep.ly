import XCTest
@testable import Bleep

final class SandboxFilesTests: XCTestCase {
    private func fixture() throws -> (URL, URL, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("sandbox-publish-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        let input = directory.appendingPathComponent("input.wav")
        try Data(repeating: 73, count: 2_100_003).write(to: input)
        return (directory, input, directory.appendingPathComponent("result.wav"))
    }

    func testPublishesAllBytesWithoutSiblingTemporaryFiles() throws {
        let (directory, input, output) = try fixture()
        try SandboxFiles.publish(input, to: output)
        XCTAssertEqual(try Data(contentsOf: input), try Data(contentsOf: output))
        XCTAssertEqual(Set(try FileManager.default.contentsOfDirectory(atPath: directory.path)), ["input.wav", "result.wav"])
    }

    func testNeverOverwritesExistingFileOrSymlink() throws {
        let (_, input, output) = try fixture()
        try Data("keep".utf8).write(to: output)
        XCTAssertThrowsError(try SandboxFiles.publish(input, to: output))
        XCTAssertEqual(try Data(contentsOf: output), Data("keep".utf8))
        try FileManager.default.removeItem(at: output)
        try FileManager.default.createSymbolicLink(at: output, withDestinationURL: input)
        XCTAssertThrowsError(try SandboxFiles.publish(input, to: output))
        XCTAssertEqual(try Data(contentsOf: input).count, 2_100_003)
    }

    func testMissingInputLeavesDestinationAbsent() throws {
        let (_, input, output) = try fixture()
        try FileManager.default.removeItem(at: input)
        XCTAssertThrowsError(try SandboxFiles.publish(input, to: output))
        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
    }

    func testCancellationLeavesDestinationAbsent() async throws {
        let (_, input, output) = try fixture()
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            try SandboxFiles.publish(input, to: output)
        }
        do { try await task.value; XCTFail("Cancelled publication must fail") }
        catch is CancellationError {}
        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
    }
}
