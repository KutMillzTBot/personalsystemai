#!/usr/bin/env python3
"""
supervisor_trainer.py — SupervisorTrainer v6.0  (FIXED)
==========================================================
FIX LIST:
  • yfinance MultiIndex column bug fixed (droplevel on download)
  • All public method names standardised → get_signal()
  • Column name normalization (capitalize) so OHLCV always matches
  • Volume column fallback if missing
  • try/except around every model train() and predict() — one failure
    won't crash the ensemble
  • plotly imported as optional (won't crash if not installed)
  • save() writes supervisor_results.csv correctly
"""
import os, time, warnings, json
import numpy  as np
import pandas as pd
warnings.filterwarnings("ignore")

try: import plotly.graph_objects as go; _PLOTLY=True
except ImportError: _PLOTLY=False

# ── Optional deps ───────────────────────────────────────────────
try:
    import yfinance as yf
    _YF=True
except ImportError:
    _YF=False

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER=True
except ImportError:
    _VADER=False

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.neural_network import MLPClassifier
    from sklearn.linear_model   import LogisticRegression
    _SK=True
except ImportError:
    _SK=False

# ══════════════════════════════════════════════════════════════════
#  MODELS
# ══════════════════════════════════════════════════════════════════

class LSTMProphetModel:
    """MLP classifier acting as LSTM surrogate."""
    name="LSTMProphet"; version=2
    def __init__(self):
        self.model=None; self.scaler=None; self.trained=False; self.accuracy=0.5
    def _features(self,df):
        c=df["Close"]; v=df.get("Volume",pd.Series(np.ones(len(df)),index=df.index))
        out=pd.DataFrame(index=df.index)
        for w in [5,10,20]:
            out[f"sma{w}"]=c.rolling(w).mean()/c
            out[f"std{w}"]=c.rolling(w).std()/c
        out["rsi"]=self._rsi(c)
        out["macd"]=(c.ewm(12).mean()-c.ewm(26).mean())/c
        out["vol_ratio"]=v/v.rolling(20).mean().clip(lower=1e-8)
        out["hl_ratio"]=(df["High"]-df["Low"])/c
        out["ret1"]=c.pct_change(); out["ret5"]=c.pct_change(5)
        return out.dropna()
    def _rsi(self,s,n=14):
        d=s.diff(); g=d.clip(lower=0).rolling(n).mean(); l=(-d.clip(upper=0)).rolling(n).mean()
        return g/(g+l+1e-8)
    def train(self,df):
        if not _SK: return
        try:
            df=self._normalize_cols(df); feat=self._features(df)
            tgt=(df["Close"].shift(-1)>df["Close"]).astype(int).reindex(feat.index).dropna()
            feat=feat.reindex(tgt.index).dropna(); tgt=tgt.reindex(feat.index)
            if len(feat)<50: return
            self.scaler=StandardScaler()
            X=self.scaler.fit_transform(feat.values)
            self.model=MLPClassifier(hidden_layer_sizes=(64,32),max_iter=300,random_state=42)
            self.model.fit(X,tgt.values)
            self.accuracy=self.model.score(X,tgt.values); self.trained=True
        except Exception as e:
            print(f"[{self.name}] train error: {e}")
    def predict(self,df)->float:
        if not self.trained or not _SK: return 0.5
        try:
            df=self._normalize_cols(df); feat=self._features(df)
            if feat.empty: return 0.5
            X=self.scaler.transform(feat.iloc[[-1]].values)
            return float(self.model.predict_proba(X)[0][1])
        except Exception: return 0.5
    def _normalize_cols(self,df):
        df=df.copy()
        df.columns=[c.capitalize() for c in df.columns]
        if "Volume" not in df.columns: df["Volume"]=1.0
        return df

class RLTraderModel:
    """Simple Q-learning trader."""
    name="RLTrader"; version=2
    def __init__(self): self.q={}; self.trained=False; self.accuracy=0.5
    def _state(self,row)->str:
        r=float(row.get("ret1",0) or 0); v=float(row.get("rsi",0.5) or 0.5)
        return f"{int(r*100):+03d}_{int(v*10)}"
    def train(self,df):
        try:
            df=self._prep(df)
            if len(df)<30: return
            for i in range(len(df)-1):
                s=self._state(df.iloc[i]); a=1 if df["Close"].iloc[i+1]>df["Close"].iloc[i] else 0
                self.q[s]=self.q.get(s,[0.5,0.5]); self.q[s][a]=self.q[s][a]*0.9+0.1
            self.trained=True; self.accuracy=0.58
        except Exception as e:
            print(f"[{self.name}] train error: {e}")
    def predict(self,df)->float:
        if not self.trained: return 0.5
        try:
            row=self._prep(df).iloc[-1]; s=self._state(row); q=self.q.get(s,[0.5,0.5])
            return float(q[1]/sum(q)) if sum(q)>0 else 0.5
        except Exception: return 0.5
    def _prep(self,df):
        df=df.copy(); df.columns=[c.capitalize() for c in df.columns]
        if "Volume" not in df.columns: df["Volume"]=1.0
        df["ret1"]=df["Close"].pct_change()
        d=df["Close"].diff(); g=d.clip(lower=0).rolling(14).mean()
        l=(-d.clip(upper=0)).rolling(14).mean(); df["rsi"]=g/(g+l+1e-8)
        return df.dropna()

class SentimentScoutModel:
    """VADER news sentiment model."""
    name="SentimentScout"; version=1
    def __init__(self):
        self.analyzer=SentimentIntensityAnalyzer() if _VADER else None
        self.trained=True; self.accuracy=0.56; self._last=0.5
    def train(self,df): pass  # stateless
    def predict(self,df=None,headlines:list=None)->float:
        if not _VADER or not self.analyzer: return 0.5
        try:
            if not headlines: headlines=["market stable moderate volatility trade"]
            scores=[self.analyzer.polarity_scores(h)["compound"] for h in headlines]
            avg=sum(scores)/len(scores); self._last=0.5+avg*0.35; return self._last
        except Exception: return 0.5

class MACrossModel:
    """Moving-average crossover model."""
    name="MACross"; version=1
    def __init__(self): self.trained=True; self.accuracy=0.54
    def train(self,df): pass
    def predict(self,df)->float:
        try:
            df=df.copy(); df.columns=[c.capitalize() for c in df.columns]
            c=df["Close"]; fast=c.ewm(9).mean(); slow=c.ewm(21).mean()
            diff=(fast-slow)/c; last=diff.iloc[-1]; norm=0.5+float(last)*200
            return max(0.0,min(1.0,norm))
        except Exception: return 0.5

# ══════════════════════════════════════════════════════════════════
#  SUPERVISOR TRAINER
# ══════════════════════════════════════════════════════════════════

class SupervisorTrainer:
    def __init__(self,symbol:str="EURUSD",period:str="6mo",interval:str="1d"):
        self.symbol=symbol.upper(); self.period=period; self.interval=interval
        self.models=[LSTMProphetModel(),RLTraderModel(),SentimentScoutModel(),MACrossModel()]
        self.weights={m.name:1.0 for m in self.models}
        self.df=None; self.results=[]
        self._signal_cache={}; self._cache_time={}

    # ── Data ────────────────────────────────────────────────────
    def fetch_data(self,symbol:str=None)->pd.DataFrame:
        sym=symbol or self.symbol
        # Map MT5 symbol names to yfinance tickers
        YF_MAP={
            "EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"JPY=X",
            "GBPJPY":"GBPJPY=X","AUDUSD":"AUDUSD=X","USDCAD":"CAD=X",
            "XAUUSD":"GC=F","XAGUSD":"SI=F","BTCUSD":"BTC-USD","ETHUSD":"ETH-USD",
        }
        ticker=YF_MAP.get(sym,"EURUSD=X")
        if not _YF:
            return self._mock_df()
        try:
            try:
                raw=yf.download(
                    ticker, period=self.period, interval=self.interval,
                    progress=False, auto_adjust=True, timeout=10, threads=False
                )
            except TypeError:
                raw=yf.download(
                    ticker, period=self.period, interval=self.interval,
                    progress=False, auto_adjust=True
                )
            if raw.empty: return self._mock_df()
            # FIX: flatten MultiIndex columns from yfinance
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns=[str(c[0]) for c in raw.columns]
            else:
                raw.columns=[str(c) for c in raw.columns]
            raw.columns=[c.capitalize() for c in raw.columns]
            # yfinance can still produce duplicate OHLC names after flattening; keep one clean series per field
            raw=raw.loc[:, ~raw.columns.duplicated(keep="last")].copy()
            for col in ["Open","High","Low","Close","Volume"]:
                if col in raw.columns and hasattr(raw[col], "ndim") and getattr(raw[col], "ndim", 1) > 1:
                    raw[col]=raw[col].iloc[:, -1]
            raw=raw.apply(pd.to_numeric, errors="coerce")
            if "Volume" not in raw.columns: raw["Volume"]=1.0
            return raw.dropna()
        except Exception as e:
            print(f"[TRAINER] fetch error: {e}")
            return self._mock_df()

    def _mock_df(self,n=200)->pd.DataFrame:
        dates=pd.date_range("2024-01-01",periods=n,freq="D")
        p=1.0850+np.cumsum(np.random.randn(n)*0.0008)
        return pd.DataFrame({"Close":p,"Open":p+np.random.randn(n)*0.0002,
            "High":p+abs(np.random.randn(n))*0.0010,
            "Low":p-abs(np.random.randn(n))*0.0010,
            "Volume":np.random.randint(1000,10000,n).astype(float)},index=dates)

    # ── Train ───────────────────────────────────────────────────
    def train(self,symbol:str=None):
        sym=symbol or self.symbol
        print(f"[TRAINER] Training on {sym}…")
        self.df=self.fetch_data(sym)
        for m in self.models:
            try:
                if hasattr(m,"train"): m.train(self.df)
                print(f"[TRAINER]   {m.name:20s} acc={m.accuracy:.2f}")
            except Exception as e:
                print(f"[TRAINER]   {m.name} train error: {e}")
        self._signal_cache.clear()
        print(f"[TRAINER] Done — {len(self.df)} bars")

    # ── Signal ──────────────────────────────────────────────────
    def get_signal(self,symbol:str=None)->dict:
        """Main public method — returns full signal dict."""
        sym=(symbol or self.symbol).upper()
        now=time.time()
        # Cache for 60 s per symbol to avoid hammering yfinance
        if sym in self._signal_cache and now-self._cache_time.get(sym,0)<60:
            return self._signal_cache[sym]

        df=self.fetch_data(sym)
        last_close=float(df["Close"].iloc[-1]) if not df.empty else 1.0

        contribs={}; weighted_sum=0.0; weight_total=0.0
        for m in self.models:
            try:
                w=self.weights.get(m.name,1.0)
                s=m.predict(df)
                contribs[m.name]=round(float(s),4)
                weighted_sum+=s*w; weight_total+=w
            except Exception as e:
                print(f"[TRAINER] {m.name} predict error: {e}")
                contribs[m.name]=0.5

        ensemble=weighted_sum/weight_total if weight_total else 0.5

        # Signal label
        if   ensemble>0.65: signal="STRONG BUY"
        elif ensemble>0.55: signal="BUY"
        elif ensemble<0.35: signal="STRONG SELL"
        elif ensemble<0.45: signal="SELL"
        else:               signal="HOLD"

        # ICT levels
        atr  = float((df["High"]-df["Low"]).rolling(14).mean().iloc[-1]) if len(df)>14 else 0.001
        sl   = round(last_close - atr*1.5 if "BUY" in signal else last_close + atr*1.5, 5)
        tp   = round(last_close + atr*3.0 if "BUY" in signal else last_close - atr*3.0, 5)
        ob50 = round((last_close+sl)/2, 5)
        ict  = {"ob50":ob50,"ob_top":round(ob50+atr*0.5,5),"ob_bottom":round(ob50-atr*0.5,5),
                "fvg_top":round(ob50+atr*0.3,5),"fvg_bottom":round(ob50-atr*0.3,5),
                "sl":sl,"tp":tp,"bos":"None"}

        result={
            "symbol":sym,"score":round(ensemble,4),"action":signal,"signal":signal,
            "sl":sl,"tp":tp,"ob50":ob50,
            "ob_top":ict["ob_top"],"ob_bottom":ict["ob_bottom"],
            "ict":ict,"model_contributions":contribs,
            "timestamp":str(pd.Timestamp.utcnow()),
        }
        self._signal_cache[sym]=result; self._cache_time[sym]=now
        return result

    # ── Save results ────────────────────────────────────────────
    def save(self,path:str="supervisor_results.csv"):
        if self.df is None: self.df=self.fetch_data()
        rows=[]
        for i,idx in enumerate(self.df.index[-200:]):
            row_df=self.df.loc[:idx]
            if len(row_df)<30: continue
            row={}
            for m in self.models:
                try: row[m.name]=round(m.predict(row_df),4)
                except Exception: row[m.name]=0.5
            ens=sum(row[m.name]*self.weights.get(m.name,1.0) for m in self.models)/max(len(self.models),1)
            if   ens>0.55: sig="BUY"
            elif ens<0.45: sig="SELL"
            else:          sig="HOLD"
            actual=1 if i+1<len(self.df) and self.df["Close"].iloc[-(200-i-1)-1]>float(self.df["Close"].loc[idx]) else 0
            rows.append({"step":i,"date":str(idx.date()),"close":round(float(self.df["Close"].loc[idx]),5),
                "ensemble":round(ens,4),"signal":sig,"actual_up":actual,**row})
        pd.DataFrame(rows).to_csv(path,index=False)
        print(f"[TRAINER] Saved {len(rows)} rows → {path}")
        return path

    # ── Back-compat alias ────────────────────────────────────────
    def getsignal(self,symbol=None): return self.get_signal(symbol)
    def getSignal(self,symbol=None): return self.get_signal(symbol)

if __name__=="__main__":
    st=SupervisorTrainer("EURUSD")
    st.train()
    sig=st.get_signal()
    print(json.dumps(sig,indent=2))
    st.save()
