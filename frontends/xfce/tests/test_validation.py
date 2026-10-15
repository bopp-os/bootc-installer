"""The identity and encryption pages ask fisherman, not a pattern.

`fisherman validate --json --partial -` owns the hostname, username,
filesystem and encryption rules (shared/recipe/README.md). These drive the
real pages with fisherman's answer and check what the user sees: the copy
line for the code, and a Next button that stays off until it is fixed.
"""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import core, pages  # noqa: E402


class _Win:
    def __init__(self, needs_user=True):
        self.needs_user = needs_user
        self.refreshed = 0

    def needs_user_creation(self):
        return self.needs_user

    def refresh_nav(self):
        self.refreshed += 1

    def selected_leaf(self):
        return None


class _Check:
    """Stands in for LiveCheck: records what the page submits."""

    def __init__(self, on_result):
        self.on_result = on_result
        self.submitted = []

    def submit(self, recipe):
        self.submitted.append(recipe)


def _page(cls, monkeypatch, **kw):
    checks = []

    def fake(on_result):
        checks.append(_Check(on_result))
        return checks[-1]

    monkeypatch.setattr(pages, "live_check", fake)
    page = cls(_Win(**kw))
    return page, checks[0]


def test_identity_sends_hostname_and_username_as_a_partial_recipe(monkeypatch):
    page, check = _page(pages.IdentityPage, monkeypatch)
    page.hostname.set_text("my_pc")
    page.username.set_text("root")
    assert check.submitted[-1] == {"hostname": "my_pc", "user": {"username": "root"}}


def test_identity_without_a_user_page_sends_only_the_hostname(monkeypatch):
    page, check = _page(pages.IdentityPage, monkeypatch, needs_user=False)
    page.hostname.set_text("box")
    assert check.submitted[-1] == {"hostname": "box"}


def test_a_hostname_problem_shows_its_copy_and_blocks_next(monkeypatch):
    page, check = _page(pages.IdentityPage, monkeypatch)
    page.username.set_text("jo")
    page.password.set_text("pw")
    assert page.can_continue()
    check.on_result([{"field": "hostname", "code": "hostname_invalid_char",
                      "message": "hostname contains '_'"}], None)
    assert not page.can_continue()
    assert page.hostname_problem.get_text() == core.BRANDING.text(
        "validate_hostname_invalid_char")
    check.on_result([], None)
    assert page.can_continue()
    assert page.hostname_problem.get_text() == ""


def test_a_reserved_username_blocks_next(monkeypatch):
    page, check = _page(pages.IdentityPage, monkeypatch)
    page.username.set_text("root")
    page.password.set_text("pw")
    check.on_result([{"field": "user.username", "code": "username_reserved",
                      "message": "m"}], None)
    assert not page.can_continue()
    assert page.username_problem.get_text() == core.BRANDING.text("validate_username_reserved")


def test_a_check_that_cannot_run_blocks_nothing(monkeypatch):
    page, check = _page(pages.IdentityPage, monkeypatch)
    page.username.set_text("jo")
    page.password.set_text("pw")
    check.on_result(None, "cannot run /usr/local/bin/fisherman: not found")
    assert page.can_continue()


def test_encryption_page_sends_the_passphrase_on_stdin_not_argv(monkeypatch):
    monkeypatch.setattr(core, "has_tpm", lambda: True)
    page, check = _page(pages.SetupPage, monkeypatch)
    page.on_enter()
    luks = next(r for r in page.enc_radios if r.value == "luks-passphrase")
    luks.set_active(True)
    page.pass1.set_text("s3cret")
    assert check.submitted[-1]["encryption"] == {"type": "luks-passphrase",
                                                 "passphrase": "s3cret"}
    assert "s3cret" not in " ".join(core.VALIDATE_ARGV)


def test_encryption_problem_blocks_next(monkeypatch):
    page, check = _page(pages.SetupPage, monkeypatch)
    check.on_result([{"field": "encryption.type", "code": "encryption_unsupported_on_zfs",
                      "message": "m"}], None)
    assert not page.can_continue()
    assert page.problem_label.get_text() == core.BRANDING.text(
        "validate_encryption_unsupported_on_zfs")


def test_tpm_choices_follow_needs_tpm2(monkeypatch):
    monkeypatch.setattr(core, "has_tpm", lambda: False)
    page, _ = _page(pages.SetupPage, monkeypatch)
    assert [r.value for r in page.enc_radios] == [
        c["type"] for c in core.ENCRYPTION_CHOICES if not c["needs_tpm2"]]


def test_no_page_carries_a_rule_of_its_own():
    src = open(pages.__file__).read()
    assert "HOSTNAME_RE" not in src
    assert '"passphrase" in' not in src
    assert 'startswith("tpm2")' not in src
