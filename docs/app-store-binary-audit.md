# Mac App Store native dependency audit

Build 21 was rejected for `_NSWindowDidOrderOnScreenNotification`, `_dcabs1_`,
`_lsame_`, and `_xerbla_array__`. The first string was in the optional Tcl/Tk
library shipped by python-build-standalone. The other three were undefined
Accelerate imports in SciPy's `cython_blas` and `cython_lapack` extensions, in
both Python runtimes. Code signing, upload validation and runtime smoke tests
do not detect every App Review API restriction.

Store candidate preparation now removes the unused Tcl/Tk stack and replaces
SciPy with the official, SHA-256-pinned 1.17.1 CPython 3.11 macOS 12 arm64 wheel.
That wheel uses bundled OpenBLAS instead of those Accelerate entry points.
Its lower wheel deployment target does not change the app's macOS 15 minimum.
The SciPy version and public Python API remain unchanged. No Apple API names
are hidden, renamed or stripped from an existing dependency.

Fetch the pinned wheel before preparing a candidate:

```sh
python3 scripts/release/app_store_runtime.py fetch
```

Run `testflight-macos.py prepare` with a new output directory and build number
as usual. Preparation installs the wheel, preserves its license notices and
records its provenance in `Contents/Resources/ThirdParty/app-store-runtime.json`.
The `sign` command repeats the audit before signing. Existing signed releases
and developer Python environments are not modified.

Inspect a prepared candidate independently:

```sh
python3 scripts/release/app_store_runtime.py audit build/testflight-0.1.9-22/bleeply.app
python3 scripts/release/bundle-macos.py --audit-only build/testflight-0.1.9-22/bleeply.app
```

The audit scans every Mach-O payload for the four exact rejected API references
and leftover native Tcl/Tk dependencies. Prefixed SciPy/OpenBLAS implementations
are distinct from Apple imports. This regression check is not a complete private
API database and cannot guarantee App Review approval.

Before upload, run the packaged-runtime smoke test in the App Sandbox. It covers
both runtimes, BLAS/LAPACK, signal resampling, sparse solving, ASR imports,
Metal/JIT, audio decoding, model-download consent, and audio/video export.
After upload, repeat a real TestFlight install and recognition/export test.
