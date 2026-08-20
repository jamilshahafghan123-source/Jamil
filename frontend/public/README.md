# Logo assets

| File | Size | Used by |
|---|---|---|
| `j-gold-ai-logo.png` | 1254x1254, 1.7 MB | **Master.** Kept as the source artwork. No page loads it. |
| `j-gold-ai-mark.png` | 256x256, 118 KB | The emblem alone — every small placement (top bars, Login, Sign Up, SubscriptionRequired, Dashboard header) and the favicon. |
| `j-gold-ai-lockup.png` | 437x512, 350 KB | The whole lockup, black margin trimmed — the home hero. |

Both derivatives are cropped from the master and carry no black margin, so
they need no runtime cropping. `src/components/Brand.tsx` is the only place
these paths appear; change them there, not per page.

To regenerate after replacing the master, re-cut with the same crop windows
(fractions of the master's width):

    mark   left 0.2016  top 0.0872  w 0.62   h 0.62    -> 256px square
    lockup left 0.128   top 0.068   w 0.744  h 0.872   -> 512px tall

If a derivative is missing, `Brand` falls back to a vector emblem and every
page stays branded.
