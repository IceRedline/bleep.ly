# Unreleased

## TestFlight candidate 0.1.7 (17)

- Added an offline Privacy Policy, GitHub support information and open source
  notices in Settings and the Help menu.
- Show the selected model's estimated download size before permission and in
  Settings, including required alignment models.
- Rebuild PyAV against LGPL-only FFmpeg without x264/x265. Include the exact
  corresponding sources, license and rebuild instructions in the app, and reject
  incompatible libraries during packaging.
- Prepare a separate sandboxed TestFlight candidate and signed installer while
  preserving the notarized direct-download release.

See [TestFlight handoff](../testflight-review.md) for metadata and review notes.
