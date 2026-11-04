"""发布扫描须拦截每家服务商的本地密钥，而非只扫描 DeepSeek。"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import check_secrets


class ReleaseSafetyTests(unittest.TestCase):
    def test_blocks_provider_keys_in_the_git_index(self):
        folder=Path(tempfile.mkdtemp())
        subprocess.run(["git","init","-q",str(folder)],check=True)
        (folder/".env").write_text("ANTHROPIC_API_KEY=short-claude-key\nCOMPATIBLE_API_KEY=short-local-key\n",encoding="utf-8")
        for secret in ["short-claude-key","short-local-key","environment-key"]:
            with self.subTest(secret=secret):
                (folder/"source.txt").write_text(secret,encoding="utf-8")
                subprocess.run(["git","-C",str(folder),"add","source.txt"],check=True)
                with patch.object(check_secrets,"ROOT",folder), patch.dict(os.environ,{"OPENAI_API_KEY":"environment-key"}):
                    with self.assertRaises(RuntimeError):
                        check_secrets.check()
