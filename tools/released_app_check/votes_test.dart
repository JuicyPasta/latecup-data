// The released app's own votes parser (the app repository at a tag) on a
// votes file that carries `prop`, and on the same file without it. See
// votes.sh.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:latecup/feed/models.dart';

void main() {
  final dir = Platform.environment['VOTES']!;

  CityVotes read(String name) {
    final doc = jsonDecode(File('$dir/$name').readAsStringSync()) as Map<String, dynamic>;
    return CityVotes.fromJson(doc, expectCity: doc['city'] as String);
  }

  test('the app reads a votes file with prop exactly as it reads the same file without it', () {
    final raw = jsonDecode(File('$dir/votes-with-prop.json').readAsStringSync()) as Map<String, dynamic>;
    final sent = raw['votes'] as Map<String, dynamic>;
    final now = read('votes-with-prop.json');
    final before = read('votes-before-prop.json');
    expect(now.city, before.city);
    expect(now.generated, before.generated);
    expect(now.byPlace.keys.toSet(), before.byPlace.keys.toSet());
    for (final id in before.byPlace.keys) {
      final a = now.byPlace[id]!;
      final b = before.byPlace[id]!;
      expect(
        [a.confirmations, a.latestConfirmation, a.wrongReports, a.latestWrongReport, a.starsMean, a.starsCount],
        [b.confirmations, b.latestConfirmation, b.wrongReports, b.latestWrongReport, b.starsMean, b.starsCount],
        reason: id,
      );
    }
    // a place that carries prop and nothing else says nothing the app can use: it is not kept
    final propOnly = sent.entries
        .where((e) => (e.value as Map<String, dynamic>).keys.toSet().difference({'prop'}).isEmpty)
        .map((e) => e.key)
        .toList();
    for (final id in propOnly) {
      expect(now.byPlace.containsKey(id), isFalse, reason: id);
    }
    final withProp = sent.values.where((v) => (v as Map<String, dynamic>).containsKey('prop')).length;
    // ignore: avoid_print
    print('the app at this tag: ${sent.length} places sent, $withProp with prop, ${propOnly.length} of them prop only; '
        '${now.byPlace.length} kept, each read the same with and without prop');
    expect(withProp, greaterThan(0));
  });
}
