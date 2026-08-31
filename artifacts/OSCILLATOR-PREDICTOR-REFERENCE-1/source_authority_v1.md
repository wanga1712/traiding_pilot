# Source authority v1

## CQG Oscillator (documented)

`OSC = MA1 - MA2`

Public CQG setup maps to DiNapoli non-proprietary Detrended Oscillator reference:

- MA1: period=1, type=SIMPLE, price=CLOSE
- MA2: period=7, type=SIMPLE, price=CLOSE

Project name: `DINAPOLI_DETRENDED_OSCILLATOR_REFERENCE_V1`  
Reference status: `DINAPOLI_NONPROPRIETARY_REFERENCE`

Formula: `DNO_t = Close_t - SMA_7(Close)_t`

## CQG Oscillator Predictor (public semantics only)

One-period-ahead price bands derived from oscillator targets.

Public parameters (CQG UI semantics):

- Period
- PeakStrength
- Lookback
- Samples
- OB/OS Level (%)
- Custom OB / Custom OS

## Project reconstruction (NOT proprietary exact)

`PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_V1`

Target aggregation: `PROJECT_MEAN_CONFIRMED_EXTREMA_V1`

```
MEAN_OB = mean(selected positive confirmed peaks)
MEAN_OS = mean(selected negative confirmed troughs)
TARGET_OB = OB_OS_LEVEL_PERCENT * MEAN_OB
TARGET_OS = OB_OS_LEVEL_PERCENT * MEAN_OS
```

Peak confirmation: `PEAK_AVAILABLE_AT = extremum_index + PeakStrength`

Segment policy: `PREDICTOR_EXTREMA_CROSS_GAP=NO`

## Separation of authorities

| Component | Status |
|---|---|
| DNO reference | Documented non-proprietary |
| Oscillator predictor bands | PROJECT_RECONSTRUCTION |
| INVERSE_PREDICTOR_ENGINE_V1 | Separate engine (DMA/Stoch/MACD) |
| DiNapoli Preferred Stoch inverse | NOT_IMPLEMENTED in engine |
| DiNapoli alpha MACD inverse | NOT_IMPLEMENTED in engine |

No proprietary equation recovery is claimed.
