# Command reference

Run `gbot --help` for the CLI's current syntax. Commands below assume the
correct device has been discovered. Add `--device /path/to/port` to select a
specific board. `gbot` without arguments shows status.

## Availability and physical controls

| Command | Color | Meaning |
| --- | --- | --- |
| `gbot busy` | Red | Do not interrupt |
| `gbot hold` | Yellow | Temporarily busy; back soon |
| `gbot await` | Blue | Available, but focused |
| `gbot open` | Green | Come say hello |
| `gbot next` | Next color | Cycle `open → await → hold → busy` |

Setting a state returns to the animated face. Each state has a family of eye
expressions. A short BOOT press follows the same state cycle; a long press
(about 0.6 seconds) changes full-screen view. RESET is a hardware restart.
A tap can change state, and sustained shaking triggers an angry expression
for up to 45 seconds.

```sh
gbot press short            # Exercise the short-press path through USB
gbot press long             # Exercise the long-press path through USB
```

Software-triggered presses check application behavior. They do not test the
physical button or sensor.

## Views and display settings

| Command | Purpose |
| --- | --- |
| `gbot face` | Return to the animated face immediately |
| `gbot view face` | Same face selection |
| `gbot view hud` | Show board telemetry |
| `gbot view limits` | Show usage already stored on the board |
| `gbot view weather` | Show weather already stored on the board |
| `gbot view trm` | Show stored USD/COP reference data |
| `gbot view calendar` | Show the stored next meeting |
| `gbot rotate 0` | Set orientation, in 90-degree steps from `0` to `3` |
| `gbot bright 70` | Set brightness, `0` to `100` |
| `gbot sleep` / `gbot wake` | Turn the display off/on |
| `gbot status` | Read availability, view, rotation, and available telemetry |
| `gbot ping` | Check the command link |
| `gbot devices` | List candidate serial ports |

The face alternates roughly 45 seconds of eyes with 8-second cards when data
is available. Manually opened usage, weather, and TRM views return to the
previous face/state after 60 seconds of visible time. Calendar displays for
up to two minutes. `gbot face` returns immediately.

Brightness and sleep are runtime controls. Availability and rotation are
stored across power cycles; boot always opens the face. Chip temperature in
the HUD is a microcontroller reading, not room temperature. Voltage is an
ADC estimate, not a calibrated battery percentage.

## Usage data

```sh
gbot limits                 # Read the stored pages; no provider request
gbot limits --demo          # Write example values and open the dashboard
gbot limits --clear         # Delete usage pages, including the saved copy
gbot limits page next       # Advance the selected account
gbot limits page 0          # Select the first account (zero-based)

gbot claude                 # Fetch usage and show Claude's page
gbot codex                  # Fetch usage and show Codex's page
gbot limits --live          # Fetch both configured providers
gbot codex --watch 60        # Refresh repeatedly; Ctrl-C stops it
```

Percentages mean **remaining**, not consumed. The host converts provider
values before sending them to the board. Reset timers are remaining seconds.
A read of `gbot limits` reports cached board values; it is not proof of a
successful provider refresh.

You can supply any small account dashboard manually:

```sh
gbot limits MYAPP 5H,84,1830 7D,89,432000
gbot view limits
```

Here `MYAPP` names the page, `5H`/`7D` are labels, `84`/`89` are remaining
percentages, and the third number is seconds until reset. Omit that number
when no reset time is available:

```sh
gbot limits BATTERY NOW,76
```

Use short ASCII account and window labels: the screen is small, account
titles are limited to eight characters, and the serial parser accepts lines
of at most 96 characters. Manual data is supplied by you; GBOT does not infer
what an account's numbers mean. Provider behavior and credential locations
are explained in [integrations](integrations.md).

## Data refresh versus view selection

`gbot weather`, `gbot trm`, `gbot claude`, and `gbot codex` fetch new data and
open their dashboards. `gbot view ...` selects a view using data already on
the board. `gbot feed` updates enabled data sources without selecting a new
availability state or manually opening their views.

```sh
gbot weather status         # Read cached board weather
gbot trm status             # Read cached board TRM
gbot calendar status        # Read the scheduled board reminder
gbot feed                   # One refresh pass
gbot feed --watch 60         # Continue until interrupted
```

An enabled calendar reminder can still interrupt the face at its scheduled
time. Online data stops refreshing when the host is offline, asleep, or
disconnected. Saved usage percentages can survive a reboot, but countdowns
are discarded because the board cannot know how long power was absent.
