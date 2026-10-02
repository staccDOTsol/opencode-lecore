import unittest
from retry import retry

class RetryTests(unittest.TestCase):
    def test_retries_and_backs_off(self):
        count=[0]; waits=[]
        def task():
            count[0]+=1
            if count[0]<3: raise OSError("transient")
            return "done"
        self.assertEqual(retry(task, attempts=4, delay=0.25, sleep=waits.append), "done")
        self.assertEqual(count[0],3)
        self.assertEqual(waits,[0.25,0.5])
    def test_final_error_is_same_instance_no_final_sleep(self):
        error=OSError("still down"); waits=[]; count=[0]
        def task():
            count[0]+=1; raise error
        with self.assertRaises(OSError) as got: retry(task, attempts=3, delay=2, sleep=waits.append)
        self.assertIs(got.exception,error); self.assertEqual(count[0],3); self.assertEqual(waits,[2,4])
    def test_non_transient_error_is_not_retried(self):
        error=ValueError("bad argument"); count=[0]; waits=[]
        def task():
            count[0]+=1; raise error
        with self.assertRaises(ValueError) as got: retry(task, attempts=5, sleep=waits.append)
        self.assertIs(got.exception,error); self.assertEqual(count[0],1); self.assertEqual(waits,[])
    def test_zero_delay_can_use_zero_backoff(self):
        attempts=[False,True]; waits=[]
        def task():
            if not attempts.pop(0): raise OSError()
            return 42
        self.assertEqual(retry(task, delay=0, sleep=waits.append),42)
        self.assertTrue(all(x==0 for x in waits))
    def test_attempts_positive(self):
        for n in (0,-1):
            with self.assertRaises(ValueError): retry(lambda:None, attempts=n)
    def test_no_sleep_after_immediate_success(self):
        waits=[]; self.assertEqual(retry(lambda:None,sleep=waits.append),None); self.assertEqual(waits,[])

if __name__=="__main__": unittest.main()
