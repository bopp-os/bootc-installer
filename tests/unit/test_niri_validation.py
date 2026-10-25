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
    from PyQt6.QtCore import QMetaObject, QObject, Q_RETURN_ARG, QUrl, QVariant
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

    def fill_account(self, username="jo", password="pw", again="pw"):
        self.root.setProperty("problems", {})
        self.root.setProperty("username", username)
        self.root.setProperty("userPassword", password)
        self.root.setProperty("userPasswordConfirm", again)

    def test_the_partial_recipe_asks_about_the_username(self):
        self.root.setProperty("username", "root")
        self.assertEqual(self.call("partialRecipe")["user"], {"username": "root"})

    def test_a_username_problem_shows_its_copy_line_and_holds_continue(self):
        self.fill_account()
        self.assertTrue(self.root.property("accountReady"))
        self.root.setProperty("problems", {"user.username": {
            "field": "user.username", "code": "username_reserved", "message": "m"}})
        copy = json.loads((NIRI / "installer" / "copy-defaults.json").read_text())
        self.assertEqual(self.root.property("usernameProblem"),
                         copy["validate_username_reserved"])
        self.assertFalse(self.root.property("accountReady"))
        self.root.setProperty("problems", {})

    def test_continue_needs_a_username_and_matching_passwords(self):
        self.fill_account(username="")
        self.assertFalse(self.root.property("accountReady"))
        self.fill_account(password="", again="")
        self.assertFalse(self.root.property("accountReady"))
        self.fill_account(password="pw", again="pX")
        self.assertFalse(self.root.property("accountReady"))
        self.fill_account()
        self.assertTrue(self.root.property("accountReady"))

    def test_install_writes_the_user_block(self):
        self.fill_account(password="s3cret", again="s3cret")
        self.root.setProperty("fullname", "Jo Doe")
        self.root.setProperty("selectedDisk", {"path": "/dev/vda"})
        QMetaObject.invokeMethod(self.root, "startInstall")
        written = next(o.property("written") for o in self.root.findChildren(QObject)
                       if o.property("written") and '"disk"' in o.property("written"))
        self.assertEqual(json.loads(written)["user"], {
            "username": "jo", "fullname": "Jo Doe", "password": "s3cret",
            "groups": ["wheel"]})
        self.root.setProperty("currentPage", 0)

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
