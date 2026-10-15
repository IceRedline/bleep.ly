SPEEDTEST_PYTHON ?= .cache/speedtest/venv/bin/python
AUDIO ?= .cache/speedtest/turbo-en.flac
SPEEDTEST_ARGS ?=

.PHONY: speedtest speedtest-setup speedtest-audio
speedtest:
	$(SPEEDTEST_PYTHON) scripts/speedtest.py run --audio "$(AUDIO)" $(SPEEDTEST_ARGS)

# Explicit downloads and compilation, excluded from all measurements.
speedtest-setup:
	python3.11 -m venv .cache/speedtest/venv
	$(SPEEDTEST_PYTHON) -m pip install -r requirements-speedtest.txt
	$(SPEEDTEST_PYTHON) -m pip install --no-deps --force-reinstall --require-hashes -r scripts/release/requirements-mlx-macos15.lock
	swift build --package-path experiments/WhisperKitRunner --scratch-path .cache/whisperkit-build -c release
	$(SPEEDTEST_PYTHON) scripts/speedtest.py prepare

# VIDEO is the full original author-hosted reference; never committed.
speedtest-audio:
	$(SPEEDTEST_PYTHON) scripts/speedtest.py audio --video "$(VIDEO)" --output "$(AUDIO)"
