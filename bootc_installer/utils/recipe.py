# recipe.py
#
# Copyright 2024 mirkobrombin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import os
import sys
from gettext import gettext as _

from bootc_installer.utils import branding

logger = logging.getLogger("Installer::RecipeLoader")


def _host_live():
    """(is_live, live_image) from fisherman's probe (`live`), the one answer
    every frontend uses (shared/probe/README.md). Not live when the probe
    failed."""
    from bootc_installer.core.system import Systeminfo
    return Systeminfo.is_live(), Systeminfo.live_image()


class RecipeLoader:
    # When running inside a Flatpak sandbox, /etc is reserved by the runtime
    # and inaccessible at /etc/.  The host filesystem /etc is available at
    # /run/host/etc instead.  We detect this at class instantiation time and
    # prefix all /etc/ recipe search paths accordingly.
    _in_flatpak: bool = os.path.exists("/.flatpak-info")
    _etc: str = "/run/host/etc" if os.path.exists("/.flatpak-info") else "/etc"

    @property
    def recipe_paths(self):
        return [
            f"{self._etc}/bootc-installer/recipe.json",
            f"{self._etc}/bootcos-installer/recipe.json",
            f"{self._etc}/vanilla-installer/recipe.json",
            "/app/share/bootc-installer/recipe.json",
        ]

    recipe_path = None

    # Where live-media facts come from; a seam for tests.
    _host_live = staticmethod(_host_live)

    def __init__(self):
        self.__recipe = {}
        self.__load()

    def __load(self):
        paths = (
            [os.environ["BOOTC_CUSTOM_RECIPE"]]
            if "BOOTC_CUSTOM_RECIPE" in os.environ
            else self.recipe_paths
        )

        for path in paths:
            if os.path.exists(path):
                self.recipe_path = path
                with open(path, "r") as f:
                    self.__recipe = json.load(f)
                if self.__validate():
                    self.__apply_branding()
                    self.__enrich()
                    return
                logger.warning(f"Recipe at {path} failed validation, trying next...")

        logger.error(f"No valid recipe found. Tried: {paths}")
        if os.environ.get("BOOTC_DEMO") or os.environ.get("BOOTC_PREVIEW_SCREEN"):
            logger.warning("Demo/preview mode: continuing without a recipe")
            self.__recipe = {
                "log_file": "/tmp/bootc-installer-demo.log",
                "distro_name": os.environ.get("BOOTC_DEMO_DISTRO_NAME", ""),
                "distro_logo": "",
                "steps": {},
            }
            return
        sys.exit(1)

    def __apply_branding(self):
        """Name the product from the branding contract, never from a literal.

        shared/branding/README.md: a branding.json (host first) wins, then the
        recipe's own `distro_name`/`welcome_title`/`distro_logo` (a custom
        recipe is a config file too), then os-release, then a neutral name.
        The resolved branding is exposed as recipe["branding"] for the about
        dialog, the recovery dialog, the phone companion and the hostname
        generator, so no other module reads os-release on its own.
        """
        b = branding.resolve()
        r = self.__recipe
        file_wins = b.source in ("env", "file")
        if file_wins or not r.get("distro_name"):
            r["distro_name"] = b.name
        if not r.get("distro_logo"):
            r["distro_logo"] = b.logo or "org.bootcinstaller.Installer"
        # Every flavour line comes from the branding copy layer; the recipe's
        # own welcome_title/welcome_subtitle are honoured only when no
        # branding file names the product (a custom recipe is a config file
        # too, but the branding file is the one the contract names).
        name = r["distro_name"]
        if file_wins or not r.get("welcome_title"):
            r["welcome_title"] = b.text("welcome_title", name=name)
        if file_wins or "welcome_subtitle" not in r:
            r["welcome_subtitle"] = b.text("welcome_subtitle", name=name)
        # Store, credits and artwork: assets are host paths; the recipe keys
        # the views already read stay the interface, so a branding file and
        # an old-style recipe both work.
        if file_wins or not r.get("store_url"):
            r["store_url"] = b.store_url
        if b.assets.get("store_qr") and (file_wins or not r.get("store_qr_resource")):
            r["store_qr_resource"] = b.assets["store_qr"]
        # GNOME-only extras (tour pages, install video, credits) are outside
        # the parity contract: they come from extensions.gnome in the
        # branding file, never from the common copy or assets.
        ext = b.extensions.get("gnome", {}) if isinstance(b.extensions, dict) else {}
        def ext_text(key, default):
            return (ext.get(key) if ext.get(key) is not None else default).replace("{name}", name)
        if ext.get("credits") and (file_wins or not r.get("credits_data")):
            r["credits_data"] = ext["credits"]
        if ext.get("video") and (file_wins or not r.get("install_video")):
            r["install_video"] = ext["video"]
        if file_wins or not isinstance(r.get("tour"), dict):
            r["tour"] = {
                "welcome": {
                    "image": b.assets.get("welcome_image", ""),
                    "title": ext_text("tour_welcome_title", _("Installing {name}")),
                    "description": ext_text("tour_welcome_description", _("This will take a few minutes.")),
                },
                "completed": {
                    "image": b.assets.get("complete_image", ""),
                    "title": ext_text("tour_done_title", _("Installation complete")),
                    "description": ext_text("tour_done_description", _("Your system is ready to use.")),
                },
            }
        d = b.as_dict()
        d.update({"store_url": b.store_url, "copy": dict(b.copy), "assets": dict(b.assets),
                  "confirm_quotes": dict(b.confirm_quotes), "extensions": dict(b.extensions)})
        r["branding"] = d
        logger.info("Branding: %s (%s)", r["distro_name"], b.source)

    def __enrich(self):
        """Post-load enrichment: on live media, install the configured image
        (or the running one) without an image step.

        Live media is fisherman's answer (probe's live.is_live). This used to
        be decided here from /run/ostree-booted, /run/initramfs/live and a
        flag file, read inside the Flatpak sandbox; /run/ostree-booted is on
        every installed ostree host, so a bootc desktop lost its image step.
        The booted image came from `bootc status`, which the probe now runs on
        the host.
        """
        live, live_image = self._host_live()
        if not live:
            logger.info("Not live media: image selection enabled")
            return

        # local_imgref is an optional override for the install *source* used only
        # on live media (e.g. "containers-storage:ghcr.io/org/image:tag" for
        # offline installs from a pre-populated squashfs).  imgref always remains
        # the remote tracking reference written into the installed system.
        if not self.__recipe.get("local_imgref"):
            imgref = self.__recipe.get("imgref", "") or live_image
            if imgref:
                logger.info(f"Live media: using bootc image {imgref}")
                self.__recipe["imgref"] = imgref
            else:
                # Nothing names the image: an empty image installs the
                # running system, which fisherman accepts on live media.
                logger.warning("Live media: no image named; installing the running system")
        else:
            logger.info(
                f"Live media: local_imgref override present "
                f"({self.__recipe['local_imgref']}), imgref stays as remote tracking ref"
            )

        # Remove the image selection step — use the configured image silently
        self.__recipe["steps"].pop("image", None)
        logger.info("Live media: image selection step removed")

    def __validate(self):
        # distro_name/distro_logo are no longer essential: __apply_branding fills
        # them from branding.json or os-release when the recipe leaves them out.
        essential_keys = ["log_file", "steps"]
        if not isinstance(self.__recipe, dict):
            logger.error(_("Recipe is not a dictionary"))
            return False

        for key in essential_keys:
            if key not in self.__recipe:
                logger.error(_(f"Recipe is missing the '{key}' key"))
                return False

        if not isinstance(self.__recipe["steps"], dict):
            logger.error(_("Recipe steps is not a dictionary"))
            return False

        for step_key, step in self.__recipe["steps"].items():
            if not isinstance(step, dict):
                logger.error(_(f"Step {step_key} is not a dictionary"))
                return False

        return True

    @property
    def raw(self):
        return self.__recipe
