# WIP=OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1

STATUS=REVIEW

## Authority

- Previous WIP: `OSCILLATOR-PREDICTOR-REFERENCE-1` (CLOSED)
- Predictor authority commit: `6b1e34e4dffb469e0b9392c33d20e5689a2cdfe2`

## Goal

Historical information study for the fixed reference oscillator predictor. Not a trading strategy test.

## Frozen config

- DNO_PERIOD=7, PEAK_STRENGTH=2, LOOKBACK=100, SAMPLES=5, OB_OS_LEVEL_PERCENT=0.80
- TARGET_AGGREGATION=PROJECT_MEAN_CONFIRMED_EXTREMA_V1

## Data architecture (mandatory)

- **S7** canonical: `/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m`
- **S13** disposable cache: `/var/tmp/traiding_pilot_market_cache`
- Research code: `market_data/research_access.py` — SCP from S7 only
- **No direct exchange HTTP** on S13 in research paths
- Preflight: `python -m crypto_trading_bot.research_v2.oscillator_predictor_event_study.run_preflight`
- Study aborts if `READY_FOR_HISTORICAL_EVENT_STUDY=NO`

## Artifacts

`artifacts/OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1/`

## Governance

PARAMETER_OPTIMIZATION_PERFORMED=NO  
SIGNAL_COMBINATION_SEARCH_PERFORMED=NO  
TRADING_STRATEGY_PERFORMED=NO  
TRADING_PNL_PERFORMED=NO  
OOS_OPENED=NO
