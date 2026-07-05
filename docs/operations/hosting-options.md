# Hosting Options

The bot currently runs on a laptop that must stay powered on 24/5, alongside IB
Gateway. This page explores cheaper, lower-power, always-on hosts so the laptop
is free for other use — evaluated for a trader in **Alberta, Canada**, with an
eye on a possible move to an **offshore broker** for nano/micro lots and a
smaller starting balance.

*Research current as of July 2026. Prices are approximate CAD and drift — treat
them as ballpark, not quotes.*

## TL;DR

- **Cheapest capable host:** a **refurbished i5-8500T mini PC** (Lenovo
  ThinkCentre Tiny / HP EliteDesk Mini / Dell OptiPlex Micro), 16 GB, **~$200–250
  CAD**. x86, trivial IB Gateway install, ~10–12 W idle. This is the recommended
  buy.
- **Lowest cost / lowest power:** a **Dell Wyse 5070 thin client** (8 GB+),
  **~$100 CAD**, ~3–5 W idle. x86, runs full Linux + IB Gateway; just add RAM/SSD.
- **Raspberry Pi 5:** now *technically* works with IB, but ends up **more
  expensive (~$290 all-in) than either x86 option, with less CPU and a more
  fragile setup**. Only worth it if a future broker uses a cross-platform API
  (cTrader / Dukascopy JForex) *and* you specifically want the Pi.
- **The decision that drives everything:** your **broker's API** determines
  whether a Pi is even an option. See below.

## The key insight: broker API decides the hardware

The host has to keep the broker's connectivity software running headless 24/5.
That software differs wildly by broker, and **one common path (MetaTrader 5)
effectively rules out a Raspberry Pi**:

| Broker API | Cross-platform? | Runs on ARM / Raspberry Pi? | Hosting implication |
|---|---|---|---|
| **IBKR TWS API** (`ib_async`) — *current* | Yes (Java Gateway + Python) | Yes (official ARM installer since Gateway ~10.37, late 2025) | Any Linux host; x86 easiest |
| **cTrader Open API** (Python SDK) | Yes, natively | **Yes** — native Linux/ARM | Pi stays viable |
| **Dukascopy JForex** (Java `IStrategy`) | Yes (JVM) | **Yes** — Java runs on Pi | Pi stays viable |
| **MetaTrader 5 / MT4** (`MetaTrader5` PyPI) | **No — Windows-only** | **No** (Wine on ARM not viable) | Forces x86 Windows or x86 Linux+Wine |
| **FIX API** | Yes (raw protocol) | Yes | Pi viable, but more work than cTrader |

!!! warning "MT5 is Windows-only, and that hasn't changed"
    The official `MetaTrader5` Python package still ships **only** for Windows in
    2026 (it depends on Windows DLL/IPC internals). On Linux you run
    Windows-Python + the MT5 terminal under **Wine**, bridged to native Python
    (`mt5linux` / `pymt5linux`). Wine on **ARM is not a realistic path**, so an
    **MT5-only broker kills the Raspberry Pi option** and pushes you to an x86
    box (Windows, or Linux+Wine).

**So:** if you stay on IBKR, or move to an offshore broker that offers **cTrader
Open API** or **Dukascopy JForex**, a Pi is on the table. If you move to a
**MetaTrader-only** offshore broker, buy x86.

---

## Hardware options (Canada, CAD)

### 1. Refurbished business mini PCs (x86) — best value ✅

Ex-corporate micro desktops. Best price/performance by a wide margin, and IB
Gateway installs with zero fuss.

| Model | Refurb config | ~CAD | Idle power |
|---|---|---|---|
| Lenovo ThinkCentre M710q / M910q Tiny (i5-7500T) | 8 GB / 256 GB | $180–250 | ~8–15 W |
| Dell OptiPlex 7060 Micro (i5-8500T) | 8–16 GB / 256 GB | $220–320 | ~8–15 W |
| HP EliteDesk 800 G4 Mini (i5-8500T) | 16 GB / 256 GB | $220–300 | ~8–15 W |

- All x86-64, 6-core i5, standard SO-DIMM RAM + M.2 NVMe (easily upgraded).
- Prefer the **"T" suffix** CPUs (35 W TDP low-power); avoid 65 W SFF/non-T variants.
- Sources: [ThinkCentre M710q (Staples.ca)](https://www.staples.ca/products/3042616-en-lenovo-thinkcentre-m710q-tiny-refurbished-desktop-computer-intel-core-i5-7500t-256-gb-ssd-8-gb-ram-windows-10-pro), [OptiPlex 7060 (amtonline.ca)](https://amtonline.ca/products/dell-optiplex-7060), [EliteDesk 800 G4 (Amazon.ca)](https://www.amazon.ca/HP-EliteDesk-Hexa-Core-Bluetooth-DisplayPort/dp/B0CHWPQNGF).

### 2. Dell Wyse 5070 thin client (x86) — cheapest / lowest power ✅

| Config | ~CAD | Power | Notes |
|---|---|---|---|
| Pentium J5005, 8–16 GB, M.2 SATA SSD | $80–150 (Canadian eBay) | **~3 W idle**, ~14 W load | Runs full Ubuntu/Debian + IB Gateway |

- x86-64, absurdly low power. **Watch the RAM:** 4 GB stock is too tight for
  Gateway (Java) + bot + Xvfb — get **8 GB minimum, ideally 16 GB** (community-verified
  to 16 GB with a BIOS update). Uses an **M.2 SATA** slot (not NVMe).
- Buy from Canadian eBay sellers to avoid US import fees.
- Sources: [Wyse 5070 review (Gough's Tech Zone)](https://goughlui.com/2024/10/01/review-dell-wyse-5070-thin-client-j5005-8gb-ram-64gb-m-2-sata-ssd/), [hardware spec (ParkyTowers)](https://www.parkytowers.me.uk/thin/wyse/5070/).

### 3. New Intel N100 / N150 mini PCs (x86)

Best if you want *new* with warranty and (optionally) fanless silence.

| Model | Config | ~CAD | Idle power |
|---|---|---|---|
| Fanless N150 (MeLE Cyber X1, etc.) | 16 GB / 500 GB | $250–350 | ~6–13 W |
| Beelink Mini S12 Pro (N100) | 16 GB / 500 GB | $230–260 | ~6–11 W (quiet fan) |
| TRIGKEY G4 (N100) | 16 GB / 500 GB | $220–250 | ~7–11 W |

- N150 is a slightly faster "binned" N100 at the same price — prefer it when
  buying new. N305 (8-core) is overkill for one bot.
- Slower than a refurb i5, but plenty for an event-driven bot + Gateway.
- Sources: [Beelink S12 Pro (Amazon.ca)](https://www.amazon.ca/Beelink-Intel-3-4GHz-Computer-Support/dp/B0CRK8S4V8), [N100/N150 power guide](https://bishalkshah.com.np/blog/low-power-homelab-n100-mini-pc), [MeLE Cyber X1 fanless N150](https://www.cnx-software.com/2025/09/17/mele-cyber-x1-fanless-intel-n150-mini-pc-plastic-heatsink/).

### 4. Raspberry Pi 5 / ARM (⚠️ only if broker API is cross-platform)

| Item | ~CAD |
|---|---|
| Pi 5 8 GB board (PiShop.ca) | $244.95 |
| + official 27 W PSU, case, SD card | ~$45 |
| **All-in** | **~$290** (more with M.2 HAT + NVMe) |

- ~3–7 W idle. **ARM64** — this is the catch.
- IB Gateway **now has an official ARM (aarch64) installer**, and the
  `gnzsnz/ib-gateway-docker` image supports Pi 5 / Apple Silicon natively. It
  *works*, but it's less battle-tested and more fiddly than x86 (see the caveats
  below).
- **Ends up more expensive than a refurb i5 or a thin client, with less CPU and
  a more fragile Gateway setup.** For this job, x86 wins on every axis except
  GPIO/ecosystem.
- Sources: [PiShop.ca Pi 5 8 GB](https://www.pishop.ca/product/raspberry-pi-5-8gb/), [nemozny/ibgateway-raspberry-64](https://github.com/nemozny/ibgateway-raspberry-64), [gnzsnz/ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker).

### IB Gateway on a Raspberry Pi — the detail

If you go Pi anyway, here's the current (2025–2026) reality:

- **Not officially supported** on Raspberry Pi — but IB now ships an official
  `linux-arm` installer that bundles a JRE, which removed the historic #1 pain
  point (hand-assembling Java). Treat it as *tolerated, not blessed* — IB
  support won't help if it breaks.
- **Cleanest path:** the `gnzsnz/ib-gateway-docker` aarch64 image (bundles
  Gateway + IBC + Xvfb). Native path: BellSoft **Liberica Full** JDK 17 ARM64 (the
  *Full* variant ships the JavaFX/AWT modules the GUI needs) or the bundled Azul
  Zulu JRE.
- **It's a GUI app** — must run under **Xvfb** (X11 virtual framebuffer, not
  Wayland) with **IBC** for automated login. Same headless plumbing as x86.
- **A Pi 5 8 GB copes fine:** Gateway wants ~1–1.5 GB (Java heap default 768 MB,
  bump to ~1024 MB); your Python bot is <500 MB. CPU is a non-issue.
- **Known fragility:** Gateway 10.45's JavaFX crashes if pointed at system
  OpenJDK (leave `JAVA_PATH` empty to auto-discover the bundled JRE); IBC's
  `ibcstart.sh` may need hand-patching to re-add `-DinstallDir`/`-DvmOptionsPath`;
  **pin the offline Gateway version** to stop auto-updates breaking things;
  **boot from USB/NVMe SSD, not SD card** (I/O reliability); use the official PSU
  + active cooling.
- **Your Python stack is 100% portable** (`ib_async`, `httpx`, `aiosqlite`,
  APScheduler, loguru, Pydantic all have ARM64 wheels). A robust pattern is even
  to **split**: run Gateway on an x86 box and just the bot on the Pi over the LAN.

**Verdict:** viable and community-proven, but for a bot placing live orders
during volatile news releases, x86 carries less tail risk. Paper trading (no 2FA)
materially de-risks the Pi option if you want to experiment.

---

## Broker options for nano/micro lots (offshore)

If the goal is a smaller starting balance with nano/micro sizing, offshore
brokers offer it — but with three big strings attached (below). The **API column
decides whether a Pi survives the move.**

| Broker | Accepts Canadians? | Min deposit / smallest size | USDZAR / USDTRY | API | Pi-friendly? |
|---|---|---|---|---|---|
| **IC Markets** | Offshore (Seychelles) — not CIRO | $200; 0.01 lot (1,000 units) | **Both** | **cTrader Open API** + FIX | ✅ Yes |
| **FP Markets** | Offshore (SVG); has en-ca site — not CIRO | ~$100; 0.01 lot | Both (verify TRY) | **cTrader Open API** + FIX | ✅ Yes |
| **Dukascopy** | Verify Canada KYC | $100 JForex / $1,000 for MT bridge; ~1,000 units | **Both** | **JForex (Java)** | ✅ Yes |
| **Pepperstone** | **Uncertain — verify** | ~$0–200; 0.01 lot | USDTRY yes; ZAR likely | cTrader + FIX | ✅ Yes (if it accepts you) |
| Eightcap | Offshore (Bahamas) | $100; micro | 40+ exotics | **MT4/5 only** | ❌ No (x86/Wine) |
| Vantage | Offshore | $50–200; micro | Exotics | MT4/5 (cTrader unconfirmed) | ❌ Mostly no |
| XM | **No Canada** | $5 cent; micro | Broad | **MT4/5 only** | ❌ No |
| Exness | **No Canada** | $10 cent; nano | Likely | cTrader + MT4/5 | ❌ Blocked |
| RoboForex | **Canada restricted** | $10 cent; nano | — | Cent = MT4/5 only | ❌ No |
| Tickmill | **No Canada** | $100; micro | USDTRY / EURZAR | **No cTrader** | ❌ No |
| **Interactive Brokers** *(current, regulated)* | **Yes — CIRO, available in Alberta** | Low; from 1,000 units, but **$2.50 min commission** | **Both** on IDEALPRO | **TWS API** | ✅ Yes |

### Three caveats that matter for *your* situation

!!! danger "1. Alberta is often blocked even offshore"
    Alberta's securities regulator is one of the most aggressive in Canada
    against unregistered forex dealers. Several offshore brokers refuse **AB**
    residents even when they "accept Canadians" generally. **Confirm province =
    Alberta acceptance at the KYC/signup step before funding** — a broker
    directory listing is not a guarantee.

!!! danger "2. Your strategy is news-event straddles — many offshore market-makers ban it"
    B-book market-maker brokers frequently requote, apply artificial slippage, or
    close accounts for "news scalping." You need **true ECN/STP execution**: the
    cTrader ECN accounts (IC Markets Raw, FP Markets Raw), Dukascopy (ECN), and
    IBKR are agency-model and appropriate. Generic MT4/5 cent-account
    market-makers are risky for event trading regardless of the API/Alberta
    issues.

!!! warning "3. Offshore = no CIPF protection"
    Entities in Seychelles, SVG, Vanuatu, Mauritius, Bahamas, etc. carry no
    Canadian investor protection, weak dispute recourse, an inherent B-book
    conflict of interest, and documented withdrawal friction for Canadians. Fund
    only what you can treat as experimental. IBKR (CIRO, CIPF, confirmed in
    Alberta) remains the safer venue for anything you care about protecting.

### Broker shortlist

**Pi-viable offshore path (cross-platform API):**

1. **IC Markets** (cTrader Open API) — best fit on paper: **both** exotics, true
   ECN, $200 min, 0.01-lot micro, mature native-Linux/ARM Python API. Verify
   Alberta.
2. **FP Markets** (cTrader Open API) — same path, $100 min, Canada-facing
   onboarding. Verify USDTRY and Alberta.
3. **Dukascopy** (JForex/Java) — you already trust them for historical data;
   Java API is inherently Pi-friendly; genuine ECN. But ~$1,000 for the MT
   bridge, no cent account, Swiss-bank KYC.
4. **Pepperstone** (cTrader) — technically ideal, but Canadian acceptance is the
   least certain; pursue only if support confirms AB in writing.

**Forces x86/Windows (rules out the Pi):** Eightcap, Vantage, XM, Exness,
RoboForex, Tickmill — all MT4/MT5-only for automation, or block Canada.

---

## Recommendation

For the **current IBKR setup**, the migration is nearly a copy-paste — install
the conda env, copy `.env` + `~/ibc/`, replicate the [cron jobs](auto-start.md),
point at the same Turso DB. Buy:

1. **A refurbished i5-8500T ThinkCentre/EliteDesk/OptiPlex Mini, 16 GB (~$200–250
   CAD).** Best value, x86, ~$10–15/yr in electricity, zero-friction Gateway.
2. Or a **Dell Wyse 5070 (8 GB+) at ~$100 CAD** if minimizing cost/watts matters
   most.

Buy x86 regardless of whether you stay on IBKR or move to an MT-only offshore
broker — it's the one choice that keeps *every* broker path open. **Only buy a
Raspberry Pi if you've committed to a cTrader/JForex broker and want the Pi
specifically** — otherwise it's more money for less capability.

If you do move offshore for nano lots, the cleanest Pi-compatible path is **IC
Markets or FP Markets via the cTrader Open API** — contingent on Alberta
acceptance, which you must confirm at signup.

*Note: RAM/SSD prices are trending up through 2026 — buying hardware sooner is
marginally cheaper.*
