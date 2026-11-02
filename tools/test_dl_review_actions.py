"""tools/test_dl_review_actions.py - tests for request_actions formatting and now_line formatting."""
import re
import unittest
from pathlib import Path
from unittest import mock

import dl_cli


class ReviewActionsTest(unittest.TestCase):
    def test_now_line_includes_tomorrow(self):
        line = dl_cli.now_line()
        self.assertTrue(line.startswith("[Now: "))
        self.assertIn("— sutra: ", line)
        self.assertTrue(line.endswith("]"))
        # Verify NOW_PREFIX strips it
        stripped = dl_cli.NOW_PREFIX.sub("", line + "\nHello")
        self.assertEqual(stripped, "Hello")

    def test_request_actions_prioritizes_external_and_truncates_edits(self):
        messages = [
            {"role": "user", "content": "Fetch weather and send email"},
        ]
        # Simulate 30 long replace_file_content calls
        for i in range(30):
            tc_id = f"call_{i}"
            messages.append({
                "role": "assistant",
                "tool_calls": [{
                    "id": tc_id,
                    "function": {
                        "name": "replace_file_content",
                        "arguments": f'{{"TargetFile": "weather/page.html", "TargetContent": "long string {i} " * 20, "ReplacementContent": "new string {i} " * 20}}'
                    }
                }]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f"Successfully updated weather/page.html with long output {i} " * 10
            })

        # Finally, a send_mail call
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": "call_send",
                "function": {
                    "name": "proton__send_mail",
                    "arguments": '{"to": "user@example.com", "html_file": "weather/page.html"}'
                }
            }]
        })
        messages.append({
            "role": "tool",
            "tool_call_id": "call_send",
            "content": "Sent from agent@example.com to user@example.com: Weather in Zagreb"
        })

        res = dl_cli.request_actions(messages, limit=3000)
        self.assertLessEqual(len(res), 3010)
        # proton__send_mail must be present and appear near the top
        self.assertIn("proton__send_mail", res)
        lines = res.splitlines()
        self.assertTrue(any("proton__send_mail" in l for l in lines[:3]), lines[:3])


if __name__ == "__main__":
    unittest.main()
