import unittest

from open_webui.mcp.tools import _reports_failure


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
