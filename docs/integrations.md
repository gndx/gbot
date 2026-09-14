# Integrations

GBOT's core states and animation work without accounts or network access.
All integrations below run on the **host computer** and send compact display
data over USB. The reference board does not connect to the Internet.

## Claude Code and Codex usage

```sh
gbot claude
gbot codex
gbot limits --live
```

These adapters reuse an existing local CLI sign-in. They read usage through
undocumented endpoints used by the providers' own clients, which may change
without notice. They are optional community integrations, not stable public
APIs or provider-endorsed features.

| Adapter | Local credential source | Request destination |
| --- | --- | --- |
| Claude Code | macOS Keychain item `Claude Code-credentials` | `https://api.anthropic.com/api/oauth/usage` |
| Codex | `~/.codex/auth.json`, `tokens.access_token` and `tokens.account_id` | `https://chatgpt.com/backend-api/wham/usage` |

The Claude reader currently requires macOS's `security` command. A Codex
installation that stores credentials only in another location or a keychain
does not match this adapter. GBOT does not perform sign-in or refresh tokens;
use the provider's own CLI when credentials have expired. An API key is not
a replacement for the expected subscription OAuth credentials.

Tokens are sent to their provider over HTTPS; the firmware receives only
account labels, percentages, and reset intervals. GBOT does not intentionally
print tokens or save a duplicate credential file. Do not paste credential
files or Keychain output into issues, logs, or AI prompts.

Claude HTTP 429 responses establish a shared local retry pause. The adapter
honors a valid `Retry-After` value or increases the pause from ten minutes up
to one hour. A direct provider command can display stored data during a
deferred retry and labels it as cached. Repeated commands do not bypass the
pause. `gbot limits --demo` and manual values remain available without either
provider.

## Weather

```sh
gbot weather                # Fetch and display
gbot weather status         # Read stored data without a network request
gbot weather terminal       # Terminal-only lookup; no board required
```

The default location is **Medellín, Colombia** (latitude `6.2442`, longitude
`-75.5812`). The host requests temperature, relative humidity, and WMO weather
code from [Open-Meteo](https://open-meteo.com/en/docs), in Celsius. The location
is fixed in the current source. To change it, update `WEATHER_URL` and city
labels in `cli/gbot` and the firmware together; there is no location-setting
command yet.

The `clima` command remains available as a legacy alias.

The feed refreshes weather every ten minutes. Review
[Open-Meteo's terms and attribution requirements](https://open-meteo.com/en/terms)
for your use, particularly before redistributing a hosted or commercial
integration.

## Colombia USD/COP reference rate

```sh
gbot trm
gbot trm terminal           # Terminal only
gbot trm status             # Stored board value
```

The host reads Colombia's TRM dataset from
[Datos Abiertos Colombia](https://www.datos.gov.co/resource/ceyp-9c7c.json).
It sends the rate as integer cents, validity dates, and a remaining validity
interval. The feed refreshes it hourly or when that interval expires.
This is a dated reference value; it is not a live exchange quote or a trading
integration. Date handling for this dataset uses Colombia's UTC−5 offset.

## Apple Calendar: macOS 14+

This optional helper reads calendars already synchronized in the macOS
Calendar app. A Google or Microsoft calendar must first be available there;
GBOT has no direct Google or Microsoft calendar login.

```sh
# Install Apple Command Line Tools first if xcrun/swiftc are unavailable.
gbot calendar connect
gbot calendar calendars
gbot calendar terminal
gbot calendar
gbot feed --watch 60
```

`calendar connect` builds a small local app named **GBOT Calendar**, launches
its authorization flow, and saves the enabled setting. macOS requests
calendar access for this app identity. The EventKit API requests full event
access, while the helper's implemented behavior only reads events; it does
not create, modify, or delete them.

The helper selects the next timed event within seven days, excluding
all-day, canceled, free, declined, and already-started events. By default it
uses all available calendars. To restrict selection, list calendar IDs with
`gbot calendar calendars`, then edit `~/.config/gbot/calendar.json`:

```json
{
  "enabled": true,
  "source": "apple",
  "calendars": ["replace-with-an-id-from-the-calendars-command"]
}
```

The host sends the meeting's shortened title, display time, a derived event
ID, and seconds until it starts. Meeting titles therefore become visible to
people who can see the device. Choose calendars accordingly.

The board opens the reminder five minutes before the meeting, for up to two
minutes. A button action or `gbot face` dismisses it. The firmware remembers
recently shown event IDs during that run to avoid repeated reminders; this
deduplication memory resets on reboot. Keep `gbot feed --watch 60` or the
background feed running to receive new or changed meetings. Authorization
alone does not run a feed.

To disable Calendar integration, set `"enabled": false` in the configuration.
A reminder already sent to the board can remain scheduled until it expires
or the board restarts. Close its visible view with `gbot face`.

## Background feed on macOS

The foreground feed is the easiest way to try synchronization:

```sh
gbot feed --device /dev/cu.usbmodemXXXX --watch 60
```

It attempts both usage adapters, weather, TRM, and Calendar if enabled. An
unavailable integration is reported independently, allowing other sources
to refresh. The current feed has no per-provider enable switches. Use
individual commands if you only want one provider or data source.

For a per-user `launchd` service:

```sh
./scripts/install-feed.sh /dev/cu.usbmodemXXXX
```

Installation starts the service immediately. It runs the feed with a
60-second polling interval, with weather and TRM throttled separately. It restarts after
failure and retries when USB reconnects. The Mac must remain awake for new
data to arrive. Reinstall the service if the checkout moves or the selected
serial path changes.

| Item | Location |
| --- | --- |
| CLI device cache and coordination files | `~/.config/gbot/` |
| Calendar configuration | `~/.config/gbot/calendar.json` |
| Calendar app | `~/Applications/GBOT Calendar.app` |
| Feed service | `~/Library/LaunchAgents/com.gndx.gbot.feed.plist` |
| Feed logs | `~/Library/Logs/gbot/` |

Stop the service before flashing, deploying, or opening a REPL:

```sh
launchctl bootout "gui/$(id -u)/com.gndx.gbot.feed"
```

Run the installer again to restart it. To uninstall the service after
stopping it, delete the plist above. Delete `GBOT Calendar.app` if you no
longer need the helper. Removing GBOT's configuration or logs does not sign
you out of Claude or Codex; their credentials stay in their original stores.

Linux users can run the foreground feed or wrap it in a service appropriate
to their system. No Linux service installer ships with this release.
