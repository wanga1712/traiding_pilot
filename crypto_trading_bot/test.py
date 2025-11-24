import yfinance as yf

data = yf.download("BTC-USD", start="2023-01-01", end="2023-12-01")
print(data)
