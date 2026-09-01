#!/usr/bin/env bash
set -euo pipefail

umask 002

exec "$@"
