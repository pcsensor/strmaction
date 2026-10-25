import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/web/web_shell_page.dart';

void main() {
  testWidgets('library fills the screen and leaves the insets to the page', (tester) async {
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
        Rect.fromLTWH(0, 0, size.width, size.height));
      // Flutter no longer shrinks the WebView: the document receives the insets
      // as --safe-* variables and pads its own header and navigation.
      expect(remaining, insets);
      expect(tester.takeException(), isNull);
    }
  });
}
