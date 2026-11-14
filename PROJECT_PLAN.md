# Standalone release

- [x] Isolate source in the requested NaviScout repository; exclude personal files and game-derived catalogs.
- [x] Add per-user configuration, build validation, verified profile backup and locally generated radar data.
- [x] Add a first-party offline installer and per-user Windows shortcuts/uninstaller.
- [x] Capture labeled screenshots and finish the illustrated preview.
- [x] Run behavior, setup, payload and packaging checks; build standalone binaries.
- [x] Inspect the packaged installer/setup and verify installed application/runtime behavior.
- [x] Publish the clean source/release and open the authorized upstream offer issue.

Published release: https://github.com/jfhutchi/NaviScout/releases/tag/v1.0.0

Upstream offer: https://github.com/tangerineturtle1/NX2navi/issues/724

The local development helper is updated from this source; its personal settings, saves and backups remain outside the repository. Only explicit source/documentation/screenshot/release files enter the distribution. User-reported diving timer success is distinguished from agent-observed tests.


# Version 1.1.0

- [x] Separate Items, Link and Minigames controls with independent refill switches.
- [x] Add confirmed run/swim, roll, jump and dive-depth controls.
- [x] Add enemy stealth using an independently owned native perception reason; verify On and Off live.
- [x] Match the in-game brown/gold menus, use toggle switches and add the Navi/Triforce icon.
- [x] Refresh all six screenshots, README and guide; identify NX2navi 0.9.2 as the tested port.
- [x] Pass 118 automated tests and code review; verify original-code and parameter restoration.
- [x] Rebuild and verify standalone application, installer, source archive and complete share ZIP.
- [x] Push clean source and publish the matching GitHub release.

Published 1.1.0: https://github.com/jfhutchi/NaviScout/releases/tag/v1.1.0

# Version 1.2.0

- [x] Add an independently toggleable 2x damage-to-enemies option with native ownership/cleanup tests and code-traced shared attack coverage. Live combat verification remains pending and is documented.
- [x] Restore signed height differences on near and distant collectible guidance.
- [x] Add game-map age availability and deduplicated per-area progress with age filters.
- [x] Fix chest-based heart completion using the game's actor-to-boolean reward mapping; four already-collected locations in the latest save were reproduced and corrected. Hyrule Field's last nearest Scrub reward remains uncollected according to its named flag.
- [x] Complete review, 132 tests, standalone build, installed payload verification, F8 UI verification, all README copies and seven refreshed screenshots.
- [x] Push the reviewed source and publish the matching 1.2.0 release; all six uploaded asset sizes and SHA-256 digests match the verified local artifacts.

Published 1.2.0: https://github.com/jfhutchi/NaviScout/releases/tag/v1.2.0

# Version 1.2.1

- [x] Add verified native run/swim and stealth layouts for NX2navi 0.10.1 while retaining the 0.9.2 reference layouts.
- [x] Keep jump and roll available when normal-running validation fails; add regression tests.
- [x] Confirm running and jumping with the player on 0.10.1; verify swimming values and stealth activation/cleanup.
- [x] Investigate the Scarecrow freeze: logs have no fatal stack; upstream issue #777 reports the same Forest Temple symptom and a 60 FPS workaround. The local game used Unlimited FPS; the player confirmed changing it to 60 FPS resolves the encounter on 0.10.1. The underlying engine defect has not been traced.
- [x] Refresh README copies and all seven screenshots; complete review, 139 tests, standalone build, 1,013-file installed payload verification and installed F8/live UI verification.
- [ ] Push source and publish the matching v1.2.1 release.
