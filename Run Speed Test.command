#!/bin/bash
# Double-click on macOS, or run: bash "Run Speed Test.command"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_URL="https://github.com/IceRedline/bleeply.git"

step() {
    PHASE="$*"
    printf '\n== %s ==\n' "$PHASE" | tee -a "$SETUP_LOG"
}

run_logged() {
    "$@" 2>&1 | tee -a "$SETUP_LOG"
}

finish() {
    local status=$1 name
    trap - EXIT
    set +e
    if [[ -n "$RAW_OUTPUT" ]]; then
        for name in report.json report.md; do
            if [[ -f "$RAW_OUTPUT/$name" ]] && ! cp "$RAW_OUTPUT/$name" "$OUTPUT/$name"; then
                status=1
                PHASE='saving reports'
                printf 'Could not copy %s. Original reports remain in: %s\n' "$name" "$RAW_OUTPUT" >&2
            fi
        done
    fi
    if [[ "$status" == 0 && "$PHASE" == completed ]]; then
        printf 'Completed successfully. Share report.json and report.md.\n' > "$OUTPUT/status.txt"
        printf '\nFinished. Send these two files:\n%s/report.json\n%s/report.md\n' "$OUTPUT" "$OUTPUT"
    elif [[ "$status" == 0 && "$PHASE" == prepared ]]; then
        printf 'Setup completed. No benchmark was run. Launch again without --prepare-only to measure.\n' > "$OUTPUT/status.txt"
        printf '\nSetup complete. Launch again to run the benchmark.\n'
    else
        printf 'Stopped during: %s\nExit code: %s\nReports, if present, may be incomplete. See setup.log and the Terminal output.\n' "$PHASE" "$status" > "$OUTPUT/status.txt"
        printf '\nStopped during: %s (exit %s). Details: %s\n' "$PHASE" "$status" "$OUTPUT"
    fi
    if [[ "$LOCK_OWNED" == 1 ]]; then
        rm -f "$LOCK/pid"
        rmdir "$LOCK"
    fi
    open "$OUTPUT" >/dev/null 2>&1 || true
    if [[ -t 0 ]]; then
        read -r -p 'Press Return to close this window… ' || true
    fi
    exit "$status"
}

acquire_lock() {
    if ! mkdir "$LOCK" 2>/dev/null; then
        local previous
        previous=$(cat "$LOCK/pid" 2>/dev/null || true)
        if [[ "$previous" =~ ^[0-9]+$ ]] && ! kill -0 "$previous" 2>/dev/null; then
            rm -f "$LOCK/pid"
            rmdir "$LOCK"
            mkdir "$LOCK"
        else
            printf 'Another speed test or setup is already running. Close it before starting another.\n' >&2
            return 1
        fi
    fi
    LOCK_OWNED=1
    printf '%s\n' "$$" > "$LOCK/pid"
}

find_brew() {
    if [[ -x /opt/homebrew/bin/brew ]]; then
        printf '/opt/homebrew/bin/brew\n'
    else
        command -v brew
    fi
}

install_homebrew() {
    local installer
    installer=$(mktemp "$SUPPORT/homebrew-install.XXXXXX")
    # Keep the official installer's interactive authorization prompts.
    curl --fail --location --retry 3 --output "$installer" https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh
    /bin/bash "$installer"
    rm -f "$installer"
    BREW=/opt/homebrew/bin/brew
}

ensure_tools() {
    step 'Preparing macOS developer tools'
    if ! xcode-select -p >/dev/null 2>&1; then
        printf 'Accept the macOS Command Line Tools installation dialog. Waiting for installation…\n'
        xcode-select --install || true
        local attempt
        for ((attempt=0; attempt<360; attempt++)); do
            if xcode-select -p >/dev/null 2>&1; then break; fi
            sleep 5
        done
    fi
    if ! xcrun --find swift >/dev/null 2>&1 || ! xcrun swift --version >/dev/null 2>&1; then
        printf 'Developer tools are not ready. Finish their installation / Xcode setup, then double-click this script again.\n' >&2
        return 1
    fi

    step 'Preparing Homebrew, Python 3.11 and FFmpeg 8'
    if ! BREW=$(find_brew); then install_homebrew; fi
    [[ -x "$BREW" ]] || { printf 'Homebrew installation did not finish. Run this script again after installation.\n' >&2; return 1; }
    export HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1
    local formula
    for formula in python@3.11 ffmpeg@8; do
        if ! "$BREW" list --versions "$formula" >/dev/null 2>&1; then
            run_logged "$BREW" install "$formula"
        fi
    done
    export PATH="$("$BREW" --prefix python@3.11)/bin:$("$BREW" --prefix ffmpeg@8)/bin:$("$BREW" --prefix)/bin:$PATH"
    command -v python3.11 >/dev/null
    command -v ffmpeg >/dev/null
    command -v ffprobe >/dev/null
}

find_source() {
    if [[ -f "$SCRIPT_DIR/scripts/speedtest.py" && -f "$SCRIPT_DIR/benchmarks/turbo-en.json" ]]; then
        # Works in a Git checkout or a downloaded source ZIP. Never update the
        # user's working checkout or mix its installed Python environment in.
        ROOT="$SCRIPT_DIR"
    else
        step 'Downloading benchmark source and reference audio'
        ROOT="$SUPPORT/source"
        if [[ ! -e "$ROOT" ]]; then
            run_logged git clone --depth 1 --branch main "$REPOSITORY_URL" "$ROOT"
        elif [[ -d "$ROOT/.git" ]]; then
            if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
                printf 'The managed source checkout has local edits. Preserve them and use a fresh copy of the launcher.\n' >&2
                return 1
            fi
            run_logged git -C "$ROOT" pull --ff-only origin main
        else
            printf 'The source download is incomplete: %s. Move that folder aside and launch again.\n' "$ROOT" >&2
            return 1
        fi
    fi
    [[ -f "$ROOT/benchmarks/fixtures/turbo-en.flac" ]] || {
        printf 'Bundled reference audio is missing. Obtain the complete speed-test source ZIP / checkout.\n' >&2
        return 1
    }
}

main() {
    local prepare_only=0 output_option=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prepare-only) prepare_only=1; shift ;;
            --output) [[ $# -ge 2 ]] || { printf 'Missing --output directory\n' >&2; return 2; }; output_option=$2; shift 2 ;;
            --help|-h) printf 'Usage: Run Speed Test.command [--prepare-only] [--output NEW_DIRECTORY]\n'; return 0 ;;
            *) printf 'Unknown option: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    [[ "$(uname -s)" == Darwin ]] || { printf 'This benchmark requires an Apple Silicon Mac with macOS 15 or newer.\n' >&2; return 1; }
    if [[ "$(uname -m)" != arm64 ]]; then
        if [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" == 1 ]]; then
            printf 'Relaunching natively on Apple Silicon…\n'
            set --
            [[ "$prepare_only" == 0 ]] || set -- "$@" --prepare-only
            [[ -z "$output_option" ]] || set -- "$@" --output "$output_option"
            exec /usr/bin/arch -arm64 /bin/bash "${BASH_SOURCE[0]}" "$@"
        fi
        printf 'Intel Macs are not supported by this three-pipeline benchmark.\n' >&2
        return 1
    fi
    local version
    version=$(sw_vers -productVersion)
    [[ "${version%%.*}" -ge 15 ]] || { printf 'macOS 15 or newer is required.\n' >&2; return 1; }
    [[ "$EUID" != 0 ]] || { printf 'Run as your normal user, without sudo.\n' >&2; return 1; }

    SUPPORT="$HOME/Library/Caches/bleeply-speedtest"
    local stamp
    stamp="$(date +%Y-%m-%d_%H-%M-%S)-$$"
    OUTPUT="${output_option:-$HOME/Desktop/bleeply Speed Test/$stamp}"
    mkdir -p "$(dirname "$OUTPUT")" "$SUPPORT"
    mkdir "$OUTPUT" # Never overwrite an earlier report.
    OUTPUT="$(cd "$OUTPUT" && pwd)"
    SETUP_LOG="$OUTPUT/setup.log"
    PHASE=starting RAW_OUTPUT="" LOCK_OWNED=0 LOCK="$SUPPORT/running.lock"
    trap 'finish $?' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    acquire_lock
    printf 'bleeply Turbo speed test\nReports: %s\n' "$OUTPUT"
    printf 'First setup downloads several GB of models and dependencies. macOS / Homebrew may request installation approval or an administrator password.\n'
    printf 'Close heavy applications, turn Low Power Mode off and keep power conditions consistent. No recordings or reports are uploaded.\n'
    ensure_tools
    find_source
    step 'Verifying bundled reference audio'
    run_logged python3.11 "$ROOT/scripts/speedtest.py" verify-audio
    step 'Installing benchmark dependencies, building WhisperKit and preparing models'
    run_logged make -C "$ROOT" speedtest-setup
    if [[ "$prepare_only" == 1 ]]; then PHASE=prepared; return 0; fi
    step 'Running 12 offline measurements: CPU, GPU, CPU + Neural Engine'
    RAW_OUTPUT="$ROOT/.cache/speedtest/launcher-$stamp"
    run_logged caffeinate -i "$ROOT/.cache/speedtest/venv/bin/python" "$ROOT/scripts/speedtest.py" run --output "$RAW_OUTPUT"
    [[ -s "$RAW_OUTPUT/report.json" && -s "$RAW_OUTPUT/report.md" ]] || { printf 'The worker did not produce reports.\n' >&2; return 1; }
    PHASE=completed
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
