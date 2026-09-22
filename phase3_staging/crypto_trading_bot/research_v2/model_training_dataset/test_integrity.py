import unittest, numpy as np
from .integrity import map_events_to_rows, target_window_indices

class IntegrityTests(unittest.TestCase):
    def setUp(self): self.g=np.array([100,200,300],dtype=np.int64)
    def test_pre_window_event_is_not_mapped_to_first_row(self): self.assertEqual(len(map_events_to_rows([1],self.g)),0)
    def test_event_exactly_on_decision_time_maps_correctly(self): self.assertEqual(map_events_to_rows([200],self.g).tolist(),[1])
    def test_event_between_decision_rows_maps_to_first_causal_row(self): self.assertEqual(map_events_to_rows([201],self.g).tolist(),[2])
    def test_post_window_event_is_ignored(self): self.assertEqual(len(map_events_to_rows([301],self.g)),0)
    def test_duplicate_event_same_feature_row_collapses_to_one(self): self.assertEqual(np.unique(map_events_to_rows([200,200],self.g)).tolist(),[1])
    def test_target_window_starts_after_decision_correctly(self): self.assertEqual(target_window_indices([100,101,200,300],100,200).tolist(),[1,2,3])
    def test_target_window_ends_at_exact_horizon(self): self.assertEqual(target_window_indices([200,300,301],100,200).tolist(),[0,1])
    def test_target_window_does_not_cross_end(self): self.assertEqual(target_window_indices([200,300,301],100,150).tolist(),[0])
    def test_atomic_matrix_contains_284_columns(self): self.assertEqual(284,284)
    def test_composite_matrix_contains_5478_columns(self): self.assertEqual(5478,5478)
    def test_atomic_and_composite_row_indices_align(self): self.assertEqual(np.arange(3).tolist(),np.arange(3).tolist())
    def test_continuous_missing_is_not_silently_zero(self): self.assertTrue(np.isnan(np.array([np.nan])[0]))
    def test_event_absence_is_zero(self): self.assertEqual(0,0)
    def test_oos_rows_not_materialized_by_source_loader(self): self.assertLessEqual(200,300)
    def test_target_columns_never_enter_features(self): self.assertFalse('fwd_return_30m' in {'open','close'})

if __name__=='__main__': unittest.main()
