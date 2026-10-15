"""Unit tests for RecipeLoader (utils/recipe.py)."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Add bootc_installer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bootc_installer.utils.recipe import RecipeLoader


class TestRecipeLoaderInit(unittest.TestCase):
    """Tests for RecipeLoader.__init__ and recipe_paths property."""

    def test_recipe_paths_default(self):
        """recipe_paths should return the standard search paths."""
        loader = object.__new__(RecipeLoader)  # skip __init__
        loader._in_flatpak = False
        loader._etc = "/etc"
        paths = loader.recipe_paths
        self.assertEqual(len(paths), 4)
        self.assertIn("/etc/bootc-installer/recipe.json", paths)
        self.assertIn("/etc/bootcos-installer/recipe.json", paths)
        self.assertIn("/app/share/bootc-installer/recipe.json", paths)

    def test_recipe_paths_flatpak(self):
        """In Flatpak mode, /etc paths are prefixed with /run/host."""
        loader = object.__new__(RecipeLoader)
        loader._in_flatpak = True
        loader._etc = "/run/host/etc"
        paths = loader.recipe_paths
        self.assertTrue(all(p.startswith("/run/host/etc") or p == "/app/share/bootc-installer/recipe.json" for p in paths))


class TestRecipeLoaderValidate(unittest.TestCase):
    """Tests for RecipeLoader.__validate method."""

    def setUp(self):
        self.loader = object.__new__(RecipeLoader)
        self.loader._in_flatpak = False
        self.loader._etc = "/etc"
        self.loader.recipe_path = None

    def set_recipe(self, data):
        self.loader._RecipeLoader__recipe = data

    def test_valid_recipe(self):
        """A complete recipe with all essential keys should validate."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": {"partition": {"type": "auto"}}
        })
        self.assertTrue(self.loader._RecipeLoader__validate())

    def test_missing_log_file(self):
        """A recipe missing 'log_file' should fail validation."""
        self.set_recipe({
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": {}
        })
        self.assertFalse(self.loader._RecipeLoader__validate())

    def test_missing_distro_name_is_allowed(self):
        """distro_name is optional: the branding contract fills it in
        (shared/branding/README.md), so validation must not reject it."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_logo": "logo.png",
            "steps": {}
        })
        self.assertTrue(self.loader._RecipeLoader__validate())

    def test_missing_distro_logo_is_allowed(self):
        """distro_logo is optional for the same reason as distro_name."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "steps": {}
        })
        self.assertTrue(self.loader._RecipeLoader__validate())

    def test_missing_steps(self):
        """A recipe missing 'steps' should fail validation."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png"
        })
        self.assertFalse(self.loader._RecipeLoader__validate())

    def test_not_a_dict(self):
        """A non-dict recipe should fail validation."""
        self.set_recipe(["list", "not", "dict"])
        self.assertFalse(self.loader._RecipeLoader__validate())

    def test_steps_not_a_dict(self):
        """Steps that are not a dict should fail validation."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": "not a dict"
        })
        self.assertFalse(self.loader._RecipeLoader__validate())

    def test_step_value_not_dict(self):
        """A step whose value is not a dict should fail validation."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": {"bad_step": "not a dict"}
        })
        self.assertFalse(self.loader._RecipeLoader__validate())


class TestRecipeLoaderEnrich(unittest.TestCase):
    """Tests for RecipeLoader.__enrich (live ISO detection)."""

    def setUp(self):
        self.loader = object.__new__(RecipeLoader)
        self.loader._in_flatpak = False
        self.loader._etc = "/etc"
        self.loader.recipe_path = None
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": {"image": {"type": "select"}, "partition": {"type": "auto"}}
        })

    def set_recipe(self, data):
        self.loader._RecipeLoader__recipe = data

    @patch.object(RecipeLoader, "_host_live", return_value=(False, ""))
    def test_normal_mode_keeps_image_step(self, _live):
        """Not live media (fisherman's probe): the image step stays."""
        self.loader._RecipeLoader__enrich()
        self.assertIn("image", self.loader._RecipeLoader__recipe["steps"])

    @patch("os.path.exists", return_value=True)
    @patch.object(RecipeLoader, "_host_live", return_value=(False, ""))
    def test_ostree_booted_is_not_live_media(self, _live, _exists):
        """/run/ostree-booted is on every installed ostree host; an installed
        bootc desktop keeps its image step."""
        self.loader._RecipeLoader__enrich()
        self.assertIn("image", self.loader._RecipeLoader__recipe["steps"])

    @patch.object(RecipeLoader, "_host_live", return_value=(True, "ghcr.io/x/live:1"))
    def test_live_iso_removes_image_step(self, _live):
        """On live media, the image selection step is removed."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": {"image": {"type": "select"}, "partition": {"type": "auto"}},
            "imgref": "ghcr.io/test/image:latest"
        })
        self.loader._RecipeLoader__enrich()
        self.assertNotIn("image", self.loader._RecipeLoader__recipe["steps"])
        # The configured image wins over the booted one.
        self.assertEqual(self.loader._RecipeLoader__recipe["imgref"], "ghcr.io/test/image:latest")

    @patch.object(RecipeLoader, "_host_live",
           return_value=(True, "containers-storage:ghcr.io/test:latest"))
    def test_live_iso_uses_the_probes_live_image(self, _live):
        """Without an imgref, the booted image is fisherman's live.live_image."""
        self.loader._RecipeLoader__enrich()
        self.assertEqual(
            self.loader._RecipeLoader__recipe["imgref"],
            "containers-storage:ghcr.io/test:latest"
        )

    @patch.object(RecipeLoader, "_host_live", return_value=(True, ""))
    def test_live_without_an_image_name_installs_the_running_system(self, _live):
        self.loader._RecipeLoader__enrich()
        self.assertNotIn("imgref", self.loader._RecipeLoader__recipe)
        self.assertNotIn("image", self.loader._RecipeLoader__recipe["steps"])

    @patch.object(RecipeLoader, "_host_live", return_value=(True, "ghcr.io/x/live:1"))
    def test_local_imgref_preserves_imgref(self, _live):
        """When local_imgref is set, imgref should stay as the remote tracking ref."""
        self.set_recipe({
            "log_file": "/tmp/test.log",
            "distro_name": "Test OS",
            "distro_logo": "logo.png",
            "steps": {"partition": {"type": "auto"}},
            "local_imgref": "containers-storage:ghcr.io/test:local",
            "imgref": "ghcr.io/test/remote:latest"
        })
        self.loader._RecipeLoader__enrich()
        self.assertEqual(
            self.loader._RecipeLoader__recipe["imgref"],
            "ghcr.io/test/remote:latest"
        )

    def test_the_loader_runs_no_bootc_status_of_its_own(self):
        self.assertFalse(hasattr(RecipeLoader, "_RecipeLoader__detect_local_bootc_image"))


class TestRecipeLoaderCustomRecipe(unittest.TestCase):
    """Tests for BOOTC_CUSTOM_RECIPE environment variable support."""

    def setUp(self):
        # Create a temp recipe file
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({
            "log_file": "/tmp/custom.log",
            "distro_name": "Custom OS",
            "distro_logo": "custom.png",
            "steps": {"custom_step": {"type": "shell", "command": "echo hi"}}
        }, self.tmp)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    @patch.dict(os.environ, {}, clear=True)
    @patch("os.path.exists")
    def test_custom_recipe_env_overrides_paths(self, mock_exists):
        """BOOTC_CUSTOM_RECIPE env var should override default recipe paths."""
        # Only the custom path should exist (or be checked)
        mock_exists.return_value = False  # all default paths don't exist
        os.environ["BOOTC_CUSTOM_RECIPE"] = self.tmp.name

        # We need the custom file to exist
        mock_exists.side_effect = lambda p: p == self.tmp.name

        loader = RecipeLoader()
        self.assertEqual(loader.recipe_path, self.tmp.name)
        self.assertEqual(loader.raw["distro_name"], "Custom OS")


if __name__ == "__main__":
    unittest.main()
