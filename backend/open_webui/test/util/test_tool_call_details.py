"""The exact text of the completed tool-call <details> element.

The frontend parses this element with a regular expression, so these tests compare exact output.
"""

import html
import json
import unittest

from open_webui.utils.tool_call_details import (
    DETAILS_TYPE,
    completed_tool_call_details,
)

CALL_ID = "call_abc123"
NAME = "fetch_rain"
ARGUMENTS = {"bbox": "0,0,1,1"}
RESULT = "wrote rain.zarr"


def rendered(**overrides):
    kwargs = {
        "call_id": CALL_ID,
        "name": NAME,
        "arguments": ARGUMENTS,
        "result": RESULT,
    }
    kwargs.update(overrides)
    return completed_tool_call_details(**kwargs)


class ExactShapeTest(unittest.TestCase):
    def test_the_element_matches_what_the_chat_loop_produced(self):
        # Copied from the f-string the chat loop used before this helper existed. A mismatch breaks
        # the frontend's parser without any backend error.
        expected = (
            f'\n<details type="tool_calls" done="true" id="{CALL_ID}"'
            f' name="{NAME}"'
            f' arguments="{html.escape(json.dumps(ARGUMENTS))}"'
            f' result="{html.escape(json.dumps(RESULT))}"'
            f' files="">\n<summary>Tool Executed</summary>\n</details>\n'
        )
        self.assertEqual(rendered(), expected)

    def test_it_opens_with_a_newline(self):
        # Callers concatenate elements, and the parser expects a newline between them.
        self.assertTrue(rendered().startswith("\n<details"))

    def test_it_closes_with_a_newline(self):
        self.assertTrue(rendered().endswith("</details>\n"))

    def test_the_type_is_the_one_the_frontend_keys_off(self):
        self.assertIn(f'type="{DETAILS_TYPE}"', rendered())

    def test_it_is_marked_done(self):
        self.assertIn('done="true"', rendered())


class EscapingTest(unittest.TestCase):
    def test_arguments_are_escaped(self):
        out = rendered(arguments={"note": '<script>"x"</script>'})
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_a_result_containing_quotes_does_not_break_the_attribute(self):
        out = rendered(result='he said "hello"')
        # An unescaped quote would end the attribute early.
        result_attr = out.split('result="')[1].split('"')[0]
        self.assertNotIn('"', result_attr)

    def test_a_result_containing_an_element_is_escaped(self):
        self.assertNotIn("</details>", rendered(result="</details>").split("result=")[1].split(" files=")[0])


class FilesTest(unittest.TestCase):
    def test_no_files_gives_an_empty_attribute(self):
        self.assertIn('files=""', rendered())

    def test_an_empty_list_gives_an_empty_attribute(self):
        self.assertIn('files=""', rendered(files=[]))

    def test_files_are_escaped_json(self):
        out = rendered(files=[{"name": "rain.png"}])
        self.assertIn(html.escape(json.dumps([{"name": "rain.png"}])), out)


class TimingTest(unittest.TestCase):
    def test_no_timing_adds_nothing(self):
        self.assertIn('files="">', rendered())

    def test_a_timing_fragment_is_passed_through_verbatim(self):
        # The caller formats the timing attribute, because streamed turns and endpoint calls
        # measure duration differently.
        self.assertIn(' duration="12">', rendered(timing_attr=' duration="12"'))


if __name__ == "__main__":
    unittest.main()
