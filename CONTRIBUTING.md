# Contributing to GBOT

Contributions are welcome: fixes, documentation, new host integrations,
accessibility improvements, and ports to additional boards.

## Before making a change

Read the [architecture](docs/architecture.md) and
[development guide](docs/development.md). For hardware changes, read the
[porting guide](docs/porting.md) and link the target's official documentation.
Keep a change focused enough that a reviewer can understand its effect.

GBOT intentionally keeps credentials and network access on the host.
Preserve that boundary, the four availability meanings, and existing serial
commands unless a change explicitly documents a migration.

## Bug reports

Include the board model and revision, host OS, Python and MicroPython
versions, GBOT commit, the command or physical action, expected result, and
actual result. For display issues, include a photo or video and the active
rotation. Provide the smallest useful sanitized error log.

Remove tokens, private meeting titles, email addresses, account IDs, and
personal filesystem details before posting. See [SECURITY.md](SECURITY.md)
for security-sensitive reports.

## Pull requests

1. Create a branch in your fork.
2. Make the focused change and update relevant English documentation.
3. Run the host checks described in [development](docs/development.md).
4. For firmware or visual changes, record actual device validation when
   hardware is available. Otherwise clearly mark it as unverified.
5. Explain the problem, resulting behavior, validation performed, and any
   known limitation in the pull request.

A new board contribution should include its exact model, official sources,
pin map, runtime/compiler versions, installation commands, unsupported
features, and evidence from the physical board. Do not add a board to the
supported list based only on successful host tests.

Claude Code and Codex contributions are welcome. Review generated changes,
verify pins against primary sources, and take responsibility for the
resulting code. Keep prompts free of personal credentials.

## Licensing

Contributions must be compatible with [LICENSE](LICENSE). Keep existing
copyright and license notices, and add attribution for new third-party code
or assets to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Do not copy a
vendor example or font without checking its redistribution terms.
