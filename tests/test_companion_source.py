from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from companion_source import (  # noqa: E402
    derive_torchaudio_version,
    derive_torchvision_version,
    resolve_companion_sources,
)


class CompanionSourceTests(unittest.TestCase):
    def test_torch_2_13_uses_official_companion_versions(self) -> None:
        self.assertEqual(derive_torchvision_version("2.13.0"), "0.28.0")
        self.assertEqual(derive_torchaudio_version("2.13.0"), "2.11.0")

        result = resolve_companion_sources("2.13.0", verify_tags=False)

        self.assertEqual(result["torch_git_tag"], "v2.13.0")
        self.assertEqual(result["torchvision_git_tag"], "v0.28.0")
        self.assertEqual(result["torchaudio_git_tag"], "v2.11.0")
        self.assertTrue(result["ready"])
        self.assertEqual(result["errors"], [])

    def test_torchaudio_stable_abi_is_reused_for_later_torch_releases(self) -> None:
        self.assertEqual(derive_torchaudio_version("2.11.0"), "2.11.0")
        self.assertEqual(derive_torchaudio_version("2.12.1"), "2.11.0")
        self.assertEqual(derive_torchaudio_version("2.13.0"), "2.11.0")

    def test_unsupported_torchvision_release_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "No verified torchvision compatibility"):
            derive_torchvision_version("2.14.0")


if __name__ == "__main__":
    unittest.main()
