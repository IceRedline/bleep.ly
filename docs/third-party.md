# Open Source Licenses

bleeply includes software developed by the open source community. Copyright and license notices for Python packages are retained in their distribution metadata inside the app. WhisperKit and its Swift dependencies have separate notices in Contents/Resources/ThirdParty.

## FFmpeg and PyAV

This software uses libraries from the [FFmpeg project](https://ffmpeg.org/) under the GNU Lesser General Public License, version 2.1 or later (LGPL-2.1-or-later). FFmpeg 8.1.2 is built from unmodified sources without GPL, nonfree or version-3 components and without x264 or x265. The command-line helpers and the shared libraries used by PyAV are built separately.

[PyAV](https://github.com/PyAV-Org/PyAV) 18.1.0 is licensed under BSD-3-Clause. bleeply's distribution rebuilds PyAV from source and dynamically links it to the above FFmpeg libraries. The upstream prebuilt PyAV wheel is not used in the distribution.

The exact FFmpeg and PyAV source archives, license text, FFmpeg configuration and build scripts are included in Contents/Resources/ThirdParty/Sources inside the app. The sources are unmodified; no source patch is required. See BUILDING.txt there for rebuilding and replacing the libraries in a local copy. The app's code signature must be renewed after changing bundled libraries.

The LGPL-covered components remain under their own license. Nothing in bleeply's terms restricts modification of those components or reverse engineering for debugging such modifications. Their original authors retain ownership. The included LGPL text describes your rights in full.

## Other components

Mac App Store builds use the official SciPy 1.17.1 macOS 12 arm64 wheel with its bundled OpenBLAS implementation instead of the Accelerate-linked variant. SciPy, OpenBLAS and compiler runtime license notices are preserved in `scipy-1.17.1.dist-info/LICENSE.txt` in both Python runtimes. The wheel URL and SHA-256 are recorded in `Contents/Resources/ThirdParty/app-store-runtime.json`. The optional Tcl/Tk GUI stack is omitted; the application interface uses SwiftUI.

The app includes CPython (Python Software Foundation License), WhisperKit (MIT), and the Python packages listed in the bundled requirements lockfiles. See the ThirdParty folder and each runtime's lib/python3.11/site-packages/*dist-info license directories for their complete notices.

Recognition model weights are downloaded separately from their publishers. Their licenses and notices accompany the respective model repositories. bleeply does not claim ownership of third-party software or model weights.
