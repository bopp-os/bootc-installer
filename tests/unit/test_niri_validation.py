"""Niri's QML asks fisherman (`validate --json --partial`), not a pattern.

installer.qml is loaded with the stub Quickshell modules the capture uses
(frontends/niri/tests/qml-stubs; the stub Process spawns nothing). The test
sets fisherman's answer and checks what the user sees and what the backend
would be sent. Skipped without PyQt6, which the Niri capture and e2e jobs
install.
"""

import json
import os
import pathlib
import unittest

NIRI = pathlib.Path(__file__).resolve().parents[2] / "frontends" / "niri"

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QML2_IMPORT_PATH"] = str(NIRI / "tests" / "qml-stubs")
    os.environ["QML_IMPORT_PATH"] = os.environ["QML2_IMPORT_PATH"]
    from PyQt6.QtCore import QMetaObject, Q_RETURN_ARG, QUrl, QVariant
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine
except ImportError:  # pragma: no cover - the root unit job has no PyQt6
    QGuiApplication = None


@unittest.skipIf(QGuiApplication is None, "PyQt6 is not installed")
class NiriAsksFisherman(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.engine = QQmlApplicationEngine()
        cls.engine.load(QUrl.fromLocalFile(str(NIRI / "ui" / "installer.qml")))
        assert cls.engine.rootObjects(), "installer.qml did not load"
        cls.root = cls.engine.rootObjects()[0]
        with open(NIRI / "installer" / "encryption-choices.json") as fh:
            cls.root.setProperty("encryptionChoices", json.load(fh)["choices"])

    def call(self, name):
        ret = QMetaObject.invokeMethod(self.root, name, Q_RETURN_ARG(QVariant))
        return ret.toVariant() if hasattr(ret, "toVariant") else ret

    def test_a_hostname_problem_shows_its_copy_line(self):
        self.root.setProperty("problems", {"hostname": {
            "field": "hostname", "code": "hostname_label_hyphen", "message": "m"}})
        copy = json.loads((NIRI / "installer" / "copy-defaults.json").read_text())
        self.assertEqual(self.root.property("hostnameProblem"),
                         copy["validate_hostname_label_hyphen"])
        self.root.setProperty("problems", {})
        self.assertEqual(self.root.property("hostnameProblem"), "")

    def test_an_unknown_code_shows_fishermans_message(self):
        self.root.setProperty("problems", {"encryption.passphrase": {
            "field": "encryption.passphrase", "code": "brand_new", "message": "say why"}})
        self.assertEqual(self.root.property("encryptionProblem"), "say why")
        self.root.setProperty("problems", {})

    def test_the_partial_recipe_carries_the_passphrase_only_when_needed(self):
        self.root.setProperty("hostname", "box")
        self.root.setProperty("encType", "tpm2-luks")
        self.root.setProperty("passphrase", "s3cret")
        partial = self.call("partialRecipe")
        self.assertEqual(partial["encryption"], {"type": "tpm2-luks"})
        self.root.setProperty("encType", "tpm2-luks-passphrase")
        partial = self.call("partialRecipe")
        self.assertEqual(partial["encryption"]["passphrase"], "s3cret")
        self.assertEqual(partial["hostname"], "box")

    def offered(self):
        value = self.root.property("offeredEncryptionTypes")
        return value.toVariant() if hasattr(value, "toVariant") else list(value)

    def test_tpm_choices_follow_needs_tpm2(self):
        self.root.setProperty("hasTpm", False)
        self.assertEqual(self.offered(), ["none", "luks-passphrase"])
        self.root.setProperty("hasTpm", True)
        self.assertEqual(len(self.offered()), 4)


if __name__ == "__main__":
    unittest.main()
