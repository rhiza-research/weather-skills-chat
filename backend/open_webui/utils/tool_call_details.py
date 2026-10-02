"""Builds the completed tool-call <details> element that the interface renders.

The frontend parses this element with a regular expression. The chat loop and the MCP endpoint both
use this function. The in-progress form is built only in the chat loop.
"""

import html
import json

# The frontend matches on this type attribute value.
DETAILS_TYPE = "tool_calls"


def completed_tool_call_details(
    *,
    call_id: str,
    name: str,
    arguments,
    result,
    files=None,
    timing_attr: str = "",
) -> str:
    """One completed tool call as a <details> element.

    `timing_attr` is an already-formatted attribute string, or empty. The leading and trailing
    newlines separate concatenated elements for the frontend parser.
    """
    files_attr = html.escape(json.dumps(files)) if files else ""
    return (
        f'\n<details type="{DETAILS_TYPE}" done="true" id="{call_id}" name="{name}"'
        f' arguments="{html.escape(json.dumps(arguments))}"'
        f' result="{html.escape(json.dumps(result))}"'
        f' files="{files_attr}"{timing_attr}>\n<summary>Tool Executed</summary>\n</details>\n'
    )
