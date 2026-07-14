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
Shanghai locations and injected fake clients; they make no cloud requests.

The first fork version always uses standard city weather, quantizes provider
coordinates to a `0.05°` grid, verifies that the quantized point remains in the
selected country/province/city warning jurisdiction, disables grid and minute
weather calls, and does not auto-register the upstream dashboard card or custom
more-info UI.

## Rebuilding the branch

```bash
git fetch upstream --tags
git switch --detach 9232254cf7dd56c72aefb23b425a4dd29bab1f4e
git switch -c maint/v1.1.6-yx
```

Run `uv sync --group test`, `uv run pytest`, and the compile/lint checks from
`.github/workflows/tests.yml` before pushing a change.
