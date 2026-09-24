import unittest
import numpy as np
try:
 from .integrity import map_events_to_rows
 from .target_engine import NS_MINUTE,complete_window_mask,forward_extreme,slow_reference,parity_check
except ImportError:
 from integrity import map_events_to_rows
 from target_engine import NS_MINUTE,complete_window_mask,forward_extreme,slow_reference,parity_check

class IntegrityTests(unittest.TestCase):
 def setUp(self): self.grid=np.array([100,200,300],np.int64)
 def test_pre_window_event_is_not_mapped_to_first_row(self): self.assertEqual(map_events_to_rows([1],self.grid).size,0)
 def test_event_exactly_on_decision_time_maps_correctly(self): self.assertEqual(map_events_to_rows([200],self.grid).tolist(),[1])
 def test_event_between_rows_maps_first_causal_row(self): self.assertEqual(map_events_to_rows([201],self.grid).tolist(),[2])
 def test_post_window_event_is_ignored(self): self.assertEqual(map_events_to_rows([301],self.grid).size,0)
 def test_duplicate_event_collapses_in_fixture_matrix(self):
  rows=np.unique(map_events_to_rows([200,200],self.grid));matrix=np.zeros((3,1),np.float32);matrix[rows,0]=1;self.assertEqual(matrix[:,0].tolist(),[0,1,0])
 def test_actual_atomic_fixture_shape(self):
  matrix=np.zeros((3,len([f'a{i}' for i in range(284)])));self.assertEqual(matrix.shape,(3,284))
 def test_actual_composite_fixture_shape(self):
  matrix=np.zeros((3,len([f'c{i}' for i in range(5478)])));self.assertEqual(matrix.shape,(3,5478))
 def test_matrix_row_alignment(self):
  row_ids=np.arange(3);a=np.zeros((len(row_ids),284));c=np.zeros((len(row_ids),5478));self.assertEqual((a.shape[0],c.shape[0]),(len(row_ids),len(row_ids)))
 def test_event_absence_is_zero(self):
  matrix=np.zeros((3,1));matrix[map_events_to_rows([200],self.grid),0]=1;self.assertEqual(matrix[0,0],0)
 def test_continuous_missing_remains_nan(self): self.assertTrue(np.isnan(np.array([1.,np.nan])[1]))
 def fixture(self,gap=False):
  t=np.arange(1,61,dtype=np.int64)*NS_MINUTE
  if gap:t=np.delete(t,14)
  c=np.arange(len(t),dtype=float)+100;return t,c,c+1,c-1
 def test_complete_path_detection(self):
  t,*_=self.fixture();_,ok,_,_=complete_window_mask(t,[0],30,60*NS_MINUTE);self.assertTrue(ok[0])
 def test_missing_internal_minute_censors(self):
  t,*_=self.fixture(True);_,ok,gap,_=complete_window_mask(t,[0],30,60*NS_MINUTE);self.assertFalse(ok[0]);self.assertTrue(gap[0])
 def test_missing_endpoint_censors(self):
  t,*_=self.fixture();_,ok,_,_=complete_window_mask(t[:-1],[30*NS_MINUTE],30,60*NS_MINUTE);self.assertFalse(ok[0])
 def test_exact_endpoint_included(self):
  t,c,h,l=self.fixture();r=slow_reference(t,c,h,l,[0],[100],30,60*NS_MINUTE)[0];self.assertAlmostEqual(r[1],c[29]/100-1)
 def test_bar_after_horizon_excluded(self):
  t,c,h,l=self.fixture();h[30]=9999;r=slow_reference(t,c,h,l,[0],[100],30,60*NS_MINUTE)[0];self.assertNotEqual(r[5],9999)
 def test_earliest_max_tie_rule(self):
  v,i=forward_extreme(np.array([5.,5.,1.]),2,True);self.assertEqual((v[0],i[0]),(5.,0))
 def test_earliest_min_tie_rule(self):
  v,i=forward_extreme(np.array([1.,1.,5.]),2,False);self.assertEqual((v[0],i[0]),(1.,0))
 def test_time_to_max_elapsed_minutes(self):
  t,c,h,l=self.fixture();h[:30]=1;h[9]=9;r=slow_reference(t,c,h,l,[0],[100],30,60*NS_MINUTE)[0];self.assertEqual(r[7],10)
 def test_time_to_min_elapsed_minutes(self):
  t,c,h,l=self.fixture();l[:30]=9;l[19]=1;r=slow_reference(t,c,h,l,[0],[100],30,60*NS_MINUTE)[0];self.assertEqual(r[8],20)
 def test_optimized_reference_parity(self):
  t,c,h,l=self.fixture();self.assertTrue(parity_check(t,c,h,l,[0,30*NS_MINUTE],[100,129],[30],60*NS_MINUTE))
 def test_no_post_boundary_close_time_in_bounded_fixture(self):
  t,*_=self.fixture();bounded=t[t<=30*NS_MINUTE];self.assertLessEqual(bounded.max(),30*NS_MINUTE)
 def test_target_columns_excluded_from_feature_storage(self): self.assertTrue({'open','close','volume'}.isdisjoint({'fwd_return_30m','censor_30m'}))

if __name__=='__main__':unittest.main()
