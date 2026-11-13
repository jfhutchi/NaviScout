# Navi Scout

A standalone Windows companion for **NX2navi**: camera-relative collectible guidance, optional supply refills, and minigame assists. Install it separately from the game.

**[Download the latest release](https://github.com/jfhutchi/NaviScout/releases/latest)**

Version **1.1.0** adds an in-game-menu-inspired umber/gold design, a Navi/Triforce icon, switch controls, and separate **Items**, **Link** and **Minigames** tabs. New abilities include **Run / swim speed 2x**, separate **Roll speed 2x** and **Jump height 2x**, **Invisible to enemies**, and **Dive limit: Off / 2x / Unlimited**. The player confirmed running, swimming, rolling, jumping and both dive modes in live play. **Tested on NX2navi 0.9.2:** the player also confirmed enemies ignore Link with stealth On and detect him again with it Off. This version also keeps the magic refill fix working after loading a save with an uninitialized capacity cache.

**[See the illustrated preview before installing](docs/START-HERE.html)**

![Navi Scout sample radar and refill controls](docs/screenshots/radar-preview.png)

*Illustrative preview using labeled sample data. No game is attached in this screenshot.*

## Compatibility

- Windows 10/11, x64. Tested on the development PC; a separate clean-PC test is still recommended.
- NX2navi game executable `ocarina.exe`, with extracted game build **E0F3CCFAF50065AE** (tested with NX2navi 0.9.2).
- Run/swim and enemy stealth additionally require their tested 0.9.2 Windows code signatures. Rebuilt or different port executables can fail these checks; the affected option stops with an explanation instead of patching unrecognized code.
- Other game builds, Hookshot, Lichii and emulators are not supported by this release.
- You provide your own installed game. No ROM, game executable, game assets, save or collectible catalog is distributed.

## Install

1. Download a release and extract the entire ZIP.
2. Open **START-HERE.html** to review screenshots, features and limitations.
3. Run **NaviScout-Setup-1.1.0.exe**, then choose **Install Navi Scout**. No Python or administrator installation is required.
4. Start Navi Scout. Close NX2navi once, choose your own `ocarina.exe`, and select **Prepare my game**.
5. Setup copies and SHA-256 verifies your existing game profile, then generates your private radar catalog from your game files.
6. Play normally. Use **F8** to hide/show the companion.

New installations start with refills, round ammo, timer freeze, movement overrides and dive overrides **off**. Each tab has its own controls, saved for your Windows account. Existing refill choices are migrated without enabling previously inactive assists.

To update an existing installation, close Navi Scout and run the new installer. Your game connection, settings and backups are retained. For the portable version, extract the new application into a separate folder and run it after closing the old copy.

This is an unsigned community application. Review the source and release checksums before running it. No antivirus or Windows security setting needs to be disabled.

## Features

| Feature | Behavior |
| --- | --- |
| Collectible radar | Missing Golden Skulltulas and heart-piece locations, filtered by area and live collection flags |
| Orientation | Camera-up, with a moving world-north indicator |
| Off-range guidance | An edge arrow toward the closest enabled missing collectible outside the radar circle |
| Alerts | Separate skull/heart switches, adjustable distance and optional sound |
| Supplies | Rupees, sticks, seeds, nuts, bombs, Bombchus, arrows, Magic Beans and Scrub seeds |
| Ownership | Unobtained items stay locked; bag/wallet upgrades determine capacity |
| Link meters | Separate health/magic controls refill existing containers/meters; grant no upgrades or abilities |
| Run / swim speed 2x | Doubles normal running translation and swimming speeds, including swim dash and heavy variants |
| Roll speed 2x | Separate roll boost using the effective ground-speed scale; independent of running |
| Invisible to enemies | Perception-based stealth; Link stays visible to the player |
| Jump height 2x | Doubles the normal jump-height setting; does not add a new jump button |
| Dive limit | Off, 2x current scale depth, or Unlimited depth during normal dives |
| Minigame ammo | Independent Bombchu, seed and arrow choices, bounded by the round's supplied allowance |
| Timer hold | Optional current-time hold for diving, Dampe's race, horse race, cucco search and running race |

Magic Beans cap at 10 and Scrub seeds at 30. Bombchus require ownership and use the bomb-bag cap. A rented minigame item may refill during its round even if its normal inventory bag is not owned. Bottle contents, quest/trade items, rewards and equipment are not granted. Fire/ice/light arrows share normal arrows and magic; no elemental arrow is unlocked.

## Using the three tabs

- **Items:** choose owned supplies, then use **Keep topped up** or **Refill once**.
- **Link:** choose health and magic, then use their separate **Keep meters topped up** or **Refill once**. Toggle **Run / swim speed 2x**, **Roll speed 2x** and **Jump height 2x** independently. Run and swim share one switch; dive depth remains separate.
- **Link / Dive limit:** select **2x** for twice the current scale's depth (3/6/9 m becomes 6/12/18 m), or **Unlimited** to remove that depth cutoff. Select **Off** to restore the normal limit. Scale ownership is unchanged.
- **Link / Invisible to enemies:** turn on before approaching an enemy. The request applies when gameplay resumes. It blocks new perception-based detection, while existing aggro, scripted fights and bosses can behave differently. The mechanism may also suppress friendly NPC awareness. Link's rendering and direct interaction controls are unchanged.
- **Minigames:** choose the round ammo types and enable **Keep round ammo topped up**. **Freeze minigame timer** remains a separate option.

![Link controls, labeled sample preview](docs/screenshots/link-controls.png)

![Minigame controls, labeled sample preview](docs/screenshots/minigame-controls.png)

## Limits and verification

- The radar is a separate companion window; it does not patch the original map. Its locally generated catalog covers 100 Skulltulas and 36 heart locations. A marker may still require night, equipment, another floor or progression.
- Resource checks run every quarter second. Health is refilled, not made invulnerable; zero health is not resurrected, and lethal damage can still occur between updates.
- Timer hold updates the shared minigame clock every 25 ms. Tiny subsecond movement can occur; games using different internal timing are outside its scope. Timed trading quests are excluded through active quest-stage checks.
- Normal dives end at a depth cutoff; the dive option changes that cutoff, not an oxygen countdown. Unlimited depth retains normal swimming, input, collision and surface rules. It does not add free swimming, unlock equipment, or claim immunity to every underwater hazard.
- Movement and dive overrides restore on switching Off or closing the helper. They change live memory only. If the helper is forcibly terminated or reports an unsuccessful restore, restart NX2navi to clear remaining overrides.
- Running uses a checked temporary override at normal movement's translation callback. It leaves turning speed and other action callbacks alone. Swimming doubles the owned player's existing normal, heavy, dash and heavy-dash speed settings, retaining the original values and inheritance flags for restoration. It does not change vertical dive speed or dive depth.
- Enemy stealth uses the game's own perception/sensor setter with a separate Navi Scout disable reason. It preserves other script/cutscene reasons and waits rather than evicting them if the reason list is full. Off removes only Navi Scout's reason. If closing while paused requires cleanup, the trainer stays open and asks you to resume play briefly before it finishes closing. Forced termination requires restarting NX2navi to clear remaining live overrides.
- Closing the helper stops all cheats. Hiding with F8 does not stop them. Loading/transition states pause writes, and unsupported data layouts are rejected.
- The current release passes 118 automated tests, including native-helper CPU-state preservation, thread-resume and interrupted-install failure paths, perception-list capacity guards, exact parameter restoration and separate control preferences. The player confirmed running, swimming, rolling, jumping and both dive modes work. Enemy stealth On/Off was confirmed in a live encounter; owned-reason removal, original-code restoration and temporary-memory release were also verified. Not every enemy or movement situation has been exhaustively tested.
- Bombchu bowling refills and a retained health refill were observed during live play. The user confirmed the diving timer hold worked. Other minigame modes have code-trace and automated coverage, but have not all been tested in live rounds.
- The release includes a machine-readable verification report for automated, extraction and packaging checks. A different PC's driver/security environment may behave differently.

## Your data and removal

Application files: `%LOCALAPPDATA%\Programs\NaviScout`.

Settings, private radar catalog, logs and verified profile backups: `%LOCALAPPDATA%\NaviScout`.

Uninstall through Windows **Installed apps**, or the Start menu's **Uninstall Navi Scout** shortcut. It removes Navi Scout and its shortcuts while retaining your game, settings and backup folder. There is no service, scheduled task, startup task, network listener or telemetry.

To restore a profile, close the game and helper, preserve the current profile, then copy a verified backup's complete `profile` folder back to the game. Keep the save journal and other profile files together.

## Build and test from source

Use 64-bit Python 3.12 with Tk support on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
$env:PYTHONPATH = "$PWD\app;$PWD\packaging"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe packaging\build_release.py
```

The build creates a standalone application, an offline per-user installer, a source archive and a preview inside `release`. A whitelist excludes local saves, catalogs, preferences, logs, caches and the development environment. The installer is implemented in this repository, so no external installer compiler is needed.

## Upstream offer and license

Navi Scout is an independent community companion, offered to the NX2navi developer for review, reuse or integration. It is not an official NX2navi or Nintendo release. The original project is [tangerineturtle1/NX2navi](https://github.com/tangerineturtle1/NX2navi).

Navi Scout's original source is MIT licensed; see [LICENSE](LICENSE). Bundled runtime dependencies retain their own licenses, shipped in `licenses` and described in [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). Game titles and trademarks belong to their respective owners.
