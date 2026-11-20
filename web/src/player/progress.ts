// How an element shows where the audio is: what is written to it, every frame, as the fraction played (0..1).
//
// These write ordinary inline properties and not a CSS custom property, on purpose. Writing a custom property on an
// element makes the browser re-style everything inside it, registered as not inherited or not. Measured in Chrome on
// the follow-along view: 4.5 ms to write it on the group of a waveform's bars, and 23 ms of style work every frame
// when it was written on the view's root (the view ran at 17 to 27 frames a second in testing). An ordinary
// property costs only the element it is written on: 0.1 ms or less for the same bars. So each element that draws the
// position gets its own painter.

export type Painter<T extends Element = HTMLElement | SVGElement> = (el: T, fraction: number) => void
type Styled = HTMLElement | SVGElement

/** A bar's fill: the element is as wide as the whole bar and `transform-origin: left`, scaled to what is played. */
export const fill: Painter<Styled> = (el, fraction) => { el.style.transform = `scaleX(${fraction})` }

/** A playhead: a thin element placed along its (positioned) parent. */
export const head: Painter<Styled> = (el, fraction) => { el.style.left = `${fraction * 100}%` }

/** The played bars of a waveform: shown up to the playhead, the last `fade` pixels fading out so the edge is soft
 *  rather than cut. */
export const played = (fade: number): Painter<Styled> => (el, fraction) => {
  const mask = `linear-gradient(to right, black calc(${fraction * 100}% - ${fade}px), transparent ${fraction * 100}%)`
  el.style.maskImage = mask
  el.style.webkitMaskImage = mask
}
