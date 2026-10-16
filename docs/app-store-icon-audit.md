# App Store icon packaging

## Observed issue

App Store Connect displayed the real icon for 0.1.3 (12), but a generated
`Placeholder.mill` image for 0.1.9 (21). Build 22 was still processing when
the investigation began. Its empty thumbnail alone does not prove a packaging
failure.

The signed build 22 contains a valid `AppIcon.icns`, including its 1024-pixel
rendition, and declares `CFBundleIconFile=AppIcon`. The ICNS generation script
has not changed since 0.1.3. Later builds added `Assets.car` for the accent color
and header logo, without a primary app icon in that catalog or a
`CFBundleIconName` declaration.

Controlled local packages with and without that theme-only catalog both expose
the standalone ICNS to Apple's `swinfo` upload-metadata extractor. Therefore,
the local experiment does **not** prove that the catalog alone caused the
server placeholder. The original icon file was not missing or corrupt.

## Packaging correction

`scripts/release/app_icons.py` generates the ten macOS icon slots from `icon.PNG`
and compiles them together with the existing theme using one `actool` invocation.
It selects `--app-icon AppIcon` and merges the compiler's partial Info.plist,
including `CFBundleIconName`, into the application metadata. The same compilation
produces the legacy ICNS fallback. There is only one catalog output, so a later
theme compilation cannot overwrite the primary icon.

Both distribution signing paths and the release audit reject a missing primary
icon declaration, missing ICNS fallback, or missing 1024×1024 AppIcon rendition.
The integration test compiles the real assets, checks the accent and header logo
remain present, and confirms that a theme-only replacement is rejected.

## Acceptance

Local compilation and upload-metadata extraction establish that the corrected
bundle declares and contains a primary icon. Final confirmation requires a new
uploaded build to finish processing and App Store Connect to display the actual
icon. Existing uploaded binaries cannot be changed. Publishing or submitting a
build for review is a separate operation.

Apple's supported workflow is documented in
[Add an app icon](https://developer.apple.com/help/app-store-connect/manage-app-information/add-an-app-icon/).
