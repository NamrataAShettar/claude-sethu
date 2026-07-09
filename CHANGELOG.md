# Changelog

## [0.12.0](https://github.com/NamrataAShettar/claude-sethu/compare/v0.11.7...v0.12.0) (2026-07-09)


### ⚠ BREAKING CHANGES

* the `launch` config key and `sethu --unlaunch` are removed; `--launch` no longer registers a persistent entry.

### Features

* make --launch one-shot; remove the launch list and --unlaunch ([#19](https://github.com/NamrataAShettar/claude-sethu/issues/19)) ([5acd719](https://github.com/NamrataAShettar/claude-sethu/commit/5acd719a2ce9791dacc72ccc56e01af65418376f))

## [0.11.7](https://github.com/NamrataAShettar/claude-sethu/compare/v0.11.6...v0.11.7) (2026-07-09)


### Bug Fixes

* guard the prefix (reject reserved chars !//@ and multi-char) ([#20](https://github.com/NamrataAShettar/claude-sethu/issues/20)) ([bc4e850](https://github.com/NamrataAShettar/claude-sethu/commit/bc4e850fa8c89f06016bc40b75cbdc0bc391450d))
