# Security and privacy

GBOT runs locally and has no hosted backend. Its host CLI may read existing
provider credentials and optional calendar data; the microcontroller
receives only the values required to render its views.

## Data boundaries

- Claude credentials remain in the macOS Keychain, and Codex credentials
  remain in their existing local authentication file. Tokens are used for
  HTTPS requests to their corresponding provider endpoints.
- The board receives account labels, remaining percentages, and reset
  intervals, not OAuth tokens.
- With Calendar enabled, a shortened meeting title and time appear on the
  device. Anyone who can see the screen can read them.
- The USB text protocol is a local control interface without authentication.
  A process able to open that serial port can control the display and inspect
  its stored dashboard values.
- Board `state.txt` and `limits.txt` retain availability, rotation, and usage
  percentages. Host configuration and retry coordination live under
  `~/.config/gbot/`. Optional service logs live under `~/Library/Logs/gbot/`.

See [integrations](docs/integrations.md) for exact optional endpoints and
installation locations. Provider usage endpoints are undocumented and may
change. Do not include auth files, Keychain output, real meeting titles, or
unredacted provider responses in public issues or pull requests.

## Reporting a vulnerability

For a flaw involving credentials, unintended data disclosure, or unsafe
remote code execution, use GitHub's **Report a vulnerability** option in this
repository's Security tab if available. If private reporting is unavailable,
open an issue asking the maintainer for a private reporting channel without
including the vulnerability details or sensitive data.

Include the affected commit, environment, impact, and a minimal sanitized
reproduction through the private channel. Never send a real access token as
proof. Revoke or rotate credentials with the relevant provider if you have
accidentally exposed them.
