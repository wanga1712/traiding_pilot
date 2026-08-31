# Indicator formula spec

## SMA: mean(Close[t-n+1:t])
## EMA: recursive, seed = SMA(first n), alpha = 2/(n+1)
## WMA: linear weights 1..n on Close window

## Stochastic RAW_K = 100*(Close-LL_n)/(HH_n-LL_n); HH==LL → 50
## K = SMA(RAW_K, k_smooth); D = SMA(K, d_period)

## MACD = EMA_fast - EMA_slow; SIGNAL = EMA(MACD); HIST = MACD - SIGNAL