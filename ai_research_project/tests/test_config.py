import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import config


class ConfigTests(unittest.TestCase):
    def test_local_env_loading(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("TEST_LOCAL_KEY=local-value\n", encoding="ascii")
            with patch.dict(os.environ, {}, clear=True):
                config.load_local_env(env_file)
                self.assertEqual(config.get_config_value("TEST_LOCAL_KEY"), "local-value")

    def test_streamlit_secrets_fallback(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            config, "_streamlit_secret", return_value="cloud-value"
        ):
            self.assertEqual(config.get_config_value("FMP_API_KEY"), "cloud-value")

    def test_missing_keys_are_graceful(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            config, "_streamlit_secret", return_value=None
        ):
            self.assertIsNone(config.get_config_value("MISSING_KEY"))


if __name__ == "__main__":
    unittest.main()
