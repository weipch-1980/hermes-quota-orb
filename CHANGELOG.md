# Changelog

## 0.3.1

- Changed only supply-chain release automation: pushed tags now run CI-native tests, build the release ZIP and SHA-256 sidecar, verify integrity, attest the CI-built ZIP, and create the Release with those same assets.
- Preserved the `0.3.0` Release history unchanged; it is not retroactively attested.

## 0.3.0

- Added the third-generation emerald crystal quota orb with double-layer thick glass, dual-track refraction, and provider-derived liquid levels.
- Documented the three-state Auto / 中文 / English language selector and profile-scoped language and daily-report storage semantics.
- Added fail-fast installer conflict detection, safe dry runs, and explicit `--force` overwrites.
- Rejected symlink, junction/reparse-point, resolved-path escapes, and commit-time destination-parent swaps during installation, including under `--force`.
- Hardened installation and release packaging against no-follow source-file races, including same-size, preserved-mtime content mutation.
- Added a reproducible standard-library-only Skill ZIP builder with a SHA-256 sidecar.
- Versioned the Skill and Hermes backend manifests together at 0.3.0.

## 0.2.0

- Added the borderless crystal orb, provider/model daily usage grouping, and read-only account quota panel.
