# GATE 3 - GPU Models

STATUS=PASS

## New models

| Model | Target | CatBoost task | GPU confirmed | SHA256 |
|---|---|---|---|---|
| `entry_direction_gpu_v1` | SKIP / LONG / SHORT | `GPU` | YES | `df5c3eaefaab1dbdf47441e765886e882e24f2373af6dae2df86977e7b49bc86` |
| `entry_risk_gpu_v1` | 24h adverse/favorable excursion | `GPU` | YES | `ab2955f0efd89565d3833402cdb8425c877c8ed4bac9d34246819cbb405fd45d` |
| `position_management_gpu_v1` | HOLD/hedge/close hedge/average/reduce/exit | `GPU` | YES | `3da5206e4099ae0edec19c0485731c33dc0af20bf1848820e714bce62f9fada0` |

Peak observed VRAM for each GPU training job was approximately 5,471-5,473
MiB on the 6,144 MiB GTX 1660 SUPER.

## Selection metrics

| Metric | Value |
|---|---:|
| Entry accuracy | 49.91% |
| Entry logloss | 0.92180 |
| Entry mean confidence | 57.35% |
| Risk MAE | 0.02369 |
| Management accuracy | 45.89% |
| Management logloss | 1.10440 |
| Entry selected features | 200 |
| Management selected features | 201 |

The entry model has no material directional edge. High-confidence bins do not
improve accuracy, including the 0.70-0.80 confidence bin at 43.61% accuracy.
The management model also underperforms its six-class prior. A negative result
must be preserved.

The management training labels contain five observed action classes; no
training example selected `CLOSE_HEDGE`. The class remains available in the
policy contract but its learned probability is not empirically supported.

All model files are committed beside this report. The training log includes
CatBoost GPU iterations and warnings. Large prediction tables remain on S13.
