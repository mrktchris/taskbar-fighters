# Taskbar Fighters: UX and engagement research against real games and desktop companions

Date: 2026-10-21. Read-only research. Repo state read: `C:\Users\User\minis` at `06e3241` (README.md, RESULT.md, docs/COMPARISON.md,
docs/ARENA.md, MOVELIST.md). Nothing in the repo was edited, the app was not started or stopped, no screen was captured.

Numbers about other products come from the sources listed at the end. Steam player and review counts come from third-party trackers;
they are snapshots, and trackers disagree with each other (noted where it matters). Recommendations describe mechanics generically. Game
names appear only in the research columns.

---

## 1. What Taskbar Fighters already has, read as a UX audit

Strong already: zero-config detection, a real privacy story (numbers only, no network), lock-on fights, best-of-3 with HP, set pieces, a
scoreboard with W-L and a 7-day sparkline, fighter select, the arena, a tray menu, pause/flash/forge switches, `doctor`, `detect`.

Gaps a new user hits, in the order they hit them:

1. **Install friction.** The Windows zip is unsigned, so SmartScreen shows "More info > Run anyway" (README, Install table). Desktop
   Goose got the same "might put your PC at risk" warning and press coverage repeated it ([LaptopMag](https://www.laptopmag.com/news/i-let-the-goose-from-untitled-goose-game-rampage-all-over-my-desktop)).
2. **No first-run explanation.** Two fighters appear and start moving. Nothing on screen says the left one is Claude Code, that the
   plate's `ctx 74%` is the context fill, or that a fight means "working". The explanation lives in README images (`plates.png`).
3. **Settings are CLI and JSON.** The tray covers toggles, but fighter size, the taskbar `zone` (`[40, 900]`, measured on one
   2560x1440 display), arena options, startup-at-logon (`print-startup` only prints) and ignore lists need `minis.json` or a terminal.
   The zone is the worst one: a wrong zone puts fighters over taskbar icons, and the fix is editing pixel numbers.
4. **Quiet periods look broken.** With one agent and the sleeping bot, nothing happens for 8-15 minutes (rival timers). RESULT.md V5.1
   records the owner hitting exactly this ("one fighter stood alone and nothing fought").
5. **Fights do not say why they happened.** The mapping (working = clash, finished = handoff, limit = KO) is only in the README.
6. **Desktop weapons default on.** `forge` is on by default (README, Commands): every arena takes one in-RAM screenshot unless the user
   turns it off. It is handled carefully, but "screen capture on by default" is the exact pattern that sank Recall's first launch (section E).
7. **Little reason to look at the record.** `record.json` and `history.json` exist, but there is no place to see careers, rivalries
   or collections. Achievements are listed as "ideas not built yet".

---

## 2. Comparables: what made each one work (or fail)

### Desktop companions and screen-edge idlers

| product | concrete mechanics | numbers | lesson for us |
| --- | --- | --- | --- |
| **Bongo Cat** (Steam, free) | Cat slaps the taskbar on every key/click. A chest drops every **30 min the app is open**, and you open it with taps. Rarity 90% / 9.5% / 0.49% / 0.01% / 1 in 500,000. 10 items of one tier trade up for 1 of the next. Achievements at 100 ... 1,000,000 beats. | ~194k peak concurrent (trackers disagree: 193,859 vs 194,508), ~105-107k reviews, 96-97% positive. Dev says it is still **not profitable** (US$2-4k/month net, Mar-Jun 2025). | Activity in, cosmetic out, on a clock. Hats are tradeable on the Steam market, which is the money hook and the bot magnet (see Banana in E). [Steambase](https://steambase.io/apps/bongo-cat), [SteamPulse](https://www.steampulse.org/game/3419430), [Insider Gaming](https://insider-gaming.com/what-is-bongo-cat-on-steam/), [GamesFuze](https://gamesfuze.com/guides/bongo-cat-complete-hat-item-guide-tiers-exchange-legendaries/), [RAWG](https://rawg.io/games/bongo-cat-2), [WN Hub](https://wnhub.io/news/stores-and-publishing/item-48117) |
| **Rusty's Retirement** ($7) | Farm in a narrow strip at the bottom of the screen. Nothing bad happens if you leave, and progress carries on. Two core actions (plant, automate). Twitch viewers can spawn on the farm. | ~140k wishlists at launch, ~20k sales/day for 5 days, ~330k (GameDiscover) to 550k (Wikipedia) copies. 97% of ~14.7k reviews. $4 supporter pack: **11% attach**. Streams often tagged "Just Chatting" because it is not full screen. | Make it work beside real work, never punish absence, and give streamers a hook. Complaints: repetition, optimisation, and "I watch it instead of working". [GameDiscover](https://newsletter.gamediscover.co/p/how-rustys-retirement-idle-farmed), [Wikipedia](https://en.wikipedia.org/wiki/Rusty%27s_Retirement), [VaporLens](https://vaporlens.app/app/2666510/rustys_retirement), [MeinMMO](https://mein-mmo.de/rustys-retirement-lebensveraendernd/) |
| **Desktop Goose** (pay what you want) | Goose steals the cursor, drags notepads and memes onto the screen, tracks mud. Intrusiveness can be tuned, and users can add their own memes. | 500 downloads in 90 min. Creator's tweet ~160k likes. Used on Twitch streams. Defender warnings. | Chaos goes viral **because it is a prank you aim at someone else**. Not a model for an always-on tool. Its tuning knobs are the useful part. [LaptopMag](https://www.laptopmag.com/news/i-let-the-goose-from-untitled-goose-game-rampage-all-over-my-desktop), [Kotaku](https://kotaku.com/untitled-goose-fan-game-unleashes-havoc-on-your-desktop-1841351806), [Genbeta](https://www.genbeta.com/windows/ganso-que-destruye-tu-pc-juego-inspirado-untitled-goose-game-trae-arte-troleo-a-tu-escritorio-windows) |
| **Desktop Mate** (free + DLC) | 3D character on the desktop. Paid character DLCs. | Launched ~89% positive. The aggregate later fell to **Mixed** (5,746 up / 2,970 down). Main complaints: DLC prices (~2,200 yen a character), **no Workshop or mods**, high resource use, only two characters at once. | Locked, pricey cosmetics plus no modding turns early goodwill into Mixed. [VaporLens](https://vaporlens.app/app/3301060/desktop_mate), [Notebookcheck](https://www.notebookcheck.net/This-free-software-tops-the-Steam-charts-but-it-s-not-a-game.945113.0.html), [Steam DLC](https://store.steampowered.com/app/3359730/Desktop_Mate__DLC/) |
| **Shimeji** (2009, fan-driven) | Mascots walk, climb and sit on windows, throw windows, react to the mouse. Open sprite format. | ~8,000 DeviantArt results by Oct 2011. Fandom redraws kept it alive for 15 years. | An open art format is the growth engine. [Fanlore](https://fanlore.org/wiki/Shimeji), [Pixiv](https://dic.pixiv.net/en/a/Shimeji), [shimeji-ee](https://github.com/gil/shimeji-ee) |
| **Ropuka's Idle Island** ($3.99) | Resizable island you place anywhere and on any monitor. Frog mows grass. Slow upgrades over weeks. | 97% positive (1,907/1,969 on StMStat; 4,028 on another snapshot). | Placement freedom and slow, gentle progression work for watch-while-working games. [StMStat](https://stmstat.com/app/3416070), [GameStar](https://www.gamestar.de/artikel/entspannte-farming-sim-auf-steam-fuer-4-euro,3427056.html), [Automaton](https://automaton-media.com/articles/newsjp/ropukas-idle-island-20250204-327321/) |
| **Tiny Pasture** | Animals along the bottom of the screen. Poke and pet reactions. Collect colours and rarities. | Praised: reactions when poked, collecting. Panned: **gacha** ("hundreds to thousands of pulls for a 5-star"), late-game boredom. | Small direct reactions delight people. Gacha sours them. [VaporLens](https://vaporlens.app/app/3167550/tiny_pasture) |
| **Spirit City: Lofi Sessions** | Focus tool: timers, spirit companions to collect, a room to decorate, ambient sound. | Overwhelmingly Positive, ~14-15k reviews. | A companion tied to the user's real work rhythm, plus collection. [Steam](https://store.steampowered.com/app/2113850/Spirit_City_Lofi_Sessions/), [Aywren](https://aywren.com/2024/06/17/steam-gaming-spirit-city-lofi-sessions) |
| **Wallpaper Engine** | Separate "pause / stop" rules for when another app is maximised and when one is full screen, plus per-monitor pause. | Category leader. | Users expect fine-grained "get out of my way" rules. [Steam discussion](https://steamcommunity.com/app/431960/discussions/2/1752358461530583995), [wallpapers.com](https://wallpapers.com/blog/does-wallpaper-engine-affect-gaming-performance.html) |
| **Codex Pets** (May 2026, built in) | `/pet` overlay with states **working / waiting for input / ready for review**. Notifies on done or needs-input. 8 built-ins. `/hatch` makes a pet from an image. Contest prize for the best pets. | First party. | The headline signal is "your turn". Custom pets and a contest drive sharing. [Engadget](https://engadget.com/2162796/openai-introduces-ai-generated-pets-for-its-codex-app), [Hongkiat](https://www.hongkiat.com/blog/codex-pets-custom-hatch-guide/), [LetsDataScience](https://letsdatascience.com/news/openai-adds-codex-pets-floating-task-overlay-bfb48d20) |
| **Pixel Agents** (VS Code) | Each Claude Code terminal gets a character in a pixel office. Animation follows the real action (writing, reading, running). Speech bubble when the agent waits for permission. **Sub-agents appear as linked characters.** Office editor. | Many forks (Codex port etc.). | Sub-agents as visible helpers, and "waiting" as a bubble. [GitHub](https://github.com/pablodelucca/pixel-agents), [mdskills](https://www.mdskills.ai/skills/pixel-agents) |
| **Clawd on Desk** | Electron pet with 12 animations driven by agent hooks or log polling. One-click permission bubbles for Claude Code. | ~3-6k stars (sources disagree). | Most informative rival, but it writes hooks into agent config, which Taskbar Fighters deliberately does not. [BrightCoding](https://blog.brightcoding.dev/2026/09/29/rullerzhou-afkclawd-on-desk-desktop-pet-for-ai-coding-agents) |
| **Clippy / Office Assistant** | Popped up on weak triggers (typing "Dear") and interrupted. | Off by default in Office XP-era builds, removed in 2007. Microsoft's own research found most users irritated. | Never interrupt. Context-poor help is worse than none. [Mental Floss](https://www.mentalfloss.com/technology/computers/tragic-life-clippy-worlds-most-hated-virtual-assistant), [Dice](https://insights.dice.com/2019/03/22/clippy-corpse-offers-valuable-lessons/?amp) |

### Fighting games and spectator fighting

| game | mechanic worth borrowing | source |
| --- | --- | --- |
| **Street Fighter 6** | Real-time **commentary**: 10 commentators, colour commentary optional, subtitles in 13 languages. **Frame meter**: a bar of pips for startup/active/recovery, with an in-game infographic, which reviewers said teaches beginners. Ranked ladder from 1,000 LP up to Master, where Master Rate resets every 3 months and nobody is demoted out of Master. Battle Hub avatars. | [Wikipedia](https://en.wikipedia.org/wiki/Street_Fighter_6), [esports.gg](https://esports.gg/news/street-fighter-v/state-of-play-showcases-street-fighter-6s-insane-new-features/), [EventHubs frame meter](https://www.eventhubs.com/news/2022/sep/16/sf6-training-visual-frame-data), [Infil](https://words.infil.net/w03-sf6beta-p6.html), [EventHubs Master League](https://www.eventhubs.com/news/2023/aug/01/sf6-launches-master-league), [Esports.net ranks](https://www.esports.net/wiki/guides/street-fighter-ranks/) |
| **Smash Ultimate** | Results screen: the winner does one of ~3 random poses while the losers stand back **applauding**. Each character has its own congratulations screen. Stage hazards can be **toggled off**, a first in 19 years, and tournaments run with hazards and spirits off. | [SSBWiki victory pose](https://www.ssbwiki.com/Victory_pose), [SSBWiki credits](https://www.ssbwiki.com/credits), [Zelda Universe](https://zeldauniverse.net/2018/06/14/stage-hazards-are-now-optional-in-super-smash-bros-ultimate/), [SSBWiki rulesets](https://ssbwiki.com/Special:MobileDiff/1635988) |
| **Tekken 8** | **Ghosts**: AI that copies your habits from online and offline play. Patch 2.02 added "NICE!" / "Don't do that!" feedback to steer it. My Replay & Tips: watch a replay, get told the mistake, take over and practise on the spot. | [esports.gg](https://esports.gg/guides/tekken-8/tekken-8-super-ghost-battle), [Bandai Namco 2.02](https://www.bandainamcoent.com/news/tekken-8-patch-notes-v2-02), [GamingBolt](https://gamingbolt.com/tekken-8-overhauls-my-replay-and-tips-allows-for-real-time-practice) |
| **Brawlhalla** | Free battle-pass track that all players advance, gold pass $9.99, 12-week seasons, exclusive cosmetics that can come back through "Classic" passes. | [Brawlhalla wiki](https://brawlhalla.wiki.gg/wiki/Battle_Pass), [Battle Pass FAQ](https://www.brawlhalla.com/battle-pass-faq) |
| **Rivals of Aether** | Steam Workshop for characters, stages, skins and buddies. **Four community characters were made official.** A creation contest drew 100+ entries for a major event. | [rivalsofaether.com](https://rivalsofaether.com/?p=84), [Steam Workshop](https://steamcommunity.com/workshop/filedetails/discussion/3514263181/524225948489413718) |
| **Salty Bet** | Round-the-clock AI-vs-AI fights on Twitch. Viewers bet **fake** "Salty Bucks" (start with $400) in a betting window before each fight, and odds set the payout. The bets run on looks, loyalty and reputation, since nobody is judging skill. | [PC Gamer](https://www.pcgamer.com/salty-bet-1/), [LSBU paper on AI spectatorship](https://openresearch.lsbu.ac.uk/download/4bdbce1fb68846551a45eca7a0b031c409a8fdbd0aebd96c654e53af989dbc9e/481395/AISB19%20AI%20Spectatorship%20v2.pdf), [MoMA](https://www.moma.org/interactives/exhibitions/2013/designandviolence/saltys-dream-cast-casino-salty-bet/) |
| **Nidhogg** | Tug of war: the winner of an exchange earns the right to advance, momentum flips constantly, one hit kills, leads are fragile. Reviewers call it very easy to watch. | [Sprites & Dice](https://spritesanddice.com/reviews/nidhogg-review-refined-rawness/), [AV Club](https://www.avclub.com/nidhogg-review-pc) |
| **Pocket Rumble** | Two buttons, simplified inputs, an on-screen frame bar, 31 short lessons. Easy to pick up, still has depth. | [Nintendo Life](https://www.nintendolife.com/reviews/switch-eshop/pocket_rumble), [Gameranx](https://gameranx.com/updates/id/25097/article/pocket-rumble-returns-to-kickstarter-to-make-fighting-game-masters-out-of-all-of-us/) |
| **Mortal Kombat** | Fatalities grew out of the dizzy state: the free hit was moved to after the winner was decided. "Finish Him!" became a signature cue. Inputs were **kept secret** on purpose to create mystery. | [Wikipedia](https://en.wikipedia.org/wiki/Fatality_(Mortal_Kombat)), [Game Informer](https://www.gameinformer.com/b/features/archive/2015/07/21/the-brutal-history-of-mortal-kombat-fatalities.aspx), [Engadget](https://www.engadget.com/2011-02-15-mortal-kombat-dev-gives-how-to-lesson-on-fatality-design.html) |

### Engagement and meta systems

| system | evidence | source |
| --- | --- | --- |
| **Streaks** | Allowing 2 streak freezes instead of 1: **+0.38% DAU**. Streak wager (stake currency on 7 days): **Day-7 retention +14%**. Guilt-laden reminders drew criticism, especially for upsetting children. | [Duolingo blog](https://blog.duolingo.com/duolingo-streak-research/), [Duolingo engineering](https://making.duolingo.com/how-streaks-keep-duolingo-learners-committed-to-their-language-goals), [University XP / El País](https://www.universityxp.com/news/2025/7/25/we-havent-seen-you-in-a-while-duolingos-passive-aggressive-strategy-for-keeping-users-hooked) |
| **Care loops** | Tamagotchi: 10M units in under a year. A pet that could not be paused and could die within hours led to classroom bans and press stories of children grieving. | [Mental Floss](https://www.mentalfloss.com/fun/toys/tamagotchi-history), [Georgia Tech archive](https://sites.cc.gatech.edu/fce/archives/future/0208.html) |
| **Achievements** | Xbox: rarity tiers (under 10% counts as rare and gets its own sound and animation). Steam: global unlock percentages. GitHub Achievements (2022): visible by default, **criteria kept secret** ("we'll never tell"). A study of 300+ discussions found the reaction mixed, "no clear purpose", more users opting out. GitHub later disabled earning them in Community Discussions over spam farming. | [Kotaku](https://kotaku.com/two-ways-to-fix-achievements-on-the-xbox-one-1645752957), [GitHub blog](https://github.blog/news-insights/product-news/introducing-achievements-recognizing-the-many-stages-of-a-developers-coding-journey/), [arXiv study](https://arxiv.org/html/2303.14702v3) |
| **Season passes** | Done badly: Halo Infinite, where 3-4 hours of play bought about one tier. 343 had to add first-games-of-the-day XP and easier challenges. Done better: Brawlhalla's free track. | [Windows Central](https://www.windowscentral.com/halo-infinite-fans-angry-about-battle-pass), [TechRadar](https://www.techradar.com/news/halo-infinites-controversial-battle-pass-progression-just-got-a-whole-lot-better) |
| **Shareable recaps** | Spotify Wrapped: vertical cards sized so a screenshot needs no crop, share as the obvious final step, identity framing ("top 1% listener"), once a year. | [ADPList](https://adplist.substack.com/p/spotifys-most-popular-design), [Substack analysis](https://ecommercewithdev.substack.com/p/spotify-wrapped-what-it-takes-to) |

### Developer-tool gamification

| tool | mechanic | source |
| --- | --- | --- |
| **WakaTime** | Daily/weekly/monthly goals, email reminders, private leaderboards with friends. | [wakatime.com/features](https://wakatime.com/features) |
| **Power Mode** (VS Code) | Particles, fireworks, flames, screen shake (on by default, `powermode.enableShake` turns it off). One clone has ~55k installs. | [DEV](https://dev.to/pandiyancool/cool-vs-code-extension-set-your-code-on-fire-2oac), [Marketplace](https://marketplace.visualstudio.com/vsgallery/936788cc-7213-4d48-93ae-045694781214) |
| **GitHub contribution graph / Achievements** | See the achievements row above. | above |
| **Pixel Agents, Clawd on Desk, Codex Pets** | See the companions table. | above |
| **Stream chat brawlers** (Stream Buddies, Twitch Chat Avatars) | Viewers spawn as fighters from chat and brawl or attack the streamer. All need a Twitch login or OAuth token. | [Stream Buddies](https://gamesplusjames.itch.io/streambuddies), [el_tutsi devlog](https://el-tutsi.itch.io/twitch-chat-avatars/devlog/468807/chat-vs-streamer-mode) |

**Patterns across all of the above:**
- Winners run beside work, never punish absence, react to direct pokes, and grow through community art.
- Losers interrupt, lock cosmetics behind price or gacha, attach real money to drops, or capture more than users expect.

---

## 3. Recommendations: the ranked top 20

Columns: **Effort** S (under a day), M (a few days), L (a week or more). **Impact** E engagement, V virality, C clarity, D delight.
**Privacy**: OK means numbers-only, no network and no new capture. FLAG means it would break or stretch the promise.
Items marked *(in progress)* overlap work already under way; for those the note is how to do it well, not whether to.

| rank | feature | group | effort | impact | privacy |
| ---: | --- | --- | --- | --- | --- |
| 1 | Settings window with a drag-to-set taskbar zone | A | M | C, E | OK |
| 2 | First-run guided intro + a "What am I looking at?" legend | A | S | C | OK |
| 3 | Real moments get real moves (task done, needs you, compaction comeback, limit finisher) | B | S-M | C, D | OK |
| 4 | Instant replay of the last K.O. + GIF export on a synthetic backdrop + fight codes | D/B | M | V, D | OK |
| 5 | Hover card: the state in plain words | A | S | C | OK |
| 6 | Ask before the first desktop-weapons screen grab | A/E | S | trust | improves it |
| 7 | Careers, head-to-head rivalries and local ranks per program | C | M | E, V | OK |
| 8 | Achievements with visible criteria that never reward burning tokens *(in progress)* | C | M | E | OK |
| 9 | A collection book for moves, set pieces and finishers | C | S-M | E | OK |
| 10 | A results beat after each match | B | S | D, C | OK |
| 11 | Text commentary ticker on the scoreboard | B | S-M | D, C | OK |
| 12 | Streamer mode done right *(in progress)* | D | M | V | OK; chat link FLAG |
| 13 | Fighting style shaped by each program's own usage | B | M | D, C | OK |
| 14 | Signed installer + winget/Homebrew | A | M | C, conversion | OK |
| 15 | Explain quiet periods (rival countdown on the plate) | A | S | C | OK |
| 16 | "Call it": pick the winner before a match | B/C | S | E, D | OK |
| 17 | A shareable card framed around identity *(in progress)* | D | S-M | V | OK if content-free |
| 18 | Open fighter-pack format, validator and contest *(skin packs in progress)* | D | M-L | V, E | OK (local files) |
| 19 | Respect focus, battery and meetings (automatic calm mode) | A/B | S-M | trust | OK (macOS Focus FLAG) |
| 20 | Gentle streak with automatic rest days, no notifications | C | S | E | OK |
| 21 | Opt-in SFX, done politely *(in progress)* | B | S-M | D | OK |

### Group A: UX clarity

**1. Settings window with a drag-to-set taskbar zone** (M; C, E; OK)
- *What:* one small window from tray > Settings… with five tabs: Fighters (who, look, size), Effects (flash, arena intensity, desktop
  weapons, hazards), Taskbar (a live outline of the fight zone with two draggable handles, plus "Auto-fit"), Startup (a "Start with
  Windows/macOS" checkbox), Advanced (ignore list, opens `minis.json`).
- *Borrowed from:* Wallpaper Engine's Performance tab, which has a rule for each situation
  ([Steam](https://steamcommunity.com/app/431960/discussions/2/1752358461530583995)), and Ropuka's freely placed, resizable island
  ([GameStar](https://www.gamestar.de/artikel/entspannte-farming-sim-auf-steam-fuer-4-euro,3427056.html)). Players of desktop idlers expect
  to place the thing themselves.
- *Mapping:* the tray already exists and the select screen proves the app can take keyboard focus in one window. Reuse that window
  class. The zone handles replace hand-editing `zone: [40, 900]`, which today is measured on one 2560x1440 display. "Start with Windows"
  writes the scheduled task that `print-startup` already composes, and only when the user ticks it.
- *Win/mac:* Windows writes the task; macOS calls the existing `autostart on`. On Windows, Auto-fit can read the taskbar icon
  rectangle so the zone stops where the icons start (the DPI and edge work in progress needs this anyway).

**2. First-run guided intro + a "What am I looking at?" legend** (S; C; OK)
- *What:* on the very first start, a 3-card overlay pointing at the real windows: "This is **Claude Code**. It's working." >
  "**74%** of its context is used." > "They fight when an agent works and hand off when one finishes. Right-click for options." There is
  a Skip button, it shows **once**, and tray > "What am I looking at?" replays it. The legend card is the existing `plates.png` content
  drawn live.
- *Borrowed from:* SF6's frame meter, which comes with an infographic and was praised for teaching beginners
  ([Infil](https://words.infil.net/w03-sf6beta-p6.html)), and Pocket Rumble's 31 short lessons
  ([Nintendo Life](https://www.nintendolife.com/reviews/switch-eshop/pocket_rumble)). The Clippy lesson sets the limit: explain once,
  on request after that, never unprompted.
- *Mapping:* drawn on the existing click-through layered windows next to the plates. A `first_run_done` flag goes in `control.json`.
- *Win/mac:* same on both. On macOS, also point at the menu-bar icon, or at the notch badge when macOS hides the icon.

**5. Hover card: the state in plain words** (S; C; OK)
- *What:* hovering a fighter or plate for 600 ms shows a small card: "Codex · waiting for you · a tool call has gone unanswered for 52 s ·
  context 61% · resets in 2h10m". It disappears when the mouse leaves.
- *Borrowed from:* Codex Pets' three states (working, waiting, ready for review)
  ([Engadget](https://engadget.com/2162796/openai-introduces-ai-generated-pets-for-its-codex-app)) and Pixel Agents' waiting bubble
  ([GitHub](https://github.com/pablodelucca/pixel-agents)). Both say the real job of a companion is "is it my turn?".
- *Mapping:* the plate already knows every field. The sprite area is already hit-testable (it is draggable).
- *Win/mac:* macOS plates already fade under the mouse, so the card should appear beside the fade, not under the cursor.

**6. Ask before the first desktop-weapons screen grab** (S; trust; improves privacy)
- *What:* the first time an arena starts with `forge` on, a one-line banner before the grab: "Desktop weapons use one screenshot that
  stays in memory and is never saved. [Use it] [Window shapes only]". The answer is remembered. A small "weapons: on" marker stays in
  the arena HUD while the picture is held. Alternative: make shapes-only the default and the pixel grab opt-in.
- *Borrowed from (as a warning):* Recall, whose plan to capture by default drew "swift backlash" and a year of delays, and which shipped
  as a double opt-in ([SC Magazine](https://scmagazine.com/news/microsofts-ai-recall-feature-postponed-to-address-security-concerns),
  [TechRepublic](https://www.techrepublic.com/article/news-microsoft-recall-expands-rollout/)).
- *Mapping:* the shape fallback already exists for macOS without Screen Recording, so the second button costs nothing to build.
- *Win/mac:* macOS already never asks for Screen Recording. Windows has no OS prompt, which is why the app has to ask.

**14. Signed installer + winget/Homebrew** (M, plus a certificate cost; C and install conversion; OK)
- *What:* sign the Windows exe (or ship through the Store / winget) so SmartScreen does not stop first launch. Notarise the macOS app
  later. A `winget install` line and a Homebrew cask both carry an implicit endorsement.
- *Borrowed from (as a warning):* Desktop Goose launch coverage repeated the Defender warning in nearly every write-up
  ([LaptopMag](https://www.laptopmag.com/news/i-let-the-goose-from-untitled-goose-game-rampage-all-over-my-desktop)). Clawd on Desk ships on
  winget ([wingetly](https://wingetly.io/apps/rullerzhou-afk/clawd-on-desk)).
- *Win/mac:* a certificate decision for the owner. Spending money needs the owner's yes.

**15. Explain quiet periods** (S; C; OK)
- *What:* when one side is asleep, the sleeping plate counts down: "rival match in ~6 min" (tray tooltip too). "Bout now" sits next to it.
- *Borrowed from:* Rusty's Retirement's rule that nothing bad happens while you are away, and that you see progress when you look
  ([GameDiscover](https://newsletter.gamediscover.co/p/how-rustys-retirement-idle-farmed)). Quiet should look deliberate, not broken.
- *Mapping:* `next_rival` already exists in the brain. Put it on the bus and draw it.

**19. Respect focus, battery and meetings (automatic calm mode)** (S-M; trust; OK on Windows, FLAG on macOS)
- *What:* drop to a static idle (or `calm`) when Windows battery saver is on or the machine is on battery. Optionally do the same when
  Windows "Do not disturb" is on. Arena effects never start in those states.
- *Borrowed from:* Wallpaper Engine's pause rules; Desktop Mate's and Rusty's resource-use complaints
  ([VaporLens](https://vaporlens.app/app/3301060/desktop_mate)).
- *Win/mac:* battery state is a plain Win32/IOKit read (OK). Reading Focus state on macOS needs a user permission, so it is a FLAG: make
  it opt-in or leave it out. "Camera in use = meeting" detection reads OS privacy state, which is a FLAG; do not add it.

### Group B: delight and game feel

**3. Real moments get real moves** (S-M; C, D; OK, ctx numbers only)
- *What:* make the four most meaningful real events unmistakable and give each one its own move:
  - **Task finished**: the agent's fighter does a victory flourish and holds a small "done" flag until the mouse passes over it. This is
    the "ready for review" signal, and the handoff is easy to miss today.
  - **Needs you** (`waiting?`): the fighter turns to the screen and waves, and the plate goes amber. It already exists; make it the
    loudest thing on screen.
  - **Context compaction** (ctx drops from 85% or more to under 40% in one session): a **second wind** comeback with an HP refill and
    an aura. This is the moment users care about, it is pure numbers, and it maps onto fighting games' comeback mechanic.
  - **Context limit**: a "finish" cue before the K.O. finisher, so a limit reads as a finisher and not a random loss.
- *Borrowed from:* Mortal Kombat moved the dizzy free hit to the end of the match and gave it a cue
  ([Wikipedia](https://en.wikipedia.org/wiki/Fatality_(Mortal_Kombat))). Codex Pets' "ready for review" and "needs input" notifications.
- *Mapping:* telemetry already emits `finished`, `waiting?` and `limit`, and ctx history is stored. Compaction is one new rule over
  numbers already read.
- *Win/mac:* same.

**10. A results beat after each match** (S; D, C; OK)
- *What:* after "CLAUDE WINS 2-1", a 4-second strip: winner pose, loser clapping in the background, three numbers ("hits 23 · best
  combo 5 · ultimate landed"), then back to idle. Turn it off in Settings.
- *Borrowed from:* Smash's results screen, where losers stand back applauding and each fighter has ~3 random poses
  ([SSBWiki](https://www.ssbwiki.com/Victory_pose)).
- *Mapping:* the scoreboard result line plus the slot fighters. Both sides already share the timeline, so the stats come free from
  the plan.

**11. Text commentary ticker** (S-M; D, C; OK)
- *What:* one rotating line in the scoreboard: "CODEX lands the spiral orb!", "CLAUDE is waiting on you", "Third straight win for
  CURSOR". Text only, no voice. Off, minimal (key events only) or full.
- *Borrowed from:* SF6 real-time commentary: 10 commentators, colour commentary optional, subtitles in 13 languages
  ([esports.gg](https://esports.gg/news/street-fighter-v/state-of-play-showcases-street-fighter-6s-insane-new-features/)). Commentary
  explains *and* hypes, and it also answers "why are they fighting?" (clarity).
- *Mapping:* timeline directives (`@banner`, `@record`) already mark the events. Lines are templated from program names and numbers
  only.

**13. Fighting style shaped by each program's own usage** (M; D, C; OK)
- *What:* each program's picker weights drift slowly with its own numbers. A high share of working time makes it more aggressive. Often
  waiting on the user makes it parry and counter more. Often running near the limit makes it spend supers sooner. Show the style on the
  hover card ("style: pressure"). Add a reset.
- *Borrowed from:* Tekken 8's Ghosts, which learn your habits, plus the 2.02 feedback buttons
  ([esports.gg](https://esports.gg/guides/tekken-8/tekken-8-super-ghost-battle),
  [Bandai Namco](https://www.bandainamcoent.com/news/tekken-8-patch-notes-v2-02)).
- *Mapping:* `choreo.Picker` is already weighted by category. Feed it a small per-program profile kept in `history.json`. Both slots
  still derive the same timeline because the profile travels in the plan.

**16. "Call it": pick the winner before a match** (S; E, D; OK)
- *What:* when the VS card appears there is a 5-second window: click a fighter's name to back them. Correct calls build a local "called
  it" streak. Points are fake and local, and buy nothing.
- *Borrowed from:* Salty Bet, where viewers bet fake money on AI-vs-AI fights and the fun is in loyalty and reputation
  ([PC Gamer](https://www.pcgamer.com/salty-bet-1/), [LSBU paper](https://openresearch.lsbu.ac.uk/download/4bdbce1fb68846551a45eca7a0b031c409a8fdbd0aebd96c654e53af989dbc9e/481395/AISB19%20AI%20Spectatorship%20v2.pdf)).
  It gives a spectator-only app something to do. In `decided` mode the healthier program usually wins, so calling it is a tiny skill.
- *Mapping:* the scoreboard buttons are already hit-testable.

**21. Opt-in SFX, done politely** *(in progress)* (S-M; D; OK)
- *How to do it well:* off by default. Only K.O., ultimate and "needs you" make a sound (one cue each). Master volume. Mute
  automatically while another app holds the microphone, if that can be read without a permission; otherwise skip that part. Never play
  a sound outside a bout.
- *Evidence:* Power Mode ships with effects on and needs a setting to remove shake
  ([DEV](https://dev.to/pandiyancool/cool-vs-code-extension-set-your-code-on-fire-2oac)). Ambient tools that people leave on are the quiet
  ones (Rusty's, Spirit City).

### Group C: meta, progression and retention

**7. Careers, head-to-head rivalries and local ranks per program** (M; E, V; OK)
- *What:* a Records tab (in Settings, or opened by clicking the scoreboard) with each program's lifetime W-L, K.O.s, longest win streak,
  ultimates landed, and **head-to-head** ("Claude vs Codex 34-29, last 10: 6-4"). Local ranks climb by wins and never demote past a
  floor (Bronze > Silver > Gold > Master > Legend). A small rank badge appears on the plate.
- *Borrowed from:* SF6's ladder: league points, a Master tier where nobody is demoted, Master Rate resetting every 3 months
  ([EventHubs](https://www.eventhubs.com/news/2023/aug/01/sf6-launches-master-league)).
- *Mapping:* `record.json` already keeps W-L per program (V6). Head-to-head needs one more key per pair.
- *Why it matters:* "my Claude is 34-29 against Codex" is the tribal line people post (see 17).

**8. Achievements with visible criteria that never reward burning tokens** *(in progress)* (M; E; OK)
- *How to do it well:*
  - Show every criterion; maybe 3 secret ones that are clearly marked as secret.
  - Keep them local and never on a profile anywhere.
  - Three families: **Fight** (first ultimate, perfect round, comeback from under 10 HP), **Discovery** (see every set piece, every
    fighter's finisher), **Partnership** (an agent finished 10 tasks in a day, a compaction comeback, a week of handoffs).
  - **Never** achievements for token totals, hours worked or late nights. They reward cost and overwork, and get farmed.
  - Show "how many of yours" instead of a global rarity, since there is no network.
- *Evidence:* GitHub Achievements' secret criteria and "no clear purpose" got a mixed reception and growing opt-outs, and their spam
  farming forced GitHub to disable earning them in Discussions ([arXiv](https://arxiv.org/html/2303.14702v3),
  [GitHub blog](https://github.blog/news-insights/product-news/introducing-achievements-recognizing-the-many-stages-of-a-developers-coding-journey/)).
  Xbox rarity tiers show that a special sound and animation on rare unlocks works ([Kotaku](https://kotaku.com/two-ways-to-fix-achievements-on-the-xbox-one-1645752957)).
- *UI:* a small banner over the scoreboard for 3 s. It never takes focus and never shows during a "needs you" state.

**9. A collection book for moves, set pieces and finishers** (S-M; E; OK)
- *What:* a grid of every fighter's 68 moves, the 8 taskbar set pieces, the arena set pieces and the finishers. Seen ones are coloured
  with the date first seen; unseen ones are silhouettes. Click one to preview it (`setpiece_preview.py` already renders them).
- *Borrowed from:* collect-them-all in Bongo Cat, Tiny Pasture and Spirit City; Smash's per-character congratulations screens. Mortal
  Kombat's secrecy, where a silhouette you have not seen yet makes people watch
  ([Game Informer](https://www.gameinformer.com/b/features/archive/2015/07/21/the-brutal-history-of-mortal-kombat-fatalities.aspx)).
- *Why here:* the move set is deep (56 shared moves plus weapon families), but nobody can tell. The book turns depth already built into
  progress you can see.

**20. Gentle streak with automatic rest days** (S; E; OK)
- *What:* "your fighters have met 12 days in a row". Two rest days a week are absorbed automatically, there are no notifications, and
  the streak lives on the Records tab, not on the taskbar.
- *Evidence:* adding freezes raised Duolingo DAU 0.38% and a commitment wager raised D7 retention 14%
  ([Duolingo](https://blog.duolingo.com/duolingo-streak-research/), [Duolingo engineering](https://making.duolingo.com/how-streaks-keep-duolingo-learners-committed-to-their-language-goals)).
  Its guilt reminders are the documented downside ([University XP](https://www.universityxp.com/news/2025/7/25/we-havent-seen-you-in-a-while-duolingos-passive-aggressive-strategy-for-keeping-users-hooked)).
  Count days the app ran with a bout, not days the user worked.

**Unlockable cosmetics** (folds into 8 and 9; not ranked separately): colourways and victory poses earned on a steady clock (one unlock
per N hours the app has run, like Bongo Cat's 30-minute chest) plus achievement rewards. Never random paid pulls, never tradeable. The
first unlock comes in the first session (Halo Infinite's slow-tier backlash:
[Windows Central](https://www.windowscentral.com/halo-infinite-fans-angry-about-battle-pass)).

### Group D: social and virality

**4. Instant replay of the last K.O. + GIF export + fight codes** (M; V, D; OK)
- *What:*
  - Tray > "Replay last finish" replays the deciding exchange in slow motion on the taskbar.
  - "Save as GIF" renders that match **offline**, on the synthetic desktop the launch media already uses, into Pictures. No screen
    capture.
  - A **fight code** (e.g. `TF1-claude-codex-7F3A9C`) that anyone with the app can paste to watch the same fight.
- *Borrowed from:* replay review in SF6 and Tekken 8's My Replay & Tips
  ([GamingBolt](https://gamingbolt.com/tekken-8-overhauls-my-replay-and-tips-allows-for-real-time-practice)), and fighting-game replay
  IDs in general.
- *Why it is cheap here:* choreography is a pure function of the seed and the two move sets (README, How it works).
  `packaging/launch_media.py` and `tools/doc_images.py` already render matches offline. Store the last N plans (seeds plus characters,
  no usage data).
- *Privacy:* a synthetic backdrop means nothing from the user's screen. A fight code carries only seed, characters and an engine
  version, never ctx or state numbers.

**12. Streamer mode done right** *(in progress)* (M; V; OK, chat link FLAG)
- *How to do it well:*
  - A "Streaming" toggle turns desktop weapons off. Optionally it also hides the context and plan numbers and uses a solid backdrop
    window for OBS window capture (layered windows over the taskbar are awkward to capture).
  - Match events go to a local `stream.json` / static HTML file that OBS can read as a browser source from `file://`, so there is
    no server.
  - Suggest that streamers run **their platform's built-in predictions** for "who wins". That is the Salty Bet loop, run by the
    streamer's tools, not ours.
- *Evidence:* Rusty's streams were mis-tagged "Just Chatting" because the game is not full screen, and Twitch viewer spawns were its
  hook ([GameDiscover](https://newsletter.gamediscover.co/p/how-rustys-retirement-idle-farmed)). Desktop Goose spread through streams.
- **FLAG:** chat-driven fighters (viewers spawning or cheering) need a Twitch token and the network, as every chat-brawler tool does
  ([el_tutsi](https://el-tutsi.itch.io/twitch-chat-avatars/devlog/468807/chat-vs-streamer-mode)). If ever built, it belongs in a separate,
  clearly labelled optional plugin, never in the core app.

**17. A shareable card framed around identity** *(in progress)* (S-M; V; OK if content-free)
- *How to do it well:*
  - Vertical (1080x1920) and wide (1200x630) versions with a big **identity line** ("Your main: CLAUDE · 34-29 vs Codex · 3 comeback
    wins").
  - Rendered offline, with an obvious "Copy image" as the last step.
  - Weekly, not daily.
  - Never project names or window content; ctx numbers optional and off by default.
- *Evidence:* Wrapped's no-crop vertical cards, the share button as the final step, and "top 1%" identity copy
  ([ADPList](https://adplist.substack.com/p/spotifys-most-popular-design)).

**18. Open fighter-pack format, validator and contest** *(skin packs in progress)* (M-L; V, E; OK)
- *What:* a documented folder format (pose data for the rig, or sheet PNGs plus `anim.json`), `minis.py pack check <dir>` to validate
  it (palette cap, baseline, frame counts: the art tests already exist), and a gallery page in the repo. Later, a community contest whose
  winners join the roster.
- *Evidence:* Rivals of Aether made four Workshop characters official and drew 100+ contest entries
  ([rivalsofaether.com](https://rivalsofaether.com/?p=84)). Shimeji lived 15 years on fan packs. Desktop Mate's "no Workshop" plus paid
  skins pulled it to Mixed. Codex Pets runs a pet contest.
- *Privacy:* local files only. Pack import never executes code from a pack.

**Matchup card** (part of 17): "Claude vs Codex" lifetime card. Rivalries between tools are the culture the product rides on.

### Group E: what to deliberately NOT do (with the backlash behind each)

| don't | why, with evidence |
| --- | --- |
| **Interrupt**: pop-ups, speech bubbles that start on their own, focus theft, "tips" | Clippy: weak triggers and interruptions; Microsoft's own research found most users irritated, and it was turned off then removed ([Mental Floss](https://www.mentalfloss.com/technology/computers/tragic-life-clippy-worlds-most-hated-virtual-assistant)). Explain once (item 2), then only on request. |
| **Touch the user's input or real windows** (cursor theft, dragging windows) | Desktop Goose does this for laughs as a prank on someone else ([Kotaku](https://kotaku.com/untitled-goose-fan-game-unleashes-havoc-on-your-desktop-1841351806)). The product's promise is "visual only"; keep the `VisualOnly7` test as the guard. |
| **Capture the screen by default, or keep any capture** | Recall's capture-by-default plan caused a year of delays and a forced double opt-in ([SC Magazine](https://scmagazine.com/news/microsofts-ai-recall-feature-postponed-to-address-security-concerns)). Ask first (item 6). Never put a forged-weapon frame in a share card or GIF. |
| **Network, telemetry, accounts, online leaderboards** | BonziBuddy went from "friendly assistant" to adware/spyware classification, lawsuits and shutdown ([Wikipedia](https://en.wikipedia.org/wiki/BonziBuddy)). "No network" is a feature here; ranks, achievements and cards stay local. |
| **Tradeable drops, real-money value, gacha** | Banana: ~700k concurrent, of which about two-thirds were bots farming drops worth real money ([Wikipedia](https://en.wikipedia.org/wiki/Banana_(2024_video_game)), [PCGamesN](https://www.pcgamesn.com/steam/banana-scam-statement)). Tiny Pasture reviews pan gacha ([VaporLens](https://vaporlens.app/app/3167550/tiny_pasture)). Bongo Cat is still not profitable despite the market ([WN Hub](https://wnhub.io/news/stores-and-publishing/item-48117)). |
| **Pricey locked characters, no modding** | Desktop Mate fell from ~89% positive to Mixed on DLC price, no Workshop and resource use ([VaporLens](https://vaporlens.app/app/3301060/desktop_mate)). If money is ever wanted, copy Rusty's optional supporter pack (11% attach), not locked fighters. |
| **Guilt, decay, death, nagging** | Tamagotchi's un-pausable death led to classroom bans and stories of distressed children ([Mental Floss](https://www.mentalfloss.com/fun/toys/tamagotchi-history)). Duolingo's guilt reminders are criticised ([University XP](https://www.universityxp.com/news/2025/7/25/we-havent-seen-you-in-a-while-duolingos-passive-aggressive-strategy-for-keeping-users-hooked)). Fighters never get sad because the user took a day off. |
| **Rewarding token burn, hours worked or late nights** | Rewards the most expensive behaviour, invites farming (GitHub disabled earning achievements in Discussions over spam, [arXiv](https://arxiv.org/html/2303.14702v3)), and gamifies overwork. |
| **Hidden criteria, default-public badges** | GitHub's "we'll never tell" criteria and default-visible badges brought opt-outs ([GitHub blog](https://github.blog/news-insights/product-news/introducing-achievements-recognizing-the-many-stages-of-a-developers-coding-journey/)). |
| **FOMO: expiring seasonal exclusives, slow passes** | Halo Infinite's slow tiers forced emergency XP changes ([Windows Central](https://www.windowscentral.com/halo-infinite-fans-angry-about-battle-pass)). Brawlhalla's ranked titles never return ([wiki](https://brawlhalla.wiki.gg/wiki/Battle_Pass)). A desktop toy has no reason for this. |
| **Sound on by default, effects you cannot turn down** | Wallpaper Engine and Power Mode both had to add off-switches for effects ([Steam](https://steamcommunity.com/app/431960/discussions/2/1752358461530583995), [DEV](https://dev.to/pandiyancool/cool-vs-code-extension-set-your-code-on-fire-2oac)). Keep `flash off`, the intensity setting and the hazards toggle; add a single "calm everything" switch. |
| **Writing hooks into agent config to get richer states** | It would close the gap with Clawd on Desk, but break the "your tools untouched" promise that sets this product apart (docs/COMPARISON.md). |
| **Approve/deny buttons for agent permissions** | Sending input to agents moves the app from viewer to actor; the README promises it never touches agents. Point at the agent instead ("needs you"). |

---

## 4. Five quick wins (each under half a day)

1. **Rival countdown on the sleeping plate** ("rival match in ~6 min") and in the tray tooltip. `next_rival` already exists in the
   brain; put it on the bus and draw it. This fixes the "nothing is happening" reading the owner hit in V5.1.
2. **Tray > "What am I looking at?"** shows a 10-second legend overlay beside the real plates (name, state word, context bar, reset
   countdown, what a clash or handoff means), drawn from the same data as `plates.png`. Show it automatically once on first start.
3. **Desktop-weapons consent on first arena**: a one-line banner with [Use screenshot] / [Window shapes only], remembered in
   `control.json`. The shapes path already exists.
4. **"Start with Windows" checkbox in the tray**, writing the task that `print-startup` already composes, only when ticked (macOS:
   `autostart on`). Removes the most common reason to open a terminal.
5. **A results line with three numbers after every match** ("CLAUDE WINS 2-1 · 23 hits · best combo 5 · ultimate landed"), taken from
   the shared timeline the scoreboard already shows the result from.

Runner-up: **"Replay last finish"** in the tray. `record.json` does not keep the seed today (`records.record()` has no seed argument), so
the first step is storing the last plans; after that, replay is a small job and the cheapest start on item 4.

---

## 5. What I could not verify

- Current Steam numbers. All are tracker snapshots (Steambase, SteamPulse, Raijin, VaporLens, StMStat) and they disagree; the ranges
  are given.
- Rusty's Retirement's Twitch integration details: the in-game documentation was not reachable.
- Spirit City's exact focus-timer mechanics, the Smash spirit count, and Codex Pets' first-party docs (press coverage only).
- Replay storage: `minis_core/records.py` `record()` takes winner, loser, where and score but **no seed**, so `record.json` does not keep
  the plan today. Replay first needs the last N plans (seed plus characters) stored. The planner being deterministic is from the README;
  I did not test a replay.
- Whether Windows "Do not disturb" state can be read cleanly without extra permissions (item 19): not tested.

---

## Sources

Desktop companions and idlers
- Bongo Cat: https://steambase.io/apps/bongo-cat · https://www.steampulse.org/game/3419430 · https://insider-gaming.com/what-is-bongo-cat-on-steam/ · https://gamesfuze.com/guides/bongo-cat-complete-hat-item-guide-tiers-exchange-legendaries/ · https://rawg.io/games/bongo-cat-2 · https://wnhub.io/news/stores-and-publishing/item-48117 · https://raijin.gg/app/3419430/Bongo_Cat
- Rusty's Retirement: https://newsletter.gamediscover.co/p/how-rustys-retirement-idle-farmed · https://en.wikipedia.org/wiki/Rusty%27s_Retirement · https://vaporlens.app/app/2666510/rustys_retirement · https://mein-mmo.de/rustys-retirement-lebensveraendernd/ · https://streamscharts.com/games/rustys-retirement
- Desktop Goose: https://www.laptopmag.com/news/i-let-the-goose-from-untitled-goose-game-rampage-all-over-my-desktop · https://kotaku.com/untitled-goose-fan-game-unleashes-havoc-on-your-desktop-1841351806 · https://www.genbeta.com/windows/ganso-que-destruye-tu-pc-juego-inspirado-untitled-goose-game-trae-arte-troleo-a-tu-escritorio-windows
- Desktop Mate: https://vaporlens.app/app/3301060/desktop_mate · https://www.notebookcheck.net/This-free-software-tops-the-Steam-charts-but-it-s-not-a-game.945113.0.html · https://store.steampowered.com/app/3359730/Desktop_Mate__DLC/
- Shimeji: https://fanlore.org/wiki/Shimeji · https://dic.pixiv.net/en/a/Shimeji · https://github.com/gil/shimeji-ee
- Ropuka's Idle Island: https://stmstat.com/app/3416070 · https://www.gamestar.de/artikel/entspannte-farming-sim-auf-steam-fuer-4-euro,3427056.html · https://automaton-media.com/articles/newsjp/ropukas-idle-island-20250204-327321/
- Tiny Pasture: https://vaporlens.app/app/3167550/tiny_pasture
- Spirit City: https://store.steampowered.com/app/2113850/Spirit_City_Lofi_Sessions/ · https://aywren.com/2024/06/17/steam-gaming-spirit-city-lofi-sessions
- Wallpaper Engine: https://steamcommunity.com/app/431960/discussions/2/1752358461530583995 · https://wallpapers.com/blog/does-wallpaper-engine-affect-gaming-performance.html
- Codex Pets: https://engadget.com/2162796/openai-introduces-ai-generated-pets-for-its-codex-app · https://www.hongkiat.com/blog/codex-pets-custom-hatch-guide/ · https://letsdatascience.com/news/openai-adds-codex-pets-floating-task-overlay-bfb48d20
- Pixel Agents: https://github.com/pablodelucca/pixel-agents · https://www.mdskills.ai/skills/pixel-agents
- Clawd on Desk: https://blog.brightcoding.dev/2026/09/29/rullerzhou-afkclawd-on-desk-desktop-pet-for-ai-coding-agents · https://wingetly.io/apps/rullerzhou-afk/clawd-on-desk
- Clippy: https://www.mentalfloss.com/technology/computers/tragic-life-clippy-worlds-most-hated-virtual-assistant · https://insights.dice.com/2019/03/22/clippy-corpse-offers-valuable-lessons/?amp
- BonziBuddy: https://en.wikipedia.org/wiki/BonziBuddy

Fighting games and spectating
- Street Fighter 6: https://en.wikipedia.org/wiki/Street_Fighter_6 · https://esports.gg/news/street-fighter-v/state-of-play-showcases-street-fighter-6s-insane-new-features/ · https://www.eventhubs.com/news/2022/sep/16/sf6-training-visual-frame-data · https://words.infil.net/w03-sf6beta-p6.html · https://www.eventhubs.com/news/2023/aug/01/sf6-launches-master-league · https://www.esports.net/wiki/guides/street-fighter-ranks/
- Smash Ultimate: https://www.ssbwiki.com/Victory_pose · https://www.ssbwiki.com/credits · https://zeldauniverse.net/2018/06/14/stage-hazards-are-now-optional-in-super-smash-bros-ultimate/ · https://ssbwiki.com/Special:MobileDiff/1635988
- Tekken 8: https://esports.gg/guides/tekken-8/tekken-8-super-ghost-battle · https://www.bandainamcoent.com/news/tekken-8-patch-notes-v2-02 · https://gamingbolt.com/tekken-8-overhauls-my-replay-and-tips-allows-for-real-time-practice
- Brawlhalla: https://brawlhalla.wiki.gg/wiki/Battle_Pass · https://www.brawlhalla.com/battle-pass-faq
- Rivals of Aether: https://rivalsofaether.com/?p=84 · https://steamcommunity.com/workshop/filedetails/discussion/3514263181/524225948489413718
- Salty Bet: https://www.pcgamer.com/salty-bet-1/ · https://openresearch.lsbu.ac.uk/download/4bdbce1fb68846551a45eca7a0b031c409a8fdbd0aebd96c654e53af989dbc9e/481395/AISB19%20AI%20Spectatorship%20v2.pdf · https://www.moma.org/interactives/exhibitions/2013/designandviolence/saltys-dream-cast-casino-salty-bet/
- Nidhogg: https://spritesanddice.com/reviews/nidhogg-review-refined-rawness/ · https://www.avclub.com/nidhogg-review-pc
- Pocket Rumble: https://www.nintendolife.com/reviews/switch-eshop/pocket_rumble · https://gameranx.com/updates/id/25097/article/pocket-rumble-returns-to-kickstarter-to-make-fighting-game-masters-out-of-all-of-us/
- Mortal Kombat: https://en.wikipedia.org/wiki/Fatality_(Mortal_Kombat) · https://www.gameinformer.com/b/features/archive/2015/07/21/the-brutal-history-of-mortal-kombat-fatalities.aspx · https://www.engadget.com/2011-02-15-mortal-kombat-dev-gives-how-to-lesson-on-fatality-design.html

Engagement, meta, privacy backlash
- Duolingo: https://blog.duolingo.com/duolingo-streak-research/ · https://making.duolingo.com/how-streaks-keep-duolingo-learners-committed-to-their-language-goals · https://www.universityxp.com/news/2025/7/25/we-havent-seen-you-in-a-while-duolingos-passive-aggressive-strategy-for-keeping-users-hooked
- Tamagotchi: https://www.mentalfloss.com/fun/toys/tamagotchi-history · https://sites.cc.gatech.edu/fce/archives/future/0208.html
- Achievements: https://kotaku.com/two-ways-to-fix-achievements-on-the-xbox-one-1645752957 · https://github.blog/news-insights/product-news/introducing-achievements-recognizing-the-many-stages-of-a-developers-coding-journey/ · https://arxiv.org/html/2303.14702v3
- Halo Infinite pass: https://www.windowscentral.com/halo-infinite-fans-angry-about-battle-pass · https://www.techradar.com/news/halo-infinites-controversial-battle-pass-progression-just-got-a-whole-lot-better
- Spotify Wrapped: https://adplist.substack.com/p/spotifys-most-popular-design · https://ecommercewithdev.substack.com/p/spotify-wrapped-what-it-takes-to
- Banana: https://en.wikipedia.org/wiki/Banana_(2024_video_game) · https://www.pcgamesn.com/steam/banana-scam-statement
- Recall: https://scmagazine.com/news/microsofts-ai-recall-feature-postponed-to-address-security-concerns · https://www.techrepublic.com/article/news-microsoft-recall-expands-rollout/

Developer-tool gamification and streaming
- WakaTime: https://wakatime.com/features
- Power Mode: https://dev.to/pandiyancool/cool-vs-code-extension-set-your-code-on-fire-2oac · https://marketplace.visualstudio.com/vsgallery/936788cc-7213-4d48-93ae-045694781214
- Chat brawlers: https://gamesplusjames.itch.io/streambuddies · https://el-tutsi.itch.io/twitch-chat-avatars/devlog/468807/chat-vs-streamer-mode
- In-repo prior research: `C:\Users\User\minis\docs\COMPARISON.md` (2026-10-13)
