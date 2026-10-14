# TestFlight handoff: 0.1.7 (17)

The local candidate is `build/testflight-0.1.7-17/bleep.ly.app`; the upload artifact
is `build/testflight-0.1.7-17/bleep.ly-0.1.7-17.pkg`. The candidate uses the explicit
macOS Bundle ID `ly.bleep.desktop`, App Sandbox, Apple Distribution signing and
the matching Mac App Store Connect provisioning profile. It supports Apple
Silicon Macs running macOS 15.0 or later. The existing notarized build 16 is preserved.

## Public metadata

Publish the committed policy and support documentation to the repository before
submission, then confirm that the policy link opens without signing in. The new
policy is bundled in the app and works offline, but an unpublished GitHub path is
not a usable App Store Connect Privacy Policy URL.

| Field | Value |
| --- | --- |
| Privacy Policy URL, after publication | https://github.com/IceRedline/bleep.ly/blob/main/docs/privacy-policy.md |
| Support URL | https://github.com/IceRedline/bleep.ly/issues |
| Copyright | 2026 Artem Tabenskii |
| App category | Video |
| Login required | No |

App Store Connect metadata, App Privacy answers, age rating, review contact,
export-compliance answers and tester groups have not been changed. Complete them
in the app record. Review App Privacy answers against the published policy,
including model hosting and optional support/TestFlight feedback; local media
processing alone is not a substitute for answering Apple's questionnaire.
See [Apple's App Privacy guidance](https://developer.apple.com/app-store/app-privacy-details/).

## Beta description

bleep.ly recognizes speech locally and helps censor profanity in audio and video.
Open a file, review the detected words and mute intervals, choose a censor sound,
and export audio or video. Russian is supported, with experimental English and
additional recognition models. Recordings are processed on your Mac. Recognition
models download separately with permission and can then be used offline.

## What to test

Check first-run model download permission and the displayed size, recognition,
Advanced transcript review, custom word lists and sounds, preview playback,
audio/video export, cancellation and reopening a saved review. Verify Privacy
Policy, Support and Open Source Licenses from Settings and the Help menu.

## Notes for Beta App Review

No account, subscription or purchase is required. The app needs an Apple Silicon
Mac with macOS 15 or later. Choose a language on Home, then use Open Media or drag
an audio/video file into the window. The initial CPU Whisper Large v3 model needs
approximately 3.1 GB; Apple GPU with GigaAM v3 needs approximately 2.3 GB including
its required word aligner. Settings shows the estimate for the selected model.
The first missing model prompts for download permission. Allow additional disk
space for temporary files and exports. If downloads have previously been
declined, re-enable them in Settings and open the file again.

After analysis, use Advanced mode to inspect or edit detected words and mute
intervals. Automatic recognition can miss words. Choose a censor sound and export
to a new filename. Original recordings are not overwritten. Preview and export
do not upload recordings. Once required models are downloaded, recognition works
offline. Some model choices are explicitly labeled experimental for beta testing.

Privacy Policy and Support are available in Settings and Help. The policy is
included locally. FFmpeg/PyAV license notices, exact corresponding source archives
and rebuild instructions are included inside the app under
Contents/Resources/ThirdParty/Sources and can be revealed from Open Source Licenses.

## Local verification and submission boundary

The source changes passed 170 Python tests and 66 Swift tests. The new PyAV wheel
was checked for LGPL-only FFmpeg configuration, audio decoding and resampling.
The bundle compatibility audit inspected 572 native files and confirmed macOS
15.0 as the minimum. Preparation records source revisions and wheel checksums in
`preparation.json`. Local logs are under `.cache/testflight-prep`.

Package signature and installer permissions are checked by the signing script.
A separate diagnostic copy exercises the signed runtime payload in App Sandbox;
it is not the upload artifact. These local checks do not constitute App Store
Connect processing, Beta App Review approval or a TestFlight installation test.
No upload or submission is performed by this preparation workflow.

After the separately authorized upload, wait for App Store Connect processing,
resolve any reported validation issues, install through TestFlight on a clean
Mac/account, and complete the interactive workflows above before inviting testers.
