import os
import tempfile
import unittest
from pathlib import Path

from tradeforge.env import load_local_env


class LocalEnvTests(unittest.TestCase):
    def test_loads_values_without_overriding_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("TEST_TF_KEY='secret-value'\nTEST_TF_EXISTING=from-file\n", encoding="utf-8")
            os.environ["TEST_TF_EXISTING"] = "from-process"
            try:
                load_local_env(path)
                self.assertEqual(os.environ["TEST_TF_KEY"], "secret-value")
                self.assertEqual(os.environ["TEST_TF_EXISTING"], "from-process")
            finally:
                os.environ.pop("TEST_TF_KEY", None)
                os.environ.pop("TEST_TF_EXISTING", None)


if __name__ == "__main__":
    unittest.main()
