import requests
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

def fetch_klines(symbol, limit=150):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit={limit}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume'
    ])
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    return df

def rma(s, length):
    return s.ewm(alpha=1/length, adjust=False).mean()

def sma(s, length):
    return s.rolling(window=length).mean()

def calculate_strategy(df):
    high = df['high']
    low = df['low']
    close = df['close']
    
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    
    atr100 = rma(tr, 100)
    atr1 = rma(tr, 1) 
    
    amplitude = 2
    channelDeviation = 2
    atr2 = atr100 / 2
    dev = channelDeviation * atr2
    
    highma = sma(high, amplitude)
    lowma = sma(low, amplitude)
    
    length_ce = 1
    mult_ce = 1.85
    atr_ce = mult_ce * atr1
    
    highest_ce = high.rolling(window=length_ce).max()
    lowest_ce = low.rolling(window=length_ce).min()
    
    n = len(df)
    trend = np.zeros(n, dtype=int)
    nextTrend = np.zeros(n, dtype=int)
    maxLowPrice = np.zeros(n, dtype=float)
    minHighPrice = np.zeros(n, dtype=float)
    up = np.zeros(n, dtype=float)
    down = np.zeros(n, dtype=float)
    
    longStop = np.zeros(n, dtype=float)
    shortStop = np.zeros(n, dtype=float)
    dir_ce = np.ones(n, dtype=int)
    
    for i in range(1, n):
        lowPrice = low.iloc[max(0, i - amplitude + 1): i + 1].min()
        highPrice = high.iloc[max(0, i - amplitude + 1): i + 1].max()
        
        trend[i] = trend[i-1]
        nextTrend[i] = nextTrend[i-1]
        maxLowPrice[i] = maxLowPrice[i-1]
        minHighPrice[i] = minHighPrice[i-1]
        up[i] = up[i-1]
        down[i] = down[i-1]
        
        if nextTrend[i] == 1:
            maxLowPrice[i] = max(lowPrice, maxLowPrice[i])
            if highma.iloc[i] < maxLowPrice[i] and close.iloc[i] < low.iloc[i-1]:
                trend[i] = 1
                nextTrend[i] = 0
                minHighPrice[i] = highPrice
        else:
            minHighPrice[i] = min(highPrice, minHighPrice[i])
            if lowma.iloc[i] > minHighPrice[i] and close.iloc[i] > high.iloc[i-1]:
                trend[i] = 0
                nextTrend[i] = 1
                maxLowPrice[i] = lowPrice
                
        if trend[i] == 0:
            if trend[i-1] != 0:
                up[i] = down[i-1]
            else:
                up[i] = max(maxLowPrice[i], up[i-1])
        else:
            if trend[i-1] != 1:
                down[i] = up[i-1]
            else:
                down[i] = min(minHighPrice[i], down[i-1])
                
        curr_longStop = highest_ce.iloc[i] - atr_ce.iloc[i]
        curr_shortStop = lowest_ce.iloc[i] + atr_ce.iloc[i]
        
        longStopPrev = longStop[i-1]
        if pd.isna(longStopPrev) or longStopPrev == 0: longStopPrev = curr_longStop
        longStop[i] = max(curr_longStop, longStopPrev) if close.iloc[i-1] > longStopPrev else curr_longStop
        
        shortStopPrev = shortStop[i-1]
        if pd.isna(shortStopPrev) or shortStopPrev == 0: shortStopPrev = curr_shortStop
        shortStop[i] = min(curr_shortStop, shortStopPrev) if close.iloc[i-1] < shortStopPrev else curr_shortStop
        
        dir_ce[i] = dir_ce[i-1]
        if close.iloc[i] > shortStopPrev:
            dir_ce[i] = 1
        elif close.iloc[i] < longStopPrev:
            dir_ce[i] = -1
            
    df['trend'] = trend
    df['dir_ce'] = dir_ce
    df['atrHigh'] = np.where(trend == 0, up + dev, down + dev)
    df['atrLow'] = np.where(trend == 0, up - dev, down - dev)
    
    df['buySignalCE'] = (df['dir_ce'] == 1) & (df['dir_ce'].shift(1) == -1)
    df['sellSignalCE'] = (df['dir_ce'] == -1) & (df['dir_ce'].shift(1) == 1)
    
    sureBuy_recent = df['buySignalCE'] | df['buySignalCE'].shift(1) | df['buySignalCE'].shift(2)
    sureSell_recent = df['sellSignalCE'] | df['sellSignalCE'].shift(1) | df['sellSignalCE'].shift(2)
    
    df['sureBuyInTrend'] = (df['trend'] == 0) & sureBuy_recent
    df['sureSellInTrend'] = (df['trend'] == 1) & sureSell_recent
    
    df['buy_alert'] = df['sureBuyInTrend'] & (~df['sureBuyInTrend'].shift(1).fillna(False))
    df['sell_alert'] = df['sureSellInTrend'] & (~df['sureSellInTrend'].shift(1).fillna(False))
    
    df['buyTarget'] = df['close'] + (df['close'] - df['atrLow'])
    df['sellTarget'] = df['close'] - (df['atrHigh'] - df['close'])
    
    return df

def analyze_custom_strategy(symbol):
    df = fetch_klines(symbol, limit=150)
    df = calculate_strategy(df)
    last_row = df.iloc[-1]
    
    return {
        'buy': bool(last_row['buy_alert']),
        'sell': bool(last_row['sell_alert']),
        'close': float(last_row['close']),
        'atrLow': float(last_row['atrLow']),
        'atrHigh': float(last_row['atrHigh']),
        'buyTarget': float(last_row['buyTarget']),
        'sellTarget': float(last_row['sellTarget'])
    }
