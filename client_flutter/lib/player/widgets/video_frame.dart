import 'package:flutter/widgets.dart';

import '../video_scale.dart';

/// Places the decoded picture into the rectangle demanded by a scale mode.
///
/// The modes that only decide a frame (fit, 16:9, 4:3, 21:9) are pure layout:
/// the surface keeps its own ratio inside the rectangle and the rest of the
/// player stays black. Cropping hands the surface a rectangle larger than the
/// viewport and clips the overflow. Stretching fits first and then scales the
/// two axes independently, which is what actually distorts the picture.
class VideoFrame extends StatelessWidget {
  final VideoScaleMode mode;
  final double? aspect;
  final Widget child;

  const VideoFrame({
    super.key,
    required this.mode,
    required this.child,
    this.aspect,
  });

  /// Rectangle the surface is laid out into, before the final scale.
  ///
  /// Cropping returns a rectangle larger than [container]; the caller clips the
  /// overflow. Stretching keeps the video ratio and lets [boxFit] distort it
  /// into the container.
  static Size targetSize(
    VideoScaleMode mode,
    Size container,
    double? aspect,
  ) {
    final width = container.width;
    final height = container.height;
    if (!width.isFinite || !height.isFinite || width <= 0 || height <= 0) {
      return container;
    }
    final forced = mode.forcedAspect;
    if (forced != null) return _fit(forced, width, height);
    final ratio = _usable(aspect);
    if (ratio == null) return Size(width, height);
    return switch (mode) {
      VideoScaleMode.crop => _cover(ratio, width, height),
      _ => _fit(ratio, width, height),
    };
  }

  /// How the laid-out rectangle is scaled onto the container.
  static BoxFit boxFitFor(VideoScaleMode mode) => switch (mode) {
        VideoScaleMode.crop => BoxFit.cover,
        VideoScaleMode.stretch => BoxFit.fill,
        _ => BoxFit.contain,
      };

  static double? _usable(double? value) {
    if (value == null || !value.isFinite || value <= 0) return null;
    return value;
  }

  static Size _fit(double ratio, double width, double height) {
    var w = width;
    var h = w / ratio;
    if (h > height) {
      h = height;
      w = h * ratio;
    }
    return Size(w, h);
  }

  static Size _cover(double ratio, double width, double height) {
    var w = width;
    var h = w / ratio;
    if (h < height) {
      h = height;
      w = h * ratio;
    }
    return Size(w, h);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final container = Size(constraints.maxWidth, constraints.maxHeight);
        final ratio = mode.forcedAspect ?? _usable(aspect);
        if (ratio == null) {
          // The video size is still unknown: let the surface decide.
          return SizedBox.expand(child: child);
        }
        final size = targetSize(mode, container, ratio);
        // FittedBox sizes the surface at its real pixel rectangle and only
        // scales when the mode distorts or crops it, so platform views keep
        // their sharpness instead of being stretched by layout constraints.
        return ClipRect(
          child: SizedBox.expand(
            child: FittedBox(
              fit: boxFitFor(mode),
              alignment: Alignment.center,
              child: SizedBox(
                width: size.width,
                height: size.height,
                child: child,
              ),
            ),
          ),
        );
      },
    );
  }
}
