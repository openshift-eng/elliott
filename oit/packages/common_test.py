import tempfile
import unittest
from common import exec_cmd, parse_taskinfo, retry


class ExecCmdCommand(unittest.TestCase):
    class RuntimeMock(object):
        def __init__(self, debug_log):
            self.debug_log = debug_log

        def log_verbose(self, message):
            self.debug_log.write(message + "\n")

    def exec_cmd(self, cmd):
        with tempfile.TemporaryFile() as f:
            runtime = self.RuntimeMock(f)
            rc = exec_cmd(runtime, cmd)
            f.seek(0)
            return rc, f.read()

    def test_success(self):
        rc, log = self.exec_cmd(["printf", "test\n"])
        self.assertEqual(rc, 0)
        self.assertIn("['printf', 'test\\n']", log)
        self.assertIn("\ntest\n", log)
        self.assertIn("Process exited with: 0", log)

    def test_failure(self):
        rc, log = self.exec_cmd(["printf"])
        self.assertEqual(rc, 1)
        self.assertIn("['printf']", log)
        self.assertIn("missing operand", log)
        self.assertIn("Process exited with: 1", log)


class RetryTestCase(unittest.TestCase):
    ERROR_MSG = r"Giving up after {} failed attempt\(s\)"

    def test_success(self):
        f = lambda: True
        self.assertTrue(retry(1, f))
        self.assertTrue(retry(2, f))

    def test_failure(self):
        f = lambda: False
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(1), retry, 1, f)
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(2), retry, 2, f)

    def test_wait(self):
        calls = []
        self.assertRaisesRegexp(
            Exception, self.ERROR_MSG.format(3),
            retry, 3, lambda: calls.append("f"),
            wait_f=lambda n: calls.extend(("w", str(n))))
        self.assertEqual(calls, list("fw0fw1f"))

    def test_return(self):
        obj = {}
        f = lambda: obj
        self.assertIs(retry(1, f, check_f=lambda _: True), obj)


class ParseTaskinfoTestCase(unittest.TestCase):
    def test_unknown(self):
        self.assertEqual(parse_taskinfo(""), "unknown")

    def test_closed(self):
        self.assertEqual(
            parse_taskinfo("""\
Task: 14892652
Type: newRepo
Owner: kojira
State: closed
Created: Mon Jan  8 12:47:05 2018
Started: Mon Jan  8 12:47:23 2018
Finished: Mon Jan  8 12:49:56 2018
Host: x86-019.build.eng.bos.redhat.com
"""),
            "closed")

    def test_open(self):
        self.assertEqual(
            parse_taskinfo("""\
Task: 14892672
Type: newRepo
Owner: kojira
State: open
Created: Mon Jan  8 12:48:43 2018
Started: Mon Jan  8 12:49:07 2018
Host: x86-034.build.eng.bos.redhat.com
"""),
            "open")

if __name__ == "__main__":
    unittest.main()
