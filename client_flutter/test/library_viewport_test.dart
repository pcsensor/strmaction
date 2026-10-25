import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/web/web_shell_page.dart';

void main() {
  testWidgets('library stays below the cutout and leaves the bottom edge-to-edge',
      (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    for (final (size, insets) in const [
      (Size(393, 852), EdgeInsets.fromLTRB(0, 59, 0, 34)),
      (Size(852, 393), EdgeInsets.fromLTRB(59, 0, 59, 21)),
      (Size(412, 915), EdgeInsets.fromLTRB(0, 32, 0, 24)),
    ]) {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      EdgeInsets? remaining;
      await tester.pumpWidget(MaterialApp(home: MediaQuery(
        data: MediaQueryData(size: size, padding: insets, viewPadding: insets),
        child: Scaffold(body: LibraryViewport(child: Builder(builder: (context) {
          remaining = MediaQuery.paddingOf(context);
          return const SizedBox.expand(key: ValueKey('web-content'));
        }))),
      )));
      // 顶部和左右由 Flutter 壳避让，底部继续铺满交给页面处理手势条。
      expect(
        tester.getRect(find.byKey(const ValueKey('web-content'))),
        Rect.fromLTRB(insets.left, insets.top, size.width - insets.right, size.height),
      );
      expect(remaining, EdgeInsets.only(bottom: insets.bottom));
      expect(tester.takeException(), isNull);
    }
  });
}
