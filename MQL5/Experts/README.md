# Range Breakout EA (MetaTrader 5)

`RangeBreakoutEA.mq5` is a MetaTrader 5 Expert Advisor (MQL5 only, no MQL4 code) that
builds a price range between two configurable times of the day and trades the breakout
of that range with stop orders.

## Installation

1. Copy `RangeBreakoutEA.mq5` into `<MT5 data folder>/MQL5/Experts/`.
2. Open it in MetaEditor and press **F7** to compile.
3. Attach it to any chart of the symbol you want to trade and allow algo trading.

The EA is timeframe independent — the range is calculated from **M1 data** plus the
incoming ticks, so an M1 chart and an H1 chart produce exactly the same range. For
backtests use "Every tick" or "Every tick based on real ticks" (or at least make sure
M1 history is available).

## How it works

1. **Range window** — between *range start* and *range end* (server time) the EA tracks
   the highest and lowest price of the symbol. The forming range is drawn on the chart
   as a rectangle.
2. **Order placement** — the moment the range window ends, the EA places
   a **buy stop** at the range high and a **sell stop** at the range low
   (optionally offset by `InpBufferPoints`).
3. **Market fallback** — if the broker rejects a stop order (price is already through
   the level, stop level too small, trade context busy, …), that side switches to
   "market on breakout": as soon as price actually breaks the level the EA opens a
   market position instead. In the meantime it keeps retrying the pending order every
   `InpRetrySeconds` seconds.
4. **One or two trades per day** — with `InpTradesPerDay = Only one trade per day` the
   opposite pending order is deleted as soon as the first order is executed.
5. **Flat out** — at the *close time* the EA deletes all remaining pending orders,
   closes all its open positions and does not open anything else for that day.

Everything is scoped by the magic number and the chart symbol, so other EAs and manual
trades are never touched.

## Stop loss, take profit and position size

* `Range size = range high − range low`
* `Stop loss distance   = range size × InpSLFactor`
* `Take profit distance = range size × InpTPFactor` (only if `InpUseTakeProfit = true`)

With `InpUseTakeProfit = false` no take profit is set at all and the trade is closed
only by the stop loss or by the flat-out time.

The lot size comes from the fixed money risk:

```
lots = InpRiskMoney / (stop loss distance / tick size × tick value)
```

The result is rounded **down** to the volume step, so the requested risk is never
exceeded. If the result is smaller than the broker's minimum volume the trade is
skipped, unless `InpUseMinLotIfSmall = true` (then the minimum lot is used and the
risk is higher than requested — a message is written to the log).

If the calculated stop distance is smaller than the broker's stop/freeze level, it is
widened to that minimum first and the lot size is calculated from the widened distance,
so the money risk stays correct.

## Inputs

### Range time window (server time)

| Input | Description |
|---|---|
| `InpRangeStartHour` / `InpRangeStartMinute` | Start of the range window |
| `InpRangeEndHour` / `InpRangeEndMinute` | End of the range window |

All four are plain `int` inputs, so they can be used directly in the strategy tester's
optimizer (start/step/stop). If the end time is earlier than the start time the range
is treated as crossing midnight (e.g. 22:00 → 02:00 for an Asian session range).

### Flat out / close time (server time)

| Input | Description |
|---|---|
| `InpCloseHour` / `InpCloseMinute` | Pending orders are deleted, open positions are closed and no new trades are taken after this time |

The close time is always interpreted as the first occurrence after the range end.

### Entries

| Input | Default | Description |
|---|---|---|
| `InpTradesPerDay` | Both directions | `Both directions` = buy and sell can both trade; `Only one trade per day` = the second order is deleted once the first is executed |
| `InpBufferPoints` | 0 | Extra distance in points above the high / below the low for the entry levels |
| `InpMinRangePoints` | 0 | Skip the day if the range is smaller than this (0 = off) |
| `InpMaxRangePoints` | 0 | Skip the day if the range is larger than this (0 = off) |
| `InpRetrySeconds` | 5 | How often a rejected pending order is retried |

### Risk / money management

| Input | Default | Description |
|---|---|---|
| `InpRiskMoney` | 100.0 | Risk per trade as a fixed money amount in the account currency |
| `InpUseMinLotIfSmall` | false | Use the minimum lot when the calculated lot is below it |

### Stop loss / take profit

| Input | Default | Description |
|---|---|---|
| `InpSLFactor` | 0.5 | Stop loss = range size × this factor |
| `InpUseTakeProfit` | true | Turn the take profit off to close trades only at the close time |
| `InpTPFactor` | 1.0 | Take profit = range size × this factor |

### Order settings

| Input | Default | Description |
|---|---|---|
| `InpMagic` | 20250818 | Magic number |
| `InpSlippagePoints` | 20 | Maximum deviation for market entries |
| `InpOrderComment` | RangeBreakout | Order comment |

### Visuals

| Input | Default | Description |
|---|---|---|
| `InpShowRange` | true | Draw the range box, the entry levels and the close-time marker |
| `InpKeepHistory` | true | Keep the drawings of previous days |
| `InpRangeColor` / `InpBuyLineColor` / `InpSellLineColor` | — | Colors |
| `InpFillRangeBox` | true | Fill the range rectangle |
| `InpShowPanel` | true | Show the status text in the chart corner |

## Notes

* All times are **server times** (the times you see on the chart), not local PC times.
* The range and the breakout detection use bid prices, which is what the chart candles
  show. A buy stop order is triggered by the broker on the ask price, so it can fire a
  spread earlier than the bid-based breakout — use `InpBufferPoints` if you want a
  margin against that.
* Pending orders are kept as GTC orders and removed by the EA itself at the close time,
  which is more reliable across brokers than order expiration times.
* The EA also runs on a one-second timer, so the flat-out time is respected even on
  symbols that do not produce ticks at that moment.
* After a terminal restart the EA re-adopts its own orders, positions and already taken
  entries of the current day, so it does not enter twice.
