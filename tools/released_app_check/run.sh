#!/bin/sh
# Run the released app's own feed code on a built site.
#
# usage: tools/released_app_check/run.sh <site folder> [app repository] [tag]
#
# Latecup 1.0.0 parses every entry of the manifest's `cities` and refuses the
# whole manifest over one it cannot read. validate.released_app is that parser
# written again in Python; this is the parser itself. The app's feed code is
# exported from its repository at the tag (default: ../Latecup at v1.0.0) into
# a temporary folder, nothing in either repository is touched, and two things
# are checked there with `flutter test`:
#   1. its FeedRepository, given the site as its feed, adopts the manifest and
#      reads New York's places from it;
#   2. on the manifest and on every broken variant of it (cases.py), the Python
#      port never accepts what the app refuses.
# Packages come from the pub cache (--offline, --no-pub): no network.
set -eu
SITE="$(cd "${1:?usage: run.sh <site folder> [app repository] [tag]}" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="${2:-$ROOT/../Latecup}"
TAG="${3:-v1.0.0}"
test -f "$SITE/v1/manifest.json" || { echo "no feed in $SITE" >&2; exit 1; }
TMP="$(mktemp -d)"
git -C "$APP" archive "$TAG" lib/app_identity.dart lib/feed lib/hours lib/services/file_store.dart assets/data | tar -x -C "$TMP"
cp "$HERE/pubspec.yaml" "$TMP/pubspec.yaml"
mkdir -p "$TMP/test"
cp "$HERE/us_manifest_test.dart" "$TMP/test/us_manifest_test.dart"
"$ROOT/.venv/bin/python" "$HERE/cases.py" "$SITE/v1/manifest.json" "$TMP/cases.json"
cd "$TMP"
flutter pub get --offline > /dev/null
SITE="$SITE/v1" flutter test --no-pub test/us_manifest_test.dart
echo "the app's code at $TAG, in $TMP"
