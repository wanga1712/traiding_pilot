# REVERSAL_SIGNAL_EVENT_STUDY_V1

WIP=REVERSAL-SIGNAL-EVENT-STUDY-1
STUDY_VERSION=REVERSAL_SIGNAL_EVENT_STUDY_V1
OOS_OPENED=NO

## Matching rules

See `match.py` docstring. Causal ledgers contain no true-C fields.
Label matches are retrospective only.

## Partitions

DISCOVERY: (datetime.datetime(2019, 5, 12, 0, 0, tzinfo=datetime.timezone.utc), datetime.datetime(2022, 6, 10, 4, 36, tzinfo=datetime.timezone.utc))
VALIDATION: (datetime.datetime(2022, 6, 10, 4, 36, tzinfo=datetime.timezone.utc), datetime.datetime(2023, 6, 20, 6, 8, tzinfo=datetime.timezone.utc))
OOS: locked (not used)

## Note

Pooled ALL source_wave_tf metrics are unweighted event averages; 1H is denser — prefer stratified boards and TF-balanced family comparisons.

## Verdict

WHEN_SIGNAL_WEAK
