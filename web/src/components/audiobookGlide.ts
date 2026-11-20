// How the follow-along text glides to the line being read, kept apart from the view so it can be tested.
//
// It closes a fifth of the distance every 60th of a second, which is exponential smoothing with a time constant of
// GLIDE_MS; by the clock and not by the frame, so a slow frame does not make the text arrive late (at 60 frames a
// second it is the same glide as a fifth per frame, at 10 it still arrives in the same time). It also has to end:
// scrollTop is whole pixels on a 1x screen, so a step under a pixel is lost to rounding and a gap of a pixel or less
// could never be closed by a fraction of itself. The glide used to spin forever on one, writing scrollTop 60 times a
// second for as long as the view was open.

/** The time constant of the glide, in milliseconds: 1/60 s over -ln(0.8), the 20% a frame it replaced. */
export const GLIDE_MS = 75
/** A gap this small is closed at once: the text is there. */
export const ARRIVED = 1

/** How far to move now, along a gap of `diff` pixels, after `ms` milliseconds since the last step: a share of the gap,
 *  but never less than a whole pixel (it would be lost to rounding), and in the direction of the gap. */
export function glideBy(diff: number, ms: number): number {
  const move = diff * (1 - Math.exp(-ms / GLIDE_MS))
  return Math.abs(move) < 1 ? Math.sign(diff) : move
}
