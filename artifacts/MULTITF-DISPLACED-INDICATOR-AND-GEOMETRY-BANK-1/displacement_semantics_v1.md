# Displacement semantics

For positive forward display shift d: value calculated at source index i is displayed at index i+d. At decision index t: DISPLAY_ALIGNED_VALUE(t, d) = SOURCE_VALUE(t - d) provided SOURCE_VALUE was already AVAILABLE_AT <= decision_time(T). DISPLAYED_AT may differ from AVAILABLE_AT; display shift NEVER changes availability.
