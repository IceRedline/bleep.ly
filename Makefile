PYTHON ?= .venv/bin/python
AUDIO ?= .cache/speedtest/turbo-en.flac
SPEEDTEST_ARGS ?=

.PHONY: speedtest speedtest-setup speedtest-audio
speedtest:
	$(PYTHON) scripts/speedtest.py run --audio "$(AUDIO)" $(SPEEDTEST_ARGS)

# Explicit downloads and compilation, excluded from all measurements.
speedtest-setup:
	python3.12 -m venv .venv
	$(PYTHON) -m pip install -r requirements-speedtest.txt
	swift build --package-path experiments/WhisperKitRunner --scratch-path .cache/whisperkit-build -c release
	$(PYTHON) scripts/speedtest.py prepare

# VIDEO is the full original author-hosted reference; never committed.
speedtest-audio:
	$(PYTHON) scripts/speedtest.py audio --video "$(VIDEO)" --output "$(AUDIO)"
