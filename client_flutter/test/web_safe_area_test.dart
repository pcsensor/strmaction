import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:strmaction_desktop/web/web_safe_area.dart';

void main() {
  test('injects insets and lets the shell own the top and side padding', () {
    final script = buildWebShellSafeAreaScript(
      const EdgeInsets.fromLTRB(10, 59, 12, 34),
    );
    expect(script, contains("'--safe-top-inset', '59.0px'"));
    expect(script, contains("'--safe-right-inset', '12.0px'"));
    expect(script, contains("'--safe-bottom-inset', '34.0px'"));
    expect(script, contains("'--safe-left-inset', '10.0px'"));
    // 旧版网页只认识 .safe-top / .safe-x，必须强制归零，防止按钮留在
    // 摄像头下面或新版页面双倍留白。
    expect(script, contains('.safe-top{padding-top:0!important}'));
    expect(script, contains('.safe-x{padding-left:0!important;padding-right:0!important}'));
    // 底部仍由页面自己避让手势条。
    expect(script, isNot(contains('.safe-bottom')));
  });
}
