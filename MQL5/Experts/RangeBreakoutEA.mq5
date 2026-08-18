//+------------------------------------------------------------------+
//|                                              RangeBreakoutEA.mq5 |
//|                        Time based range breakout Expert Advisor  |
//+------------------------------------------------------------------+
#property copyright "Range Breakout EA"
#property link      ""
#property version   "1.00"
#property description "Builds a price range between two configurable server times,"
#property description "draws it on the chart and trades the breakout with stop orders."
#property description "Fixed money risk, range based SL/TP, automatic flat-out time."

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Enumerations                                                     |
//+------------------------------------------------------------------+
enum ENUM_TRADES_PER_DAY
  {
   TPD_BOTH = 0,   // Both directions (buy and sell)
   TPD_ONE  = 1    // Only one trade per day
  };

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "=== Range time window (server time) ==="
input int    InpRangeStartHour   = 0;      // Range start hour   (0-23)
input int    InpRangeStartMinute = 0;      // Range start minute (0-59)
input int    InpRangeEndHour     = 8;      // Range end hour     (0-23)
input int    InpRangeEndMinute   = 0;      // Range end minute   (0-59)

input group "=== Flat out / close time (server time) ==="
input int    InpCloseHour        = 21;     // Close hour   (0-23)
input int    InpCloseMinute      = 0;      // Close minute (0-59)

input group "=== Entries ==="
input ENUM_TRADES_PER_DAY InpTradesPerDay = TPD_BOTH;  // Trades per day
input int    InpBufferPoints     = 0;      // Entry offset beyond range (points)
input int    InpMinRangePoints   = 0;      // Min range size to trade (points, 0=off)
input int    InpMaxRangePoints   = 0;      // Max range size to trade (points, 0=off)
input int    InpRetrySeconds     = 5;      // Retry interval for pending orders (sec)

input group "=== Risk / money management ==="
input double InpRiskMoney        = 100.0;  // Risk per trade (account currency)
input bool   InpUseMinLotIfSmall = false;  // Use min lot if calculated lot is too small

input group "=== Stop loss / take profit (x range size) ==="
input double InpSLFactor         = 0.5;    // Stop loss factor
input bool   InpUseTakeProfit    = true;   // Use take profit
input double InpTPFactor         = 1.0;    // Take profit factor

input group "=== Order settings ==="
input long   InpMagic            = 20250818;   // Magic number
input int    InpSlippagePoints   = 20;         // Max deviation (points)
input string InpOrderComment     = "RangeBreakout"; // Order comment

input group "=== Visuals ==="
input bool   InpShowRange        = true;                 // Draw range on the chart
input bool   InpKeepHistory      = true;                 // Keep objects of previous days
input color  InpRangeColor       = clrDodgerBlue;        // Range box color
input color  InpBuyLineColor     = clrLimeGreen;         // Buy level color
input color  InpSellLineColor    = clrOrangeRed;         // Sell level color
input bool   InpFillRangeBox     = true;                 // Fill the range box
input bool   InpShowPanel        = true;                 // Show info panel (chart comment)

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CTrade   trade;

// --- session times of the trading day currently handled
datetime g_rangeStart  = 0;
datetime g_rangeEnd    = 0;
datetime g_closeTime   = 0;
datetime g_sessionId   = 0;      // == g_rangeStart, identifies the trading day

// --- range data
double   g_rangeHigh   = 0.0;
double   g_rangeLow    = 0.0;
bool     g_rangeValid  = false;  // at least one price collected
bool     g_rangeDone   = false;  // range window finished and finalised
bool     g_rangeOk     = false;  // range passed the size filter -> trading allowed

// --- entry levels / trade state
double   g_buyPrice    = 0.0;
double   g_sellPrice   = 0.0;
double   g_slDistance  = 0.0;
double   g_tpDistance  = 0.0;
double   g_lots        = 0.0;

ulong    g_buyTicket   = 0;      // pending buy stop ticket (0 = none)
ulong    g_sellTicket  = 0;      // pending sell stop ticket (0 = none)
bool     g_buyArmed    = false;  // we still want a long entry today
bool     g_sellArmed   = false;  // we still want a short entry today
bool     g_buyEntered  = false;  // long entry already taken today
bool     g_sellEntered = false;  // short entry already taken today
bool     g_buyPendFail  = false; // pending order could not be placed -> watch for breakout
bool     g_sellPendFail = false;
datetime g_buyRetry     = 0;     // next allowed pending placement attempt
datetime g_sellRetry    = 0;
datetime g_buyMktRetry  = 0;     // next allowed market entry attempt
datetime g_sellMktRetry = 0;
bool     g_buyWarned    = false; // "pending not possible" already logged
bool     g_sellWarned   = false;

bool     g_sessionClosed = false; // flat-out already executed for this session

string   g_prefix      = "";     // chart object prefix of the current session
string   g_prefixAll   = "";     // chart object prefix of the EA

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
double AskPrice() { return SymbolInfoDouble(_Symbol, SYMBOL_ASK); }
double BidPrice() { return SymbolInfoDouble(_Symbol, SYMBOL_BID); }

//+------------------------------------------------------------------+
//| Formatting shortcuts for the log and the info panel               |
//+------------------------------------------------------------------+
string PS(const double price)  { return DoubleToString(price, _Digits); }
string VS(const double volume) { return DoubleToString(volume, LotDigits()); }

//+------------------------------------------------------------------+
double NormPrice(const double price)
  {
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double p  = price;
   if(ts > 0.0)
      p = MathRound(price / ts) * ts;
   return NormalizeDouble(p, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
  }

//+------------------------------------------------------------------+
//| Minimum distance between price and stop levels required by broker |
//+------------------------------------------------------------------+
double MinStopDistance()
  {
   long stopLevel   = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freezeLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   long lvl = (stopLevel > freezeLevel) ? stopLevel : freezeLevel;
   if(lvl < 0)
      lvl = 0;
   return (double)lvl * _Point;
  }

//+------------------------------------------------------------------+
int LotDigits()
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      return 2;
   int digits = 0;
   double s = step;
   while(digits < 8 && MathAbs(s - MathRound(s)) > 1e-9)
     {
      s *= 10.0;
      digits++;
     }
   return digits;
  }

//+------------------------------------------------------------------+
//| Position size from a fixed money risk and the stop distance      |
//+------------------------------------------------------------------+
double CalculateLots(const double slDistance)
  {
   if(slDistance <= 0.0 || InpRiskMoney <= 0.0)
      return 0.0;

   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0.0)
      tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);

   if(tickSize <= 0.0 || tickValue <= 0.0)
     {
      Print("Range Breakout: tick size / tick value not available, cannot size the position.");
      return 0.0;
     }

   double lossPerLot = (slDistance / tickSize) * tickValue;
   if(lossPerLot <= 0.0)
      return 0.0;

   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = minLot > 0.0 ? minLot : 0.01;

   double lots = InpRiskMoney / lossPerLot;
   lots = MathFloor(lots / step + 1e-8) * step;   // never risk more than requested

   if(lots < minLot)
     {
      if(!InpUseMinLotIfSmall)
        {
         PrintFormat("Range Breakout: calculated lot %.4f is below the minimum %.4f - no trade. "
                     "Increase the risk or reduce the SL factor.", lots, minLot);
         return 0.0;
        }
      lots = minLot;
      PrintFormat("Range Breakout: calculated lot below minimum, using min lot %.4f "
                  "(money risk will be higher than %.2f).", minLot, InpRiskMoney);
     }
   if(maxLot > 0.0 && lots > maxLot)
      lots = maxLot;

   return NormalizeDouble(lots, LotDigits());
  }

//+------------------------------------------------------------------+
//| Session time handling                                            |
//+------------------------------------------------------------------+
int SecondsOfDay(const int hour, const int minute)
  {
   return hour * 3600 + minute * 60;
  }

//+------------------------------------------------------------------+
void BuildSession(const datetime dayAnchor, datetime &rStart, datetime &rEnd, datetime &cTime)
  {
   int startSec = SecondsOfDay(InpRangeStartHour, InpRangeStartMinute);
   int endSec   = SecondsOfDay(InpRangeEndHour,   InpRangeEndMinute);
   int closeSec = SecondsOfDay(InpCloseHour,      InpCloseMinute);

   rStart = dayAnchor + startSec;
   rEnd   = dayAnchor + endSec;
   if(rEnd <= rStart)              // range crosses midnight
      rEnd += 86400;

   cTime = dayAnchor + closeSec;
   while(cTime <= rEnd)            // flat-out is always after the range
      cTime += 86400;
  }

//+------------------------------------------------------------------+
//| Reset all per day state                                          |
//+------------------------------------------------------------------+
void ResetSession()
  {
   g_rangeHigh    = 0.0;
   g_rangeLow     = 0.0;
   g_rangeValid   = false;
   g_rangeDone    = false;
   g_rangeOk      = false;

   g_buyPrice     = 0.0;
   g_sellPrice    = 0.0;
   g_slDistance   = 0.0;
   g_tpDistance   = 0.0;
   g_lots         = 0.0;

   g_buyTicket    = 0;
   g_sellTicket   = 0;
   g_buyArmed     = false;
   g_sellArmed    = false;
   g_buyEntered   = false;
   g_sellEntered  = false;
   g_buyPendFail  = false;
   g_sellPendFail = false;
   g_buyRetry     = 0;
   g_sellRetry    = 0;
   g_buyMktRetry  = 0;
   g_sellMktRetry = 0;
   g_buyWarned    = false;
   g_sellWarned   = false;

   g_sessionClosed = false;

   g_prefix = StringFormat("%s%s_", g_prefixAll, TimeToString(g_rangeStart, TIME_DATE));

   if(!InpKeepHistory)
      DeleteObjectsExcept(g_prefix);

   SyncStateFromTerminal();

   PrintFormat("Range Breakout: new session - range %s .. %s, flat out %s",
               TimeToString(g_rangeStart, TIME_DATE | TIME_MINUTES),
               TimeToString(g_rangeEnd,   TIME_DATE | TIME_MINUTES),
               TimeToString(g_closeTime,  TIME_DATE | TIME_MINUTES));
  }

//+------------------------------------------------------------------+
//| Detect the session that is currently relevant                    |
//+------------------------------------------------------------------+
void UpdateSession()
  {
   datetime now      = TimeCurrent();
   datetime dayStart = (datetime)((long)now - (long)now % 86400);

   datetime bestStart = 0, bestEnd = 0, bestClose = 0;
   bool found = false;

   for(int d = -1; d <= 1; d++)
     {
      datetime s, e, c;
      BuildSession(dayStart + d * 86400, s, e, c);
      if(s <= now && (!found || s > bestStart))
        {
         bestStart = s;
         bestEnd   = e;
         bestClose = c;
         found     = true;
        }
     }

   if(!found)   // only possible for exotic clock states - fall back to today
      BuildSession(dayStart, bestStart, bestEnd, bestClose);

   if(bestStart != g_sessionId)
     {
      g_rangeStart = bestStart;
      g_rangeEnd   = bestEnd;
      g_closeTime  = bestClose;
      g_sessionId  = bestStart;
      ResetSession();
     }
  }

//+------------------------------------------------------------------+
//| Re-adopt orders / positions and detected entries after a restart |
//+------------------------------------------------------------------+
void SyncStateFromTerminal()
  {
   // open pending orders of this EA
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;

      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type == ORDER_TYPE_BUY_STOP)
        {
         g_buyTicket = ticket;
         g_buyPrice  = OrderGetDouble(ORDER_PRICE_OPEN);
         g_buyArmed  = true;
        }
      else
         if(type == ORDER_TYPE_SELL_STOP)
           {
            g_sellTicket = ticket;
            g_sellPrice  = OrderGetDouble(ORDER_PRICE_OPEN);
            g_sellArmed  = true;
           }
     }

   // currently open positions of this EA
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;

      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         g_buyEntered = true;
      else
         g_sellEntered = true;
     }

   // entries that were already taken (and maybe closed again) in this session
   if(HistorySelect(g_rangeStart, TimeCurrent() + 60))
     {
      int deals = HistoryDealsTotal();
      for(int i = 0; i < deals; i++)
        {
         ulong dt = HistoryDealGetTicket(i);
         if(dt == 0)
            continue;
         if(HistoryDealGetString(dt, DEAL_SYMBOL) != _Symbol)
            continue;
         if(HistoryDealGetInteger(dt, DEAL_MAGIC) != InpMagic)
            continue;
         if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_IN)
            continue;

         if((ENUM_DEAL_TYPE)HistoryDealGetInteger(dt, DEAL_TYPE) == DEAL_TYPE_BUY)
            g_buyEntered = true;
         else
            if((ENUM_DEAL_TYPE)HistoryDealGetInteger(dt, DEAL_TYPE) == DEAL_TYPE_SELL)
               g_sellEntered = true;
        }
     }

   if(g_buyEntered)
      g_buyArmed = false;
   if(g_sellEntered)
      g_sellArmed = false;
  }

//+------------------------------------------------------------------+
//| Range calculation                                                |
//+------------------------------------------------------------------+
void MergeRangePrice(const double high, const double low)
  {
   if(high <= 0.0 || low <= 0.0)
      return;

   if(!g_rangeValid)
     {
      g_rangeHigh  = high;
      g_rangeLow   = low;
      g_rangeValid = true;
      return;
     }
   if(high > g_rangeHigh)
      g_rangeHigh = high;
   if(low < g_rangeLow)
      g_rangeLow = low;
  }

//+------------------------------------------------------------------+
//| Merge all completed M1 bars of the range window                  |
//+------------------------------------------------------------------+
bool MergeRangeFromBars()
  {
   datetime to = (TimeCurrent() < g_rangeEnd) ? TimeCurrent() : g_rangeEnd;
   to = to - 1;                     // only bars that opened inside the window
   if(to < g_rangeStart)
      return false;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(_Symbol, PERIOD_M1, g_rangeStart, to, rates);
   if(copied <= 0)
      return false;

   for(int i = 0; i < copied; i++)
     {
      if(rates[i].time < g_rangeStart || rates[i].time >= g_rangeEnd)
         continue;
      MergeRangePrice(rates[i].high, rates[i].low);
     }
   return true;
  }

//+------------------------------------------------------------------+
//| Finalise the range and prepare the entry levels                  |
//+------------------------------------------------------------------+
void FinalizeRange()
  {
   MergeRangeFromBars();
   g_rangeDone = true;

   if(!g_rangeValid || g_rangeHigh <= g_rangeLow)
     {
      Print("Range Breakout: no valid range data for this session - no trades today.");
      g_rangeOk = false;
      return;
     }

   double rangeSize   = g_rangeHigh - g_rangeLow;
   double rangePoints = rangeSize / _Point;

   if(InpMinRangePoints > 0 && rangePoints < InpMinRangePoints)
     {
      PrintFormat("Range Breakout: range %.0f points is smaller than the minimum %d - no trades today.",
                  rangePoints, InpMinRangePoints);
      g_rangeOk = false;
      return;
     }
   if(InpMaxRangePoints > 0 && rangePoints > InpMaxRangePoints)
     {
      PrintFormat("Range Breakout: range %.0f points is larger than the maximum %d - no trades today.",
                  rangePoints, InpMaxRangePoints);
      g_rangeOk = false;
      return;
     }

   double buffer = (double)InpBufferPoints * _Point;
   g_buyPrice  = NormPrice(g_rangeHigh + buffer);
   g_sellPrice = NormPrice(g_rangeLow  - buffer);

   // stop loss / take profit distances from the range size
   g_slDistance = rangeSize * InpSLFactor;
   g_tpDistance = InpUseTakeProfit ? rangeSize * InpTPFactor : 0.0;

   double minDist = MinStopDistance();
   if(minDist > 0.0 && g_slDistance < minDist)
     {
      PrintFormat("Range Breakout: SL distance %s is below the broker minimum %s - widened.",
                  PS(g_slDistance), PS(minDist));
      g_slDistance = minDist;
     }
   if(g_tpDistance > 0.0 && minDist > 0.0 && g_tpDistance < minDist)
      g_tpDistance = minDist;

   g_lots = CalculateLots(g_slDistance);
   if(g_lots <= 0.0)
     {
      g_rangeOk = false;
      return;
     }

   g_rangeOk  = true;
   g_buyArmed = g_buyArmed  || !g_buyEntered;
   g_sellArmed = g_sellArmed || !g_sellEntered;

   PrintFormat("Range Breakout: range high %s low %s size %.0f points | "
               "buy stop %s sell stop %s | lots %s | SL %.0f pts | TP %s",
               PS(g_rangeHigh), PS(g_rangeLow), rangePoints,
               PS(g_buyPrice), PS(g_sellPrice),
               VS(g_lots), g_slDistance / _Point,
               (g_tpDistance > 0.0 ? StringFormat("%.0f pts", g_tpDistance / _Point) : "off"));
  }

//+------------------------------------------------------------------+
//| Order / position helpers                                         |
//+------------------------------------------------------------------+
bool PendingExists(const ulong ticket)
  {
   if(ticket == 0)
      return false;
   return OrderSelect(ticket);
  }

//+------------------------------------------------------------------+
bool PendingWasFilled(const ulong ticket)
  {
   if(ticket == 0)
      return false;
   if(!HistoryOrderSelect(ticket))
      return false;
   ENUM_ORDER_STATE state = (ENUM_ORDER_STATE)HistoryOrderGetInteger(ticket, ORDER_STATE);
   return (state == ORDER_STATE_FILLED || state == ORDER_STATE_PARTIAL);
  }

//+------------------------------------------------------------------+
int CountOurOrders()
  {
   int count = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         count++;
     }
   return count;
  }

//+------------------------------------------------------------------+
int CountOurPositions()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         count++;
     }
   return count;
  }

//+------------------------------------------------------------------+
void DeletePending(ulong &ticket)
  {
   if(ticket == 0)
      return;
   if(OrderSelect(ticket))
     {
      if(!trade.OrderDelete(ticket))
         PrintFormat("Range Breakout: could not delete order #%I64u (%d - %s)",
                     ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
   ticket = 0;
  }

//+------------------------------------------------------------------+
//| One entry was taken - handle the "one trade per day" rule        |
//+------------------------------------------------------------------+
void OnEntryTaken(const bool isBuy)
  {
   if(isBuy)
     {
      g_buyEntered = true;
      g_buyArmed   = false;
     }
   else
     {
      g_sellEntered = true;
      g_sellArmed   = false;
     }

   if(InpTradesPerDay == TPD_ONE)
     {
      if(isBuy)
        {
         g_sellArmed = false;
         DeletePending(g_sellTicket);
        }
      else
        {
         g_buyArmed = false;
         DeletePending(g_buyTicket);
        }
      Print("Range Breakout: one trade per day - opposite side cancelled.");
     }
  }

//+------------------------------------------------------------------+
//| Watch the pending orders for fills / cancellations               |
//+------------------------------------------------------------------+
void CheckPendingStatus()
  {
   if(g_buyTicket != 0 && !PendingExists(g_buyTicket))
     {
      ulong t = g_buyTicket;
      g_buyTicket = 0;
      if(PendingWasFilled(t))
        {
         PrintFormat("Range Breakout: buy stop #%I64u filled.", t);
         OnEntryTaken(true);
        }
      else
         PrintFormat("Range Breakout: buy stop #%I64u is gone without a fill.", t);
     }

   if(g_sellTicket != 0 && !PendingExists(g_sellTicket))
     {
      ulong t = g_sellTicket;
      g_sellTicket = 0;
      if(PendingWasFilled(t))
        {
         PrintFormat("Range Breakout: sell stop #%I64u filled.", t);
         OnEntryTaken(false);
        }
      else
         PrintFormat("Range Breakout: sell stop #%I64u is gone without a fill.", t);
     }
  }

//+------------------------------------------------------------------+
//| Try to place one pending stop order                              |
//+------------------------------------------------------------------+
bool PlacePending(const bool isBuy)
  {
   double price = isBuy ? g_buyPrice : g_sellPrice;
   double sl    = isBuy ? NormPrice(price - g_slDistance) : NormPrice(price + g_slDistance);
   double tp    = 0.0;
   if(g_tpDistance > 0.0)
      tp = isBuy ? NormPrice(price + g_tpDistance) : NormPrice(price - g_tpDistance);

   string comment = InpOrderComment;
   bool ok;
   if(isBuy)
      ok = trade.BuyStop(g_lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
   else
      ok = trade.SellStop(g_lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);

   if(ok && trade.ResultOrder() > 0)
     {
      if(isBuy)
        {
         g_buyTicket = trade.ResultOrder();
         g_buyWarned = false;
        }
      else
        {
         g_sellTicket = trade.ResultOrder();
         g_sellWarned = false;
        }
      PrintFormat("Range Breakout: %s stop placed at %s (SL %s, TP %s), ticket #%I64u",
                  isBuy ? "buy" : "sell", PS(price), PS(sl),
                  (tp > 0.0 ? PS(tp) : "off"), trade.ResultOrder());
      return true;
     }

   bool warned = isBuy ? g_buyWarned : g_sellWarned;
   if(!warned)
     {
      PrintFormat("Range Breakout: %s stop could not be placed at %s (%d - %s). "
                  "Waiting for the breakout to enter at market.",
                  isBuy ? "buy" : "sell", PS(price),
                  trade.ResultRetcode(), trade.ResultRetcodeDescription());
      if(isBuy)
         g_buyWarned = true;
      else
         g_sellWarned = true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Market entry used when the pending order was not possible        |
//+------------------------------------------------------------------+
bool OpenMarket(const bool isBuy)
  {
   double price = isBuy ? AskPrice() : BidPrice();
   double sl    = isBuy ? NormPrice(price - g_slDistance) : NormPrice(price + g_slDistance);
   double tp    = 0.0;
   if(g_tpDistance > 0.0)
      tp = isBuy ? NormPrice(price + g_tpDistance) : NormPrice(price - g_tpDistance);

   bool ok;
   if(isBuy)
      ok = trade.Buy(g_lots, _Symbol, 0.0, sl, tp, InpOrderComment);
   else
      ok = trade.Sell(g_lots, _Symbol, 0.0, sl, tp, InpOrderComment);

   if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE ||
             trade.ResultRetcode() == TRADE_RETCODE_PLACED ||
             trade.ResultRetcode() == TRADE_RETCODE_DONE_PARTIAL))
     {
      PrintFormat("Range Breakout: market %s opened at %s after breakout (pending order was not possible).",
                  isBuy ? "buy" : "sell", PS(trade.ResultPrice()));
      OnEntryTaken(isBuy);
      return true;
     }

   PrintFormat("Range Breakout: market %s failed (%d - %s).",
               isBuy ? "buy" : "sell", trade.ResultRetcode(), trade.ResultRetcodeDescription());
   return false;
  }

//+------------------------------------------------------------------+
//| Entry management for one side                                    |
//|                                                                  |
//| 1. a stop order is placed at the range level                     |
//| 2. if the broker rejects it (price too close, level already       |
//|    passed, ...) the side is watched and entered at market as soon |
//|    as the breakout happens                                        |
//| 3. the pending order keeps being retried in the meantime          |
//+------------------------------------------------------------------+
void ManageSide(const bool isBuy)
  {
   bool armed = isBuy ? g_buyArmed : g_sellArmed;
   if(!armed)
      return;

   ulong ticket = isBuy ? g_buyTicket : g_sellTicket;
   if(ticket != 0)      // pending order is working, nothing to do
      return;

   datetime now   = TimeCurrent();
   int      pause = (InpRetrySeconds > 1) ? InpRetrySeconds : 1;

   // --- as long as the pending order was never rejected, only try the pending order
   bool pendFailed = isBuy ? g_buyPendFail : g_sellPendFail;
   if(!pendFailed)
     {
      datetime next = isBuy ? g_buyRetry : g_sellRetry;
      if(now < next)
         return;

      if(PlacePending(isBuy))
         return;

      if(isBuy)
        {
         g_buyPendFail = true;
         g_buyRetry    = now + pause;
        }
      else
        {
         g_sellPendFail = true;
         g_sellRetry    = now + pause;
        }
     }

   // --- pending order is currently not possible: enter at market on the breakout
   double level = isBuy ? g_buyPrice : g_sellPrice;
   double bid   = BidPrice();
   if(bid > 0.0)
     {
      bool breakout = isBuy ? (bid > level) : (bid < level);
      datetime mktNext = isBuy ? g_buyMktRetry : g_sellMktRetry;
      if(breakout && now >= mktNext)
        {
         if(OpenMarket(isBuy))
            return;
         if(isBuy)
            g_buyMktRetry = now + pause;
         else
            g_sellMktRetry = now + pause;
         return;
        }
     }

   // --- keep retrying the pending order until the breakout happens
   datetime retryAt = isBuy ? g_buyRetry : g_sellRetry;
   if(now >= retryAt)
     {
      if(PlacePending(isBuy))
        {
         if(isBuy)
            g_buyPendFail = false;
         else
            g_sellPendFail = false;
         return;
        }
      if(isBuy)
         g_buyRetry = now + pause;
      else
         g_sellRetry = now + pause;
     }
  }

//+------------------------------------------------------------------+
//| Flat out: delete pending orders and close positions              |
//+------------------------------------------------------------------+
void CloseSession()
  {
   g_buyArmed  = false;
   g_sellArmed = false;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      if(!trade.OrderDelete(ticket))
         PrintFormat("Range Breakout: close time - deleting order #%I64u failed (%d - %s)",
                     ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(!trade.PositionClose(ticket))
         PrintFormat("Range Breakout: close time - closing position #%I64u failed (%d - %s)",
                     ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }

   g_buyTicket  = 0;
   g_sellTicket = 0;

   if(CountOurOrders() == 0 && CountOurPositions() == 0)
     {
      if(!g_sessionClosed)
         Print("Range Breakout: close time reached - all orders deleted and positions closed.");
      g_sessionClosed = true;
     }
  }

//+------------------------------------------------------------------+
//| Chart objects                                                    |
//+------------------------------------------------------------------+
void DeleteObjectsExcept(const string keepPrefix)
  {
   if(g_prefixAll == "")   // never touch foreign objects
      return;

   for(int i = ObjectsTotal(0, 0) - 1; i >= 0; i--)
     {
      string name = ObjectName(0, i, 0);
      if(StringFind(name, g_prefixAll) != 0)
         continue;
      if(keepPrefix != "" && StringFind(name, keepPrefix) == 0)
         continue;
      ObjectDelete(0, name);
     }
  }

//+------------------------------------------------------------------+
void SetLine(const string name, const datetime t1, const double p1,
             const datetime t2, const double p2, const color clr,
             const ENUM_LINE_STYLE style, const int width)
  {
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2))
         return;
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
     }
   else
     {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
     }
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
  }

//+------------------------------------------------------------------+
void SetText(const string name, const datetime t, const double p,
             const string text, const color clr)
  {
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, p))
         return;
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
     }
   else
     {
      ObjectMove(0, name, 0, t, p);
     }
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
  }

//+------------------------------------------------------------------+
void DrawRange()
  {
   if(!InpShowRange || !g_rangeValid)
      return;

   datetime rightEdge = (TimeCurrent() < g_rangeEnd) ? TimeCurrent() : g_rangeEnd;

   // --- range box
   string box = g_prefix + "BOX";
   if(ObjectFind(0, box) < 0)
     {
      if(ObjectCreate(0, box, OBJ_RECTANGLE, 0, g_rangeStart, g_rangeHigh, rightEdge, g_rangeLow))
        {
         ObjectSetInteger(0, box, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, box, OBJPROP_HIDDEN, true);
         ObjectSetInteger(0, box, OBJPROP_BACK, true);
         ObjectSetInteger(0, box, OBJPROP_FILL, InpFillRangeBox);
        }
     }
   else
     {
      ObjectMove(0, box, 0, g_rangeStart, g_rangeHigh);
      ObjectMove(0, box, 1, rightEdge, g_rangeLow);
     }
   ObjectSetInteger(0, box, OBJPROP_COLOR, InpRangeColor);

   // --- projection of the levels until the flat out time
   if(g_rangeDone)
     {
      SetLine(g_prefix + "HI", g_rangeEnd, g_rangeHigh, g_closeTime, g_rangeHigh,
              InpBuyLineColor, STYLE_DOT, 1);
      SetLine(g_prefix + "LO", g_rangeEnd, g_rangeLow, g_closeTime, g_rangeLow,
              InpSellLineColor, STYLE_DOT, 1);

      if(g_rangeOk)
        {
         SetLine(g_prefix + "BUY", g_rangeEnd, g_buyPrice, g_closeTime, g_buyPrice,
                 InpBuyLineColor, STYLE_SOLID, 1);
         SetLine(g_prefix + "SELL", g_rangeEnd, g_sellPrice, g_closeTime, g_sellPrice,
                 InpSellLineColor, STYLE_SOLID, 1);
        }

      SetText(g_prefix + "TXT", g_rangeEnd, g_rangeHigh,
              StringFormat(" Range %.0f pts", (g_rangeHigh - g_rangeLow) / _Point),
              InpRangeColor);
     }

   // --- vertical marker for the flat out time
   string vline = g_prefix + "CLOSE";
   if(ObjectFind(0, vline) < 0)
     {
      if(ObjectCreate(0, vline, OBJ_VLINE, 0, g_closeTime, 0))
        {
         ObjectSetInteger(0, vline, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, vline, OBJPROP_HIDDEN, true);
         ObjectSetInteger(0, vline, OBJPROP_BACK, true);
         ObjectSetInteger(0, vline, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, vline, OBJPROP_COLOR, InpRangeColor);
        }
     }
  }

//+------------------------------------------------------------------+
string SideState(const bool isBuy)
  {
   if(isBuy ? g_buyEntered : g_sellEntered)
      return "traded";
   if(!(isBuy ? g_buyArmed : g_sellArmed))
      return "off";
   if((isBuy ? g_buyTicket : g_sellTicket) != 0)
      return "pending";
   if(isBuy ? g_buyPendFail : g_sellPendFail)
      return "market on breakout";
   return "armed";
  }

//+------------------------------------------------------------------+
void ShowPanel()
  {
   if(!InpShowPanel)
      return;

   string state;
   datetime now = TimeCurrent();
   if(now < g_rangeStart)
      state = "waiting for range";
   else
      if(now < g_rangeEnd)
         state = "building range";
      else
         if(now >= g_closeTime)
            state = "closed for the day";
         else
            state = g_rangeOk ? "trading breakout" : "no trades today";

   string txt = StringFormat("Range Breakout EA  |  %s\n", _Symbol);
   txt += StringFormat("Range      : %s - %s\n",
                       TimeToString(g_rangeStart, TIME_MINUTES),
                       TimeToString(g_rangeEnd, TIME_MINUTES));
   txt += StringFormat("Flat out   : %s\n", TimeToString(g_closeTime, TIME_DATE | TIME_MINUTES));
   txt += StringFormat("Server time: %s\n", TimeToString(now, TIME_DATE | TIME_SECONDS));
   txt += StringFormat("State      : %s\n", state);

   if(g_rangeValid)
      txt += StringFormat("High/Low   : %s / %s  (%.0f pts)\n",
                          PS(g_rangeHigh), PS(g_rangeLow),
                          (g_rangeHigh - g_rangeLow) / _Point);
   if(g_rangeDone && g_rangeOk)
     {
      txt += StringFormat("Buy / Sell : %s / %s\n", PS(g_buyPrice), PS(g_sellPrice));
      txt += StringFormat("Lots       : %s  (risk %.2f %s)\n",
                          VS(g_lots), InpRiskMoney,
                          AccountInfoString(ACCOUNT_CURRENCY));
      txt += StringFormat("SL / TP    : %.0f pts / %s\n", g_slDistance / _Point,
                          (g_tpDistance > 0.0 ? StringFormat("%.0f pts", g_tpDistance / _Point) : "off"));
      txt += StringFormat("Entries    : buy %s | sell %s\n",
                          SideState(true), SideState(false));
     }

   Comment(txt);
  }

//+------------------------------------------------------------------+
//| Main processing                                                  |
//+------------------------------------------------------------------+
void Process()
  {
   UpdateSession();

   datetime now = TimeCurrent();

   // --- before the range starts
   if(now < g_rangeStart)
     {
      ShowPanel();
      return;
     }

   // --- range is being built
   if(now < g_rangeEnd)
     {
      static datetime lastBarMerge = 0;
      datetime minute = (datetime)((long)now - (long)now % 60);
      if(minute != lastBarMerge)
        {
         MergeRangeFromBars();
         lastBarMerge = minute;
        }
      double bid = BidPrice();
      double ask = AskPrice();
      if(bid > 0.0)
         MergeRangePrice(bid, bid);
      if(ask > 0.0 && bid <= 0.0)
         MergeRangePrice(ask, ask);

      DrawRange();
      ShowPanel();
      return;
     }

   // --- range window is over
   if(!g_rangeDone)
     {
      FinalizeRange();
      DrawRange();
     }

   // --- flat out time reached: no more trades today
   if(now >= g_closeTime)
     {
      if(!g_sessionClosed)
         CloseSession();
      DrawRange();
      ShowPanel();
      return;
     }

   // --- fills / cancellations are tracked even when trading is switched off
   CheckPendingStatus();

   if(g_rangeOk && IsTradingAllowed())
     {
      ManageSide(true);
      ManageSide(false);
     }

   DrawRange();
   ShowPanel();
  }

//+------------------------------------------------------------------+
bool IsTradingAllowed()
  {
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return false;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
      return false;
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
      return false;
   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
      return false;
   if(SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE) == SYMBOL_TRADE_MODE_DISABLED)
      return false;
   return true;
  }

//+------------------------------------------------------------------+
//| Input validation                                                 |
//+------------------------------------------------------------------+
bool ValidateInputs()
  {
   if(InpRangeStartHour < 0 || InpRangeStartHour > 23 ||
      InpRangeEndHour   < 0 || InpRangeEndHour   > 23 ||
      InpCloseHour      < 0 || InpCloseHour      > 23)
     {
      Print("Range Breakout: hour inputs must be between 0 and 23.");
      return false;
     }
   if(InpRangeStartMinute < 0 || InpRangeStartMinute > 59 ||
      InpRangeEndMinute   < 0 || InpRangeEndMinute   > 59 ||
      InpCloseMinute      < 0 || InpCloseMinute      > 59)
     {
      Print("Range Breakout: minute inputs must be between 0 and 59.");
      return false;
     }
   if(SecondsOfDay(InpRangeStartHour, InpRangeStartMinute) ==
      SecondsOfDay(InpRangeEndHour, InpRangeEndMinute))
     {
      Print("Range Breakout: range start and range end must be different.");
      return false;
     }
   if(InpRiskMoney <= 0.0)
     {
      Print("Range Breakout: risk per trade must be greater than zero.");
      return false;
     }
   if(InpSLFactor <= 0.0)
     {
      Print("Range Breakout: stop loss factor must be greater than zero.");
      return false;
     }
   if(InpUseTakeProfit && InpTPFactor <= 0.0)
     {
      Print("Range Breakout: take profit factor must be greater than zero when TP is used.");
      return false;
     }
   if(InpMinRangePoints > 0 && InpMaxRangePoints > 0 && InpMinRangePoints > InpMaxRangePoints)
     {
      Print("Range Breakout: minimum range size is larger than the maximum range size.");
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(!ValidateInputs())
      return INIT_PARAMETERS_INCORRECT;

   g_prefixAll = StringFormat("RBEA_%I64d_", InpMagic);

   trade.SetExpertMagicNumber((ulong)InpMagic);
   trade.SetDeviationInPoints((ulong)(InpSlippagePoints > 0 ? InpSlippagePoints : 0));
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   g_sessionId = 0;      // force a session setup on the first Process() call
   UpdateSession();

   EventSetTimer(1);

   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");

   // keep the drawings visible when the visual tester finishes
   if(!MQLInfoInteger(MQL_VISUAL_MODE))
      DeleteObjectsExcept("");

   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   Process();
  }

//+------------------------------------------------------------------+
//| Timer - keeps the flat out time reliable on quiet symbols        |
//+------------------------------------------------------------------+
void OnTimer()
  {
   Process();
  }
//+------------------------------------------------------------------+
