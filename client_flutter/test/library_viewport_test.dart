import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/web/web_shell_page.dart';

void main() {
  testWidgets('library avoids portrait and landscape cutouts without double insets', (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    for (final (size, insets) in const [
      (Size(393, 852), EdgeInsets.fromLTRB(0, 59, 0, 34)),
      (Size(852, 393), EdgeInsets.fromLTRB(59, 0, 59, 21)),
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
      expect(tester.getRect(find.byKey(const ValueKey('web-content'))),
        Rect.fromLTRB(insets.left, insets.top, size.width - insets.right, size.height - insets.bottom));
      expect(remaining, EdgeInsets.zero);
      expect(tester.takeException(), isNull);
    }
  });
}
