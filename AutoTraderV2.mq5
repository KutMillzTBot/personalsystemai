//+------------------------------------------------------------------+
//|  AutoTraderV2.mq5 — SupervisorTrainer Auto-Trader EA            |
//|  Reads signals from Python bridge → executes trades in MT5      |
//|  Features: OB50 entry, dynamic SL/TP, partial close, BE        |
//+------------------------------------------------------------------+
#property copyright "SupervisorTrainer v8"
#property version   "2.10"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>

// ── Inputs ──────────────────────────────────────────────────────
input string   InpBridgeURL    = "http://127.0.0.1:5050/signal"; // Bridge URL
input double   InpLotSize      = 0.01;    // Fixed lot (0 = auto from bridge)
input double   InpMinScore     = 0.62;    // Minimum signal confidence
input bool     InpUseSLTP      = true;    // Use bridge SL/TP levels
input bool     InpPartialClose = true;    // Close 50% at 1R profit
input bool     InpMoveToBreakEven = true; // Move SL to entry at 1R
input int      InpMagicNumber  = 77777;   // EA magic number
input int      InpPollSeconds  = 30;      // Poll interval (seconds)
input bool     InpDryRun       = false;   // Log signals only, no real trades
input int      InpMaxPositions = 3;       // Max concurrent positions

// ── Globals ─────────────────────────────────────────────────────
CTrade         Trade;
CPositionInfo  Pos;
datetime       LastPoll    = 0;
string         LastSignal  = "";
double         LastScore   = 0;

int OnInit() {
   Trade.SetMagicNumber(InpMagicNumber);
   Trade.SetDeviationInPoints(30);
   Print("[AutoTraderV2] EA started | Bridge: ", InpBridgeURL);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnTick() {
   if (TimeCurrent() - LastPoll < InpPollSeconds) return;
   LastPoll = TimeCurrent();

   string signal = "";
   double score = 0, ob50 = 0, slPrice = 0, tpPrice = 0;
   string symbol = Symbol();

   // ── Fetch signal from bridge ──────────────────────────────────
   if (!FetchSignal(symbol, signal, score, ob50, slPrice, tpPrice)) {
      Print("[AutoTraderV2] Bridge unreachable");
      return;
   }

   if (signal == LastSignal && score == LastScore) return;
   LastSignal = signal;
   LastScore  = score;

   Print("[AutoTraderV2] Signal=", signal, " Score=", DoubleToString(score,3),
         " OB50=", DoubleToString(ob50,5),
         " SL=", DoubleToString(slPrice,5),
         " TP=", DoubleToString(tpPrice,5));

   // ── Validate signal ───────────────────────────────────────────
   if (score < InpMinScore) {
      Print("[AutoTraderV2] Score too low: ", score, " < ", InpMinScore);
      return;
   }
   if (CountMyPositions() >= InpMaxPositions) {
      Print("[AutoTraderV2] Max positions reached: ", InpMaxPositions);
      return;
   }

   if (InpDryRun) {
      Print("[DRY RUN] Would open: ", signal, " @ ", ob50);
      return;
   }

   // ── Execute trade ─────────────────────────────────────────────
   double lot = InpLotSize > 0 ? InpLotSize : 0.01;
   if (signal == "BUY" || signal == "STRONG BUY") {
      ExecuteBuy(symbol, lot, ob50, slPrice, tpPrice);
   } else if (signal == "SELL" || signal == "STRONG SELL") {
      ExecuteSell(symbol, lot, ob50, slPrice, tpPrice);
   }

   // ── Partial close + breakeven management ─────────────────────
   ManagePositions(symbol);
}

//+------------------------------------------------------------------+
bool FetchSignal(string sym, string &sig, double &score,
                 double &ob50, double &sl, double &tp) {
   string url  = InpBridgeURL + "?symbol=" + sym;
   string resp = "";
   char   data[], result[];
   string headers = "Content-Type: application/json\r\n";

   ResetLastError();
   int res = WebRequest("GET", url, headers, 5000, data, result, headers);
   if (res == -1) return false;
   resp = CharArrayToString(result);

   // Simple JSON parse (no external lib needed)
   sig   = ExtractStr(resp, "signal");
   score = ExtractNum(resp, "score");
   ob50  = ExtractNum(resp, "ob50");
   sl    = ExtractNum(resp, "sl");
   tp    = ExtractNum(resp, "tp");
   return sig != "";
}

string ExtractStr(string json, string key) {
   string search = "\"" + key + "\":\"";
   int p = StringFind(json, search);
   if (p < 0) return "";
   p += StringLen(search);
   int e = StringFind(json, "\"", p);
   return e > p ? StringSubstr(json, p, e - p) : "";
}

double ExtractNum(string json, string key) {
   string search = "\"" + key + "\":";
   int p = StringFind(json, search);
   if (p < 0) return 0;
   p += StringLen(search);
   string sub = StringSubstr(json, p, 20);
   return StringToDouble(sub);
}

void ExecuteBuy(string sym, double lot, double entry, double sl, double tp) {
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   if (InpUseSLTP) {
      Trade.Buy(lot, sym, ask, sl, tp, "SupervisorAI_BUY");
   } else {
      Trade.Buy(lot, sym, ask, 0, 0, "SupervisorAI_BUY");
   }
   if (Trade.ResultRetcode() == TRADE_RETCODE_DONE)
      Print("[AutoTraderV2] ✅ BUY opened @ ", ask);
   else
      Print("[AutoTraderV2] ❌ BUY failed: ", Trade.ResultRetcodeDescription());
}

void ExecuteSell(string sym, double lot, double entry, double sl, double tp) {
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   if (InpUseSLTP) {
      Trade.Sell(lot, sym, bid, sl, tp, "SupervisorAI_SELL");
   } else {
      Trade.Sell(lot, sym, bid, 0, 0, "SupervisorAI_SELL");
   }
   if (Trade.ResultRetcode() == TRADE_RETCODE_DONE)
      Print("[AutoTraderV2] ✅ SELL opened @ ", bid);
   else
      Print("[AutoTraderV2] ❌ SELL failed: ", Trade.ResultRetcodeDescription());
}

void ManagePositions(string sym) {
   for (int i = PositionsTotal() - 1; i >= 0; i--) {
      if (!Pos.SelectByIndex(i)) continue;
      if (Pos.Magic() != InpMagicNumber) continue;
      if (Pos.Symbol() != sym) continue;

      double entry = Pos.PriceOpen();
      double sl    = Pos.StopLoss();
      double tp    = Pos.TakeProfit();
      double price = Pos.PriceCurrent();
      double r     = MathAbs(entry - sl);  // 1R distance
      if (r <= 0) continue;

      bool isBuy  = Pos.PositionType() == POSITION_TYPE_BUY;
      double pnlR = isBuy ? (price - entry) / r : (entry - price) / r;

      // Partial close at 1R
      if (InpPartialClose && pnlR >= 1.0 && Pos.Volume() > 0.01) {
         double closeVol = NormalizeDouble(Pos.Volume() * 0.5, 2);
         Trade.PositionClosePartial(Pos.Ticket(), closeVol);
         Print("[AutoTraderV2] Partial close 50% at 1R: ticket=", Pos.Ticket());
      }

      // Move to breakeven at 1R
      if (InpMoveToBreakEven && pnlR >= 1.0 && sl != entry) {
         double newSL = entry + (isBuy ? 2*_Point : -2*_Point);
         Trade.PositionModify(Pos.Ticket(), newSL, tp);
         Print("[AutoTraderV2] Breakeven set: ticket=", Pos.Ticket());
      }
   }
}

int CountMyPositions() {
   int count = 0;
   for (int i = 0; i < PositionsTotal(); i++) {
      if (Pos.SelectByIndex(i) && Pos.Magic() == InpMagicNumber) count++;
   }
   return count;
}

void OnDeinit(const int reason) {
   Print("[AutoTraderV2] EA stopped. Reason: ", reason);
}
