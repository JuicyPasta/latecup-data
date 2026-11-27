#!/bin/sh
# Run the released app's own votes parser on a votes file that carries `prop`.
#
# usage: tools/released_app_check/votes.sh [a votes file] [app repository] [tag]
#
# `prop` (FORMAT.md, the votes file) is new in the feed, and Latecup 1.0.0
# reads New York's votes file. This asks the app's own code at the tag
# (default: ../Latecup at v1.0.0), exported into a temporary folder like
# run.sh does, whether it reads a votes file with `prop` exactly as it reads
# the same file without it. Without a votes file, one is made by the hourly
# count from made-up rows (votes_cases.py). Packages come from the pub cache
# (--offline, --no-pub): no network. PYTHON names the interpreter (default:
# .venv/bin/python).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
FILE="${1:-}"
APP="${2:-$ROOT/../Latecup}"
TAG="${3:-v1.0.0}"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
TMP="$(mktemp -d)"
git -C "$APP" archive "$TAG" lib/app_identity.dart lib/feed lib/hours lib/services/file_store.dart assets/data | tar -x -C "$TMP"
cp "$HERE/pubspec.yaml" "$TMP/pubspec.yaml"
mkdir -p "$TMP/test" "$TMP/votes"
cp "$HERE/votes_test.dart" "$TMP/test/votes_test.dart"
if [ -n "$FILE" ]; then "$PY" "$HERE/votes_cases.py" "$TMP/votes" "$FILE"; else "$PY" "$HERE/votes_cases.py" "$TMP/votes"; fi
cd "$TMP"
flutter pub get --offline > /dev/null
VOTES="$TMP/votes" flutter test --no-pub test/votes_test.dart
echo "the app's code at $TAG, in $TMP"
