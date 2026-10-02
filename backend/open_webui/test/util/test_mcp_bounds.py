"""The three result bounds, their values, and the notice on a shortened result.

Every shortened result, of any type, ends with a notice stating that it was shortened.
"""

import json
import unittest

from open_webui.mcp.tools import _reports_failure
from open_webui.mcp.bounds import (
    LONGEST_MEASURED_LISTING_ENTRY_BYTES,
    MAX_LISTING_ENTRIES,
    MAX_RESULT_BYTES,
    MAX_RUN_OUTPUT_CHARACTERS,
    within_bounds,
    within_run_output_bound,
)


class ValuesTest(unittest.TestCase):
    def test_all_three_have_stated_values(self):
        for bound in (
            MAX_RESULT_BYTES,
            MAX_RUN_OUTPUT_CHARACTERS,
            MAX_LISTING_ENTRIES,
        ):
            self.assertIsInstance(bound, int)
            self.assertGreater(bound, 0)

    def test_the_result_bound_is_the_measured_one(self):
        # 128 KiB, about 32,000 tokens at roughly four bytes each.
        self.assertEqual(MAX_RESULT_BYTES, 131_072)

    def test_run_output_is_bounded_far_below_a_whole_result(self):
        # A skill that prints a data file to stdout instead of writing it is cut here.
        self.assertLess(MAX_RUN_OUTPUT_CHARACTERS, MAX_RESULT_BYTES // 4)

    def test_the_listing_bound_is_derived_from_the_result_bound(self):
        # This many entries at the longest measured entry size fit inside the result bound.
        worst_case = MAX_LISTING_ENTRIES * LONGEST_MEASURED_LISTING_ENTRY_BYTES
        self.assertLess(worst_case, MAX_RESULT_BYTES)


class WithinBoundsTest(unittest.TestCase):
    def test_a_small_string_passes_through_unchanged(self):
        bounded, shortened = within_bounds("two artifacts")
        self.assertEqual(bounded, "two artifacts")
        self.assertFalse(shortened)

    def test_a_small_dict_passes_through_as_a_dict(self):
        value = {"ok": True, "stdout": "done"}
        bounded, shortened = within_bounds(value)
        self.assertEqual(bounded, value)
        self.assertFalse(shortened)

    def test_a_result_at_exactly_the_bound_is_not_shortened(self):
        bounded, shortened = within_bounds("x" * MAX_RESULT_BYTES)
        self.assertFalse(shortened)
        self.assertEqual(len(bounded), MAX_RESULT_BYTES)

    def test_an_oversized_string_is_shortened(self):
        _bounded, shortened = within_bounds("x" * (MAX_RESULT_BYTES + 1))
        self.assertTrue(shortened)

    def test_a_shortened_result_says_so(self):
        bounded, _ = within_bounds("x" * (MAX_RESULT_BYTES * 2))
        self.assertIn("Shortened", bounded)

    def test_a_shortened_result_names_both_sizes(self):
        # The kept figure is the byte count before the notice, which is less than the bound by the
        # notice's length.
        total = MAX_RESULT_BYTES * 2
        bounded, _ = within_bounds("x" * total)
        self.assertIn(str(total), bounded)
        kept, _, notice = bounded.partition("\n\n[Shortened.")
        self.assertIn(str(len(kept.encode("utf-8"))), notice)
        self.assertLess(len(kept.encode("utf-8")), MAX_RESULT_BYTES)

    def test_a_shortened_result_fits_inside_the_bound(self):
        bounded, _ = within_bounds("x" * (MAX_RESULT_BYTES * 3))
        self.assertLessEqual(len(bounded.encode("utf-8")), MAX_RESULT_BYTES)

    def test_an_oversized_dict_is_shortened_too(self):
        value = {"stdout": "x" * (MAX_RESULT_BYTES + 100)}
        bounded, shortened = within_bounds(value)
        self.assertTrue(shortened)
        self.assertIsInstance(bounded, str)
        self.assertIn("Shortened", bounded)

    def test_shortening_never_splits_a_character(self):
        # A cut inside a multi-byte UTF-8 sequence would not decode.
        bounded, _ = within_bounds("é" * MAX_RESULT_BYTES)
        self.assertIsInstance(bounded, str)

    def test_something_unserializable_is_still_bounded(self):
        class Opaque:
            def __repr__(self):
                return "x" * (MAX_RESULT_BYTES + 10)

        bounded, shortened = within_bounds(Opaque())
        self.assertTrue(shortened)
        self.assertLessEqual(len(bounded.encode("utf-8")), MAX_RESULT_BYTES)

    def test_a_json_serializable_value_is_measured_as_json(self):
        value = {"a": "x" * 100}
        bounded, shortened = within_bounds(value)
        self.assertFalse(shortened)
        self.assertLess(len(json.dumps(value)), MAX_RESULT_BYTES)


class RunOutputBoundTest(unittest.TestCase):
    """within_run_output_bound shortens a run result's stdout and stderr."""

    def result(self, **overrides):
        base = {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}
        base.update(overrides)
        return base

    def test_a_long_stdout_is_shortened(self):
        value = self.result(stdout="x" * (MAX_RUN_OUTPUT_CHARACTERS + 5_000))
        bounded = within_run_output_bound(value)
        self.assertLess(len(bounded["stdout"]), len(value["stdout"]))
        self.assertIn("Shortened", bounded["stdout"])

    def test_a_long_stderr_is_shortened_too(self):
        value = self.result(stderr="e" * (MAX_RUN_OUTPUT_CHARACTERS + 1))
        self.assertIn("Shortened", within_run_output_bound(value)["stderr"])

    def test_output_inside_the_bound_is_untouched(self):
        value = self.result(stdout="x" * MAX_RUN_OUTPUT_CHARACTERS)
        self.assertIs(within_run_output_bound(value), value)

    def test_the_fields_around_the_output_survive(self):
        value = self.result(
            ok=False, exit_code=3, stdout="x" * (MAX_RUN_OUTPUT_CHARACTERS + 1)
        )
        bounded = within_run_output_bound(value)
        self.assertEqual(bounded["ok"], False)
        self.assertEqual(bounded["exit_code"], 3)

    def test_the_caller_value_is_not_mutated(self):
        value = self.result(stdout="x" * (MAX_RUN_OUTPUT_CHARACTERS + 1))
        within_run_output_bound(value)
        self.assertEqual(len(value["stdout"]), MAX_RUN_OUTPUT_CHARACTERS + 1)

    def test_anything_that_is_not_a_run_result_passes_through(self):
        self.assertEqual(within_run_output_bound("a listing"), "a listing")

    def test_the_notice_states_what_was_kept(self):
        value = self.result(stdout="x" * (MAX_RUN_OUTPUT_CHARACTERS + 7))
        self.assertIn(
            str(MAX_RUN_OUTPUT_CHARACTERS), within_run_output_bound(value)["stdout"]
        )


class ShorteningNoticeTest(unittest.TestCase):
    """The notice states the byte count of the text before it."""

    def test_the_notice_counts_what_precedes_it(self):
        bounded, shortened = within_bounds("x" * (MAX_RESULT_BYTES * 2))
        self.assertTrue(shortened)
        kept, _, notice = bounded.partition("\n\n[Shortened.")
        self.assertIn(str(len(kept.encode("utf-8"))), notice)

    def test_the_whole_thing_still_fits_inside_the_bound(self):
        bounded, _ = within_bounds("x" * (MAX_RESULT_BYTES * 2))
        self.assertLessEqual(len(bounded.encode("utf-8")), MAX_RESULT_BYTES)


class FailureFlagTest(unittest.TestCase):
    """_reports_failure recognizes ok=False, a nonzero exit_code, an error field, and an exception."""

    def test_ok_false_is_a_failure(self):
        self.assertTrue(_reports_failure({"ok": False}))

    def test_a_nonzero_exit_code_is_a_failure(self):
        self.assertTrue(_reports_failure({"exit_code": 2}))

    def test_an_error_field_is_a_failure(self):
        self.assertTrue(_reports_failure({"error": "it went wrong"}))

    def test_a_raised_exception_handed_back_is_a_failure(self):
        self.assertTrue(_reports_failure(RuntimeError("boom")))

    def test_a_successful_run_is_not_a_failure(self):
        self.assertFalse(_reports_failure({"ok": True, "exit_code": 0, "stdout": "hi"}))

    def test_a_plain_string_result_is_not_a_failure(self):
        self.assertFalse(_reports_failure("a listing"))

    def test_an_empty_error_field_is_not_a_failure(self):
        self.assertFalse(_reports_failure({"ok": True, "error": ""}))


if __name__ == "__main__":
    unittest.main()
