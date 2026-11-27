// The released app's own feed code (the app repository at a tag) run on a
// built site's manifest and on every broken variant of it. See run.sh.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:latecup/feed/feed_repository.dart';
import 'package:latecup/feed/models.dart';
import 'package:latecup/services/file_store.dart';

/// What 1.0.0's FeedRepository._adopt does with a manifest, up to the
/// point where it would fetch the places file.
bool adopts(Object? raw) {
  try {
    final minBuild = raw is Map<String, dynamic> ? raw['min_build'] : null;
    if (minBuild is num && minBuild > 3) return false; // "Update Latecup"
    final manifest = Manifest.fromJson(raw);
    if (manifest.format != 1) return false;
    FeedRepository.checkManifest(manifest);
    return true;
  } on Object {
    return false;
  }
}

void main() {
  final site = Platform.environment['SITE']!;

  test('the app takes the manifest and New York from it', () async {
    final asked = <String>[];
    final client = MockClient((request) async {
      final name = request.url.pathSegments.last;
      asked.add(name);
      final file = File('$site/$name');
      if (!file.existsSync()) return http.Response('not found', 404);
      return http.Response.bytes(file.readAsBytesSync(), 200, headers: {'etag': '"x"'});
    });
    final repo = FeedRepository(
      httpClient: client,
      store: MemoryFileStore(),
      assets: (name) async => File(name).readAsBytes(),
      build: 3,
    );
    await repo.load();
    expect(repo.origin, FeedOrigin.bundled);
    final bundled = repo.places.length;
    await repo.refresh(force: true);
    expect(repo.offline, isFalse, reason: 'the refresh failed: 1.0.0 refused the feed');
    expect(repo.updateRequired, isFalse);
    expect(repo.origin, FeedOrigin.downloaded);
    final built = jsonDecode(File('$site/manifest.json').readAsStringSync()) as Map<String, dynamic>;
    expect(repo.manifest.cities.length, (built['cities'] as List<dynamic>).length);
    expect(repo.city.id, 'nyc');
    final expected = ((built['cities'] as List<dynamic>)[0] as Map<String, dynamic>)['count'] as int;
    expect(repo.places.length, expected);
    // it asks for the manifest and New York's file, and for no other area's
    expect(asked, ['manifest.json', 'nyc.json']);
    final places = repo.places;
    final fromLayer = places.where((p) => p.id.startsWith('x-starbucks-') || p.id.startsWith('x-dunkin-')).length;
    // ignore: avoid_print
    print('1.0.0: bundled $bundled places -> downloaded ${places.length} places, '
        '${places.where((p) => p.source == HoursSource.brand).length} brand, '
        '$fromLayer Starbucks or Dunkin stores with x- ids, '
        '${places.where((p) => p.hood == null || p.boro == null).length} without hood or boro');
  });

  test('the Python port and the app agree on every case', () {
    final cases = jsonDecode(File('cases.json').readAsStringSync()) as List<dynamic>;
    var agree = 0;
    final stricter = <String>[];
    final wrong = <String>[];
    for (final c in cases) {
      final name = c['name'] as String;
      final python = c['python_accepts'] as bool;
      final dart = adopts(c['manifest']);
      if (python == dart) {
        agree++;
      } else if (!python && dart) {
        stricter.add(name);
      } else {
        wrong.add(name);
      }
    }
    // ignore: avoid_print
    print('${cases.length} cases: $agree agree; the port is stricter than the app on ${stricter.length}: $stricter');
    expect(wrong, isEmpty, reason: 'the Python port accepts what 1.0.0 refuses');
  });
}
