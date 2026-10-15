# bleeply Privacy Policy

Effective date: October 14, 2026

bleeply is developed by Artem Tabenskii. This policy describes the macOS application, including its TestFlight version.

## Your recordings stay on your Mac

bleeply processes the audio and video files you select on your Mac. Recordings, transcripts, censoring decisions and exports are not sent to the developer or to an online speech recognition service. The app does not require an account, contain advertising or include analytics or tracking SDKs.

## Model downloads

Speech recognition needs model files. Before the first download, the app asks for permission and shows the estimated size of the selected model and its required components. You can change download permission in Settings. Once the required files are downloaded, recognition works offline.

Downloads connect to Hugging Face and its delivery providers, or to Sber's GigaAM model CDN. These services receive ordinary network request information, such as your IP address and the model files requested. Your recordings and transcripts are not included. Hugging Face telemetry is disabled in the app. The providers operate under their own privacy policies: [Hugging Face](https://huggingface.co/privacy) and [SberDevices](https://sberdevices.ru/legal/).

## Data stored locally

The app saves preferences, downloaded models, recognition caches and history, your most recent review, a reference to the selected source file, custom word lists and your selected custom censor sound. Temporary working files can contain audio from your recording. Preview audio is limited to 7 GiB per session and is cleaned up when the session ends; interrupted sessions are cleaned up on a later run. Recognition cache and history are limited to 256 MiB and 30 days. Models and your saved review are retained until you remove them. Original media and exports remain in the locations you choose.

The TestFlight and Mac App Store versions store app-managed data in the macOS app container. The direct-download version uses the bleeply Application Support folder. System backups may include these files according to your Mac's backup settings.

## Your choices and deletion

You choose which media the app can access and where exports are saved. Turn off “Allow first-time model download” in Settings to prevent further model downloads. To remove app-managed data, quit bleeply and delete its app data folder. In the TestFlight version, open Finder → Go → Go to Folder and enter ~/Library/Containers/ly.bleep.desktop. In the direct-download version, use ~/Library/Application Support/bleeply. Removing these folders also removes saved reviews, custom lists, sounds and downloaded models. Delete original recordings and exports separately if desired.

## Support and TestFlight feedback

Support is available through [GitHub Issues](https://github.com/IceRedline/bleeply/issues). GitHub issues are public: do not attach private recordings, transcripts or personal information. If you choose to send feedback, the developer receives the information you submit, and GitHub processes it under [GitHub's privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

Apple may provide TestFlight feedback and crash information according to your Apple settings and [Apple's TestFlight privacy information](https://www.apple.com/legal/privacy/data/en/test-flight/). These services are separate from the app's local media processing.

## Contact and changes

For questions about this policy, contact Artem Tabenskii through [the project's support page](https://github.com/IceRedline/bleeply/issues). Updates to this policy will appear with a new effective date in the app and repository.
