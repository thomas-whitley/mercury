"""Whether a chore's staged diff weakens the repo's tests: a test that is
removed and not added back, a deleted test file, or a skip or xfail marker
added to a test file. Built from the Phase 1 eval, where 6 of 10 failures were
a green result that had dropped one of main's tests."""

import pytest

from app.test_guard import weakened_tests

ADD_TEST = """\
diff --git a/test_calc.py b/test_calc.py
--- a/test_calc.py
+++ b/test_calc.py
@@ -1,6 +1,9 @@
 import unittest
 from calc import add

 class AddTest(unittest.TestCase):
     def test_adds_two_numbers(self):
         self.assertEqual(add(2, 3), 5)
+
+    def test_divides(self):
+        self.assertEqual(divide(7, 2), 3.5)
"""

# What ollama did on divide (fixture PR #19): the class became bare functions.
REWRITTEN = """\
diff --git a/test_calc.py b/test_calc.py
--- a/test_calc.py
+++ b/test_calc.py
@@ -1,6 +1,7 @@
-import unittest
-from calc import add
-
-class AddTest(unittest.TestCase):
-    def test_adds_two_numbers(self):
-        self.assertEqual(add(2, 3), 5)
+from calc import divide
+
+def test_divide():
+    assert divide(7, 2) == 3.5
+
+def test_divide_by_zero():
+    pass
"""


def test_adding_a_test_beside_the_old_ones_is_fine():
    assert weakened_tests(ADD_TEST) == []


def test_a_test_that_disappears_is_named():
    assert weakened_tests(REWRITTEN) == ["test_calc.py: removed test_adds_two_numbers"]


def test_moving_a_test_within_the_file_is_not_a_removal():
    moved = ADD_TEST.replace(
        "+    def test_divides",
        "-    def test_adds_two_numbers(self):\n"
        "+    def test_adds_two_numbers(self):\n"
        "+    def test_divides",
    )
    assert weakened_tests(moved) == []


def test_a_change_outside_test_files_is_fine():
    diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
        "-def test_mode():\n+def test_mode_on():\n"
    )
    assert weakened_tests(diff) == []


@pytest.mark.parametrize(
    "line",
    [
        "+    @unittest.skip('later')",
        "+    @pytest.mark.skip",
        "+    @pytest.mark.xfail",
        "+        pytest.skip('flaky')",
        "+    @unittest.expectedFailure",
        "+  it.skip('adds', () => {",
        "+  xit('adds', () => {",
    ],
)
def test_a_skip_or_xfail_added_to_a_test_file_is_named(line):
    diff = ADD_TEST + line + "\n"
    assert weakened_tests(diff) == [f"test_calc.py: added a skip ({line[1:].strip()})"]


def test_a_skip_word_outside_a_test_file_is_ignored():
    diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,2 @@\n"
        " def add(a, b):\n+    skip = pytest.mark.skip\n"
    )
    assert weakened_tests(diff) == []


def test_a_deleted_test_file_is_named():
    diff = (
        "diff --git a/test_calc.py b/test_calc.py\ndeleted file mode 100644\n"
        "--- a/test_calc.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def test_add():\n-    pass\n"
    )
    assert weakened_tests(diff) == ["test_calc.py: deleted", "test_calc.py: removed test_add"]


def test_a_file_under_tests_counts_as_a_test_file():
    diff = (
        "diff --git a/tests/helpers.py b/tests/helpers.py\n--- a/tests/helpers.py\n"
        "+++ b/tests/helpers.py\n@@ -1 +0,0 @@\n-def test_shared_setup():\n"
    )
    assert weakened_tests(diff) == ["tests/helpers.py: removed test_shared_setup"]


def test_javascript_tests_count_by_their_names():
    diff = (
        "diff --git a/src/sum.test.ts b/src/sum.test.ts\n--- a/src/sum.test.ts\n"
        "+++ b/src/sum.test.ts\n@@ -1,3 +1,3 @@\n"
        "-test('adds two numbers', () => {\n+test('adds numbers', () => {\n"
    )
    assert weakened_tests(diff) == ["src/sum.test.ts: removed adds two numbers"]
