# Personal fork maintenance

This repository is the personal maintenance fork of
[`hzonz/ha_qweather_pro`](https://github.com/hzonz/ha_qweather_pro). It preserves
the `qweather_pro` domain, config-entry identity, device identifiers, and entity
unique-ID rules so an installed entry does not need to be recreated.

## Audited baseline

- Upstream remote: `git@github.com:hzonz/ha_qweather_pro.git`
- Upstream tag: `v1.1.6`
- Upstream commit: `9232254cf7dd56c72aefb23b425a4dd29bab1f4e`
- Maintenance branch: `maint/v1.1.6-yx`
- Fork remote: `git@github.com:XuanYang-cn/ha_qweather_pro.git`

Fork versions use `1.1.6-yx.N` and tags use `v1.1.6-yx.N`. Each behavioral
change stays in a focused, tested commit that can be reviewed or cherry-picked
onto a later upstream baseline. The maintenance branch is the development line;
only tagged GitHub releases are installation candidates for HACS.

## Private configuration boundary

Use the account-specific QWeather API Host and JWT/Ed25519 authentication. The
private key belongs only in Home Assistant config-entry storage. Never commit it,
put it in fixtures or release archives, or print it in logs. Tests use synthetic
synthetic locations and injected fake clients; they make no cloud requests.

The first fork version always uses standard city weather, quantizes provider
coordinates to a `0.05°` grid, and verifies before weather requests that the
quantized point resolves to the configured weather location (including for
older config entries). The separately configurable warning jurisdiction
validates its selected district through its own flow. The fork disables grid
and minute weather calls and does not auto-register the upstream dashboard card
or custom more-info UI.

## Rebuilding and releasing the branch

```bash
git fetch upstream --tags
git switch --detach <reviewed-upstream-tag>
git switch -c maint/<X.Y.Z>-yx
```

For each new upstream tag, compare every local maintenance commit with that tag
and retain only patches not accepted upstream or not made obsolete by the new
release. Cherry-pick those focused commits onto the new maintenance branch,
then run `uv sync --group test`, `uv run pytest`, and the compile/lint checks
from `.github/workflows/tests.yml`.

Before a fork release, increment the manifest to `X.Y.Z-yx.N`, run the full
offline suite, push the maintenance branch, create and push the matching
annotated tag, and publish a GitHub release from that exact tag. The release
notes must name the fork URL, upstream baseline, maintenance branch, and each
included local commit, while excluding credentials and household coordinates.

HACS installs only the fork custom repository for the `qweather_pro` domain.
To roll back, select and reinstall the preceding fork release in HACS, restart
Home Assistant, and verify that the unchanged config entry, device, and entity
identities are still attached. Keep the preceding tagged release available.
