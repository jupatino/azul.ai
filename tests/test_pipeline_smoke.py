import unittest


class PipelineSmokeTest(unittest.TestCase):
    def test_intentional_failure(self):
        self.fail("Intentional failure to verify the Slack @-mention on failure")
