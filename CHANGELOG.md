# Changelog

## [0.12.2](https://github.com/NamrataAShettar/claude-sethu/compare/v0.12.1...v0.12.2) (2026-10-06)


### Bug Fixes

* add directory listing fields, square icon, and manifest consistency tests ([#28](https://github.com/NamrataAShettar/claude-sethu/issues/28)) ([ec2aed2](https://github.com/NamrataAShettar/claude-sethu/commit/ec2aed298b3fc08564ef9f8fbc7a4e38fa702078))

## [0.12.1](https://github.com/NamrataAShettar/claude-sethu/compare/v0.12.0...v0.12.1) (2026-07-09)


### Bug Fixes

* message consistency + humane-tone guideline + PR test-plan template ([#23](https://github.com/NamrataAShettar/claude-sethu/issues/23)) ([9c611ab](https://github.com/NamrataAShettar/claude-sethu/commit/9c611ab9a6977b2ea6dc690f4b513ad68f37938d))

## [0.12.0](https://github.com/NamrataAShettar/claude-sethu/compare/v0.11.7...v0.12.0) (2026-07-09)


### ⚠ BREAKING CHANGES

* the `launch` config key and `sethu --unlaunch` are removed; `--launch` no longer registers a persistent entry.

### Features

* make --launch one-shot; remove the launch list and --unlaunch ([#19](https://github.com/NamrataAShettar/claude-sethu/issues/19)) ([5acd719](https://github.com/NamrataAShettar/claude-sethu/commit/5acd719a2ce9791dacc72ccc56e01af65418376f))

## [0.11.7](https://github.com/NamrataAShettar/claude-sethu/compare/v0.11.6...v0.11.7) (2026-07-09)


### Bug Fixes

* guard the prefix (reject reserved chars !//@ and multi-char) ([#20](https://github.com/NamrataAShettar/claude-sethu/issues/20)) ([bc4e850](https://github.com/NamrataAShettar/claude-sethu/commit/bc4e850fa8c89f06016bc40b75cbdc0bc391450d))
