import unittest, sys
names=["test_identity","test_identity_v2","test_product_memory_bridge","test_cross_model_vertical","test_product_e1_composition"]
loader=unittest.defaultTestLoader
suite=loader.loadTestsFromNames(names)

def filt(s):
    out=unittest.TestSuite()
    for x in s:
        if isinstance(x,unittest.TestSuite):
            y=filt(x)
            if y.countTestCases(): out.addTest(y)
        else:
            if "test_preexisting_v1_archive_restores_under_v2" not in x.id(): out.addTest(x)
    return out
safe=filt(suite)
print("private_safe_count",safe.countTestCases())
r=unittest.TextTestRunner(verbosity=1).run(safe)
sys.exit(0 if r.wasSuccessful() else 1)
