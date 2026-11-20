import { describe, expect, it } from 'vitest'
import { fill, head, played } from './progress'
import playerCss from '../styles/player.css?raw'
import followCss from '../styles/panels/follow.css?raw'
import engine from './engine.tsx?raw'
import audioPlayer from '../ui/AudioPlayer.tsx?raw'
import miniPlayer from '../ui/MiniPlayer.tsx?raw'
import audioFollow from '../components/AudioFollow.tsx?raw'

// The bar's elements are written to directly, so a stand-in with a `style` is all a painter needs.
const element = () => ({ style: {} as Record<string, string> }) as unknown as HTMLElement

describe('what is written to the elements that draw the position', () => {
  it('scales a fill to the share played', () => {
    const el = element()
    fill(el, 0.25)
    expect(el.style.transform).toBe('scaleX(0.25)')
  })

  it('places a playhead along its parent', () => {
    const el = element()
    head(el, 0.25)
    expect(el.style.left).toBe('25%')
  })

  it('masks the played bars up to the playhead, fading over the given pixels', () => {
    const el = element()
    played(8)(el, 0.5)
    expect(el.style.maskImage).toBe('linear-gradient(to right, black calc(50% - 8px), transparent 50%)')
    expect(el.style.webkitMaskImage).toBe(el.style.maskImage) // Safari still reads the prefixed one
  })

  it('shows nothing played at the start and everything at the end', () => {
    const start = element()
    played(10)(start, 0)
    expect(start.style.maskImage).toBe('linear-gradient(to right, black calc(0% - 10px), transparent 0%)')
    const end = element()
    played(10)(end, 1)
    expect(end.style.maskImage).toBe('linear-gradient(to right, black calc(100% - 10px), transparent 100%)')
  })
})

// A CSS custom property written every frame makes the browser re-style everything inside the element it is written
// on, registered as inherited or not (measured in Chrome: 4.5 ms for a waveform's bars, 23 ms of style work a frame
// on the whole follow-along layer). The position of the bar is written as ordinary properties instead
// (progress.ts). This keeps a variable from creeping back.
describe('the bar does not move through a CSS variable', () => {
  const files: Record<string, string> = {
    'styles/player.css': playerCss,
    'styles/panels/follow.css': followCss,
    'player/engine.tsx': engine,
    'ui/AudioPlayer.tsx': audioPlayer,
    'ui/MiniPlayer.tsx': miniPlayer,
    'components/AudioFollow.tsx': audioFollow,
  }
  for (const [name, text] of Object.entries(files)) {
    it(`${name} has no --progress`, () => {
      // Comments may explain why; code and rules may not use it.
      const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      expect(code).not.toMatch(/--progress\b/)
    })
  }
})
