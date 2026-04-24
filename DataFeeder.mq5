//+------------------------------------------------------------------+
//|  DataFeeder.mq5                                                |
//|  Sends historical + live OHLCV bars to Python bridge server    |
//|  so models can train on MT5's own data simultaneously          |
//+------------------------------------------------------------------+
#property copyright "SupervisorTrainer DataFeeder"
#property version   "1.00"
#property strict

//── Inputs ───────────────────────────────────────────────────
input string   ServerURL      = "http://127.0.0.1:5050";
input string   FeedSymbol     = "";          // blank = chart symbol
input ENUM_TIMEFRAMES FeedTF  = PERIOD_H1;  // timeframe to send
input datetime StartDate      = 0;          // 0 = auto (2 years back)
input datetime EndDate        = 0;          // 0 = now
input int      BatchSize      = 200;        // bars per HTTP batch
input bool     FeedOnNewBar   = true;       // auto-feed each new bar
input bool     PrintProgress  = true;

string g_symbol;
datetime g_lastBar = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = (FeedSymbol == "") ? Symbol() : FeedSymbol;
   Print("[DataFeeder] Symbol=", g_symbol,
         " TF=", EnumToString(FeedTF));
   // Send historical data immediately on attach
   EventSetTimer(3);
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ EventKillTimer(); }

void RefreshFeedSymbol()
{
   if(FeedSymbol != "") return; // manual symbol override is enabled
   string chartSym = Symbol();
   if(chartSym == g_symbol) return;
   g_symbol = chartSym;
   Print("[DataFeeder] Symbol auto-switched to ", g_symbol);
}

void OnTimer()
{
   RefreshFeedSymbol();
   static bool historySent = false;
   if(!historySent)
   {
      SendHistoricalBatch();
      historySent = true;
      EventKillTimer();
      if(FeedOnNewBar) EventSetTimer(PeriodSeconds(FeedTF));
   }
   else if(FeedOnNewBar)
   {
      // Check for new bar
      datetime cur = iTime(g_symbol, FeedTF, 0);
      if(cur != g_lastBar)
      {
         g_lastBar = cur;
         SendLatestBars(5);  // send last 5 bars on each new candle
      }
   }
}

void OnTick()
{
   RefreshFeedSymbol();
   if(FeedOnNewBar)
   {
      datetime cur = iTime(g_symbol, FeedTF, 0);
      if(cur != g_lastBar){ g_lastBar = cur; SendLatestBars(5); }
   }
}

//+------------------------------------------------------------------+
//  Send full historical range in batches
//+------------------------------------------------------------------+
void SendHistoricalBatch()
{
   datetime t_start = (StartDate == 0) ? TimeCurrent() - 63072000 : StartDate; // 2 years
   datetime t_end   = (EndDate   == 0) ? TimeCurrent()             : EndDate;

   Print("[DataFeeder] Fetching history: ",
         TimeToString(t_start), " → ", TimeToString(t_end));

   MqlRates rates[];
   int total = CopyRates(g_symbol, FeedTF, t_start, t_end, rates);
   if(total <= 0)
   {
      Print("[DataFeeder] ❌ No bars retrieved. Error: ", GetLastError());
      return;
   }
   Print("[DataFeeder] Retrieved ", total, " bars — sending in batches of ", BatchSize);

   int sent = 0;
   for(int i = 0; i < total; i += BatchSize)
   {
      int end = MathMin(i + BatchSize, total);
      string json = BuildJSON(rates, i, end, g_symbol, EnumToString(FeedTF));
      bool ok = PostJSON(ServerURL + "/ingest", json);
      sent += (end - i);
      if(PrintProgress)
         Print("[DataFeeder] Sent ", sent, "/", total, " bars | ",
               ok ? "✅" : "❌");
   }
   Print("[DataFeeder] ✅ Historical feed complete — ", sent, " bars sent");
}

//+------------------------------------------------------------------+
//  Send N most recent bars (called on new bar)
//+------------------------------------------------------------------+
void SendLatestBars(int n)
{
   MqlRates rates[];
   int got = CopyRates(g_symbol, FeedTF, 0, n, rates);
   if(got <= 0) return;
   string json = BuildJSON(rates, 0, got, g_symbol, EnumToString(FeedTF));
   PostJSON(ServerURL + "/ingest", json);
   if(PrintProgress)
      Print("[DataFeeder] 📡 Live bar sent: ",
            TimeToString(rates[got-1].time));
}

//+------------------------------------------------------------------+
//  Build JSON array of OHLCV bars
//+------------------------------------------------------------------+
string BuildJSON(MqlRates &rates[], int from, int to,
                 string sym, string tf)
{
   string j = "{\"symbol\":\"" + sym + "\",\"timeframe\":\"" + tf + "\",\"bars\":[";
   for(int i = from; i < to; i++)
   {
      if(i > from) j += ",";
      j += "{\"t\":"  + IntegerToString((long)rates[i].time)
         + ",\"o\":"  + DoubleToString(rates[i].open,  5)
         + ",\"h\":"  + DoubleToString(rates[i].high,  5)
         + ",\"l\":"  + DoubleToString(rates[i].low,   5)
         + ",\"c\":"  + DoubleToString(rates[i].close, 5)
         + ",\"v\":"  + IntegerToString(rates[i].tick_volume)
         + "}";
   }
   j += "]}";
   return j;
}

//+------------------------------------------------------------------+
//  HTTP POST helper
//+------------------------------------------------------------------+
bool PostJSON(string url, string body)
{
   uchar  post[], resp[];
   string reqH = "Content-Type: application/json\r\n";
   string resH = "";
   StringToCharArray(body, post, 0, StringLen(body));
   int rc = WebRequest("POST", url, reqH, 8000, post, resp, resH);
   return (rc != -1);
}
//+------------------------------------------------------------------+
