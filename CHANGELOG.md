# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- Eager-import `discovery_socket_thread` and the stdlib `socket` module in `discovery` so Home Assistant no longer reports blocking-call warnings during `async_discover_host` setup (#136).
