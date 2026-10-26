import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/models/playback_payload.dart';
import 'package:strmaction_desktop/player/playback_engine.dart';
import 'package:strmaction_desktop/player/widgets/player_drawer.dart';

Widget buildDrawer(List<PlaylistEntry> playlist) {
  return MaterialApp(
    home: Scaffold(
      body: SizedBox(
        width: 800,
        height: 600,
        child: PlayerDrawer(
          visible: true,
          playlist: playlist,
          currentItemId: playlist.first.itemId,
          currentSpeed: 1,
          boostSpeed: 2,
          subtitles: const [],
          audioTracks: const [],
          currentSid: null,
          currentAid: null,
          subtitleHint: '',
          videoScale: VideoScaleMode.fit,
          scaleModes: VideoScaleMode.values,
          onClose: () {},
          onEpisodeSelected: (_) {},
          onSpeedSelected: (_) {},
          onBoostSpeedSelected: (_) {},
          onSubtitleSelected: (_) {},
          onAudioSelected: (_) {},
          onScaleSelected: (_) {},
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('课程视频没有季集号时按播放列表序号显示', (tester) async {
    await tester.pumpWidget(
      buildDrawer(const [
        PlaylistEntry(
          itemId: 1,
          title: '[1]--开班仪式',
          code: '',
          episodeNo: null,
          watched: false,
          current: true,
        ),
        PlaylistEntry(
          itemId: 2,
          title: '[2]--班会',
          code: '',
          episodeNo: null,
          watched: false,
          current: false,
        ),
      ]),
    );
    await tester.pumpAndSettle();

    expect(find.text('P01'), findsOneWidget);
    expect(find.text('P02'), findsOneWidget);
    expect(find.text('P00'), findsNothing);
  });

  testWidgets('上千个视频时自动定位到当前集且只构建可见条目', (tester) async {
    final playlist = List.generate(
      1000,
      (index) => PlaylistEntry(
        itemId: index + 1,
        title: '视频 ${index + 1}',
        code: '',
        episodeNo: null,
        watched: false,
        current: index == 500,
      ),
    );
    await tester.pumpWidget(buildDrawer(playlist));
    await tester.pumpAndSettle();

    expect(find.text('P501'), findsOneWidget);
    expect(find.text('P01'), findsNothing);
    expect(find.text('P1000'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
