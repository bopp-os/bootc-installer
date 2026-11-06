# network.py
#
# Copyright 2024 mirkobrombin
# Copyright 2024 matbme
#
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

from __future__ import annotations

import logging
import socket
import time
from gettext import gettext as _
from operator import attrgetter
from threading import Lock, Timer

from gi.repository import NM, Adw, GLib, Gtk

from bootc_installer.utils.run_async import RunAsync

logger = logging.getLogger("BootcInstaller::Network")

# Dictionary mapping security types to a tuple containing
# their pretty name and whether it is a secure protocol.
# If security is None, it means that no padlock icon is shown.
# If security is False, a warning symbol appears instead of a padlock.
AP_SECURITY_TYPES = {
    "none": (None, None),
    "wep": (False, _("Insecure network (WEP)")),
    "wpa": (True, _("Secure network (WPA)")),
    "wpa2": (True, _("Secure network (WPA2)")),
    "sae": (True, _("Secure network (WPA3)")),
    "owe": (None, None),
    "owe_tm": (None, None),
}

# PyGObject-libnm doesn't seem to expose these values, so we have redefine them
NM_802_11_AP_FLAGS_PRIVACY = 0x00000001
NM_802_11_AP_SEC_NONE = 0x00000000

NM_802_11_AP_SEC_KEY_MGMT_802_1X = 0x00000200
NM_802_11_AP_SEC_KEY_MGMT_EAP_SUITE_B_192 = 0x00002000
NM_802_11_AP_SEC_KEY_MGMT_OWE = 0x00000800
NM_802_11_AP_SEC_KEY_MGMT_OWE_TM = 0x00001000
NM_802_11_AP_SEC_KEY_MGMT_PSK = 0x00000100
NM_802_11_AP_SEC_KEY_MGMT_SAE = 0x00000400


def signal_icon_name(strength: int) -> str:
    """The Wi-Fi signal icon for a strength of 0 to 100 (the same steps as gnome-control-center)."""
    if strength < 20:
        return "network-wireless-signal-none-symbolic"
    if strength < 40:
        return "network-wireless-signal-weak-symbolic"
    if strength < 50:
        return "network-wireless-signal-ok-symbolic"
    if strength < 80:
        return "network-wireless-signal-good-symbolic"
    return "network-wireless-signal-excellent-symbolic"


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/wireless-row.ui")
class WirelessRow(Adw.ActionRow):
    __gtype_name__ = "WirelessRow"

    signal_icon = Gtk.Template.Child()
    secure_icon = Gtk.Template.Child()
    connected_label = Gtk.Template.Child()

    # True from pressing the row until NetworkManager says the connection is up or has failed.
    _connecting = False

    def __init__(self, window, client, device: NM.DeviceWifi, ap, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.client = client
        self.ap = ap
        self.device = device
        self.refresh_ui()

        self.set_activatable(True)
        self.connect("activated", self.__show_connect_dialog)

    @property
    def ssid(self):
        ssid = self.ap.get_ssid()
        if ssid is not None:
            ssid = ssid.get_data().decode("utf-8")
        else:
            ssid = ""
        return ssid

    @property
    def signal_strength(self):
        return self.ap.get_strength()

    @property
    def connected(self):
        active_connection = self.device.get_active_connection()
        if active_connection is not None:
            if active_connection.get_id() == self.ssid:
                return True
        return False

    def refresh_ui(self):
        icon_name = signal_icon_name(self.signal_strength)

        self.set_title(self.ssid)
        self.signal_icon.set_from_icon_name(icon_name)
        secure, tooltip = self.__get_security()
        if secure is not None:
            if not secure:
                self.secure_icon.set_from_icon_name("warning-small-symbolic")
            else:
                self.secure_icon.set_from_icon_name(
                    "network-wireless-encrypted-symbolic"
                )

        self.secure_icon.set_visible(secure is not None)
        if tooltip is not None:
            self.secure_icon.set_tooltip_text(tooltip)

        if self._connecting:
            self.connected_label.set_label(_("Connecting…"))
            self.connected_label.set_visible(True)
        else:
            self.connected_label.set_label(_("Connected"))
            self.connected_label.set_visible(self.connected)

    def __get_security(self) -> tuple[bool | None, str | None]:
        flags = self.ap.get_flags()
        rsn_flags = self.ap.get_rsn_flags()
        wpa_flags = self.ap.get_wpa_flags()

        # Copying logic used in gnome-control-center because this is a mess
        if (
            not (flags & NM_802_11_AP_FLAGS_PRIVACY)
            and wpa_flags == NM_802_11_AP_SEC_NONE
            and rsn_flags == NM_802_11_AP_SEC_NONE
        ):
            return AP_SECURITY_TYPES["none"]
        elif (
            (flags & NM_802_11_AP_FLAGS_PRIVACY)
            and wpa_flags == NM_802_11_AP_SEC_NONE
            and rsn_flags == NM_802_11_AP_SEC_NONE
        ):
            return AP_SECURITY_TYPES["wep"]
        elif (
            (flags & NM_802_11_AP_FLAGS_PRIVACY)
            and wpa_flags != NM_802_11_AP_SEC_NONE
            and rsn_flags != NM_802_11_AP_SEC_NONE
        ):
            return AP_SECURITY_TYPES["wpa"]
        elif rsn_flags & NM_802_11_AP_SEC_KEY_MGMT_SAE:
            return AP_SECURITY_TYPES["sae"]
        elif rsn_flags & NM_802_11_AP_SEC_KEY_MGMT_OWE:
            return AP_SECURITY_TYPES["owe"]
        elif rsn_flags & NM_802_11_AP_SEC_KEY_MGMT_OWE_TM:
            return AP_SECURITY_TYPES["owe_tm"]
        else:
            return AP_SECURITY_TYPES["wpa2"]

    def __key_mgmt(self) -> str | None:
        """The key-mgmt value a new connection to this network needs: None for an open network, "none" for WEP,
        otherwise NetworkManager's name for the scheme ("wpa-psk", "sae", "owe", "wpa-eap")."""
        flags = self.ap.get_flags()
        both = self.ap.get_wpa_flags() | self.ap.get_rsn_flags()
        if both & (NM_802_11_AP_SEC_KEY_MGMT_802_1X | NM_802_11_AP_SEC_KEY_MGMT_EAP_SUITE_B_192):
            return "wpa-eap"
        if both & (NM_802_11_AP_SEC_KEY_MGMT_OWE | NM_802_11_AP_SEC_KEY_MGMT_OWE_TM):
            return "owe"
        if both & NM_802_11_AP_SEC_KEY_MGMT_PSK:
            # Also covers WPA2/WPA3 transition networks, which offer both.
            return "wpa-psk"
        if both & NM_802_11_AP_SEC_KEY_MGMT_SAE:
            return "sae"
        if both != NM_802_11_AP_SEC_NONE:
            return "wpa-psk"
        if flags & NM_802_11_AP_FLAGS_PRIVACY:
            return "none"
        return None

    @staticmethod
    def password_ok(key_mgmt: str | None, password: str) -> bool:
        """WPA personal keys are 8 to 63 characters, or 64 hex digits; WPA3 (SAE) and WEP only need something."""
        if key_mgmt == "wpa-psk":
            return 8 <= len(password) <= 64
        return len(password) > 0

    def __saved_connection(self):
        """A connection NetworkManager already has for this network's name, or None."""
        ssid = self.ap.get_ssid()
        if ssid is None:
            return None
        want = ssid.get_data()
        for conn in self.client.get_connections():
            setting = conn.get_setting_wireless()
            if setting is not None and setting.get_ssid() is not None and setting.get_ssid().get_data() == want:
                return conn
        return None

    def __build_connection(self, key_mgmt: str | None, password: str | None):
        connection = NM.SimpleConnection.new()
        s_con = NM.SettingConnection.new()
        s_con.set_property(NM.SETTING_CONNECTION_ID, self.ssid)
        s_con.set_property(NM.SETTING_CONNECTION_UUID, NM.utils_uuid_generate())
        s_con.set_property(NM.SETTING_CONNECTION_TYPE, NM.SETTING_WIRELESS_SETTING_NAME)
        connection.add_setting(s_con)

        s_wifi = NM.SettingWireless.new()
        s_wifi.set_property(NM.SETTING_WIRELESS_SSID, self.ap.get_ssid())
        s_wifi.set_property(NM.SETTING_WIRELESS_MODE, NM.SETTING_WIRELESS_MODE_INFRA)
        connection.add_setting(s_wifi)

        if key_mgmt is not None:
            s_sec = NM.SettingWirelessSecurity.new()
            s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, key_mgmt)
            if key_mgmt in ("wpa-psk", "sae"):
                s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, password)
            elif key_mgmt == "none":
                s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_WEP_KEY0, password)
                # 5 or 13 characters, or 10 or 26 hex digits, is the key itself; anything else is a passphrase.
                key_type = NM.WepKeyType.KEY if len(password) in (5, 10, 13, 26) else NM.WepKeyType.PASSPHRASE
                s_sec.set_property(NM.SETTING_WIRELESS_SECURITY_WEP_KEY_TYPE, key_type)
            connection.add_setting(s_sec)
        # IPv4 and IPv6 are left out: NetworkManager fills them in (automatic) when it adds the connection.
        return connection

    def __set_connecting(self, connecting: bool):
        self._connecting = connecting
        self.refresh_ui()

    def __show_connect_dialog(self, *args):
        if self.connected or self._connecting:
            return
        key_mgmt = self.__key_mgmt()
        if key_mgmt == "wpa-eap":
            self.__window.toast(
                _("Enterprise (802.1X) networks can't be set up in the installer. Use another network or a cable."),
                timeout=6,
            )
            return
        saved = self.__saved_connection()
        if saved is not None:
            self.__set_connecting(True)
            self.client.activate_connection_async(
                saved, self.device, self.ap.get_path(), None, self.__on_activated_saved, key_mgmt
            )
        elif key_mgmt in (None, "owe"):
            self.__add_and_activate(key_mgmt, None)
        else:
            self.__ask_password(key_mgmt)

    def __ask_password(self, key_mgmt: str, retry: bool = False):
        body = (
            _("That password did not work. Check it and try again.")
            if retry
            else _("Enter the password for this Wi-Fi network.")
        )
        dialog = Adw.AlertDialog.new(_("Connect to “{}”").format(self.ssid), body)
        entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        entry.set_property("placeholder-text", _("Password"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("connect", _("Connect"))
        dialog.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("connect")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("connect", False)

        sent = [False]

        def connect_once():
            if sent[0] or not self.password_ok(key_mgmt, entry.get_text()):
                return False
            sent[0] = True
            self.__add_and_activate(key_mgmt, entry.get_text())
            return True

        entry.connect(
            "changed", lambda e: dialog.set_response_enabled("connect", self.password_ok(key_mgmt, e.get_text()))
        )
        # Enter (on a hardware keyboard or the on-screen one) connects, as the button does.
        entry.connect("activate", lambda e: connect_once() and dialog.force_close())
        dialog.connect("response", lambda d, response: response == "connect" and connect_once())

        # The dialog sits inside the installer window, so the on-screen keyboard stays up and the window shrinks
        # to keep the dialog above it. The password field takes focus so the keys go there.
        dialog.present(self.__window)
        GLib.idle_add(lambda: entry.grab_focus() and False)
        if hasattr(self.__window, "request_keyboard"):
            self.__window.request_keyboard()

    def __add_and_activate(self, key_mgmt: str | None, password: str | None):
        self.__set_connecting(True)
        self.client.add_and_activate_connection_async(
            self.__build_connection(key_mgmt, password),
            self.device,
            self.ap.get_path(),
            None,
            self.__on_added,
            key_mgmt,
        )

    def __on_added(self, client, result, key_mgmt):
        try:
            active = client.add_and_activate_connection_finish(result)
        except GLib.Error as e:
            self.__on_start_failed(e)
            return
        self.__watch(active, key_mgmt)

    def __on_activated_saved(self, client, result, key_mgmt):
        try:
            active = client.activate_connection_finish(result)
        except GLib.Error as e:
            self.__on_start_failed(e)
            return
        self.__watch(active, key_mgmt)

    def __on_start_failed(self, error):
        logger.error("Could not connect to %s: %s", self.ssid, error.message)
        self.__set_connecting(False)
        self.__window.toast(_("Could not connect to {}: {}").format(self.ssid, error.message), timeout=6)

    def __watch(self, active, key_mgmt):
        """Follow the connection until it is up or has failed. A wrong password fails with "no secrets" (the live
        system has no password agent to ask again): forget that connection and ask for the password again."""
        handler = [None]

        def finish(state, reason):
            if state not in (NM.ActiveConnectionState.ACTIVATED, NM.ActiveConnectionState.DEACTIVATED):
                return
            if handler[0] is not None:
                active.disconnect(handler[0])
                handler[0] = None
            self.__set_connecting(False)
            if state == NM.ActiveConnectionState.ACTIVATED:
                logger.info("Connected to %s", self.ssid)
                self.__window.toast(_("Connected to {}").format(self.ssid))
                return
            logger.warning("Connection to %s failed (reason %s)", self.ssid, int(reason))
            bad_password = reason in (
                NM.ActiveConnectionStateReason.NO_SECRETS,
                NM.ActiveConnectionStateReason.LOGIN_FAILED,
            )
            if bad_password and key_mgmt not in (None, "owe"):
                remote = active.get_connection()
                if remote is not None:
                    remote.delete_async(None, None, None)
                self.__ask_password(key_mgmt, retry=True)
            else:
                self.__window.toast(_("Could not connect to {}").format(self.ssid), timeout=6)

        handler[0] = active.connect("state-changed", lambda ac, state, reason: finish(state, reason))
        # It may have come up before the handler was connected.
        if active.get_state() == NM.ActiveConnectionState.ACTIVATED:
            finish(NM.ActiveConnectionState.ACTIVATED, 0)


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-network.ui")
class BootcDefaultNetwork(Adw.Bin):
    __gtype_name__ = "BootcDefaultNetwork"

    wired_group = Gtk.Template.Child()
    wireless_group = Gtk.Template.Child()
    hidden_network_row = Gtk.Template.Child()
    proxy_settings_row = Gtk.Template.Child()
    advanced_group = Gtk.Template.Child()
    btn_next = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.__step_num = step["num"]
        try:
            self.__nm_client = NM.Client.new()
        except GLib.Error as e:
            # No NetworkManager (a dev container, a stripped image): pass over the page instead of failing the
            # installer. The page stays in the carousel: the steps after it find their place by position, and
            # removing it would shift them (the connection check would then fire on the image page).
            logger.warning("NetworkManager is not available (%s); the network page cannot list connections", e)
            self.__nm_client = None
            self.advanced_group.set_visible(False)
            self.wired_group.set_visible(False)
            self.wireless_group.add(Adw.ActionRow(
                title=_("Network settings are unavailable"),
                subtitle=_("NetworkManager is not running, so connections cannot be listed here."),
            ))
            self.btn_next.connect("clicked", self.__on_next_clicked)
            self.set_btn_next(True)
            return
        self.delta = False

        self.__devices = []
        self.__wired_children = []
        self.__wireless_children = {}

        # Prevent concurrency issues when re-scanning Wi-Fi devices.
        # Since we reload the list every time there's a state change,
        # there's a high change that it coincides with a periodic
        # refresh operation.
        self.__wifi_lock = Lock()

        # Since we have a dedicated page for checking connectivity,
        # we only need to make sure the user has some type of
        # connection set up, be it wired or wireless.
        self.has_eth_connection = False
        self.has_wifi_connection = False

        self.__get_network_devices()
        self.__start_auto_refresh()

        # "Connect to Hidden Network" and "Proxy Settings" rows have no
        # handler implementation yet. Keep the group hidden until they are built.
        self.advanced_group.set_visible(False)

        self.__nm_client.connect("device-added", self.__add_new_device)
        self.__nm_client.connect("device-added", self.__remove_device)
        self.btn_next.connect("clicked", self.__on_next_clicked)

    def __on_next_clicked(self, *args):
        """Continue once the image registry can be reached; otherwise stay on this page and say why. (This replaces
        a separate connection-check page that flashed by on its own when the check passed.)"""
        self.btn_next.set_sensitive(False)

        def reachable():
            # ghcr.io is where the images come from; 8.8.8.8:53 tells "no internet" apart from "ghcr.io blocked".
            for host, port in (("ghcr.io", 443), ("8.8.8.8", 53)):
                try:
                    socket.create_connection((host, port), timeout=5).close()
                    return True
                except OSError:
                    continue
            return False

        def done(ok, *args):
            self.btn_next.set_sensitive(True)
            if ok:
                self.__window.next()
            else:
                logger.error("Connection check failed: could not reach ghcr.io:443 or 8.8.8.8:53")
                self.__window.toast(_("No internet connection. Connect to a network, then press Next again."), timeout=6)

        RunAsync(reachable, done)

    @property
    def step_id(self):
        return self.__key

    def get_finals(self):
        return {}

    def set_btn_next(self, state: bool):
        if state:
            if not self.btn_next.has_css_class("suggested-action"):
                self.btn_next.add_css_class("suggested-action")
            self.btn_next.set_sensitive(True)
        else:
            if self.btn_next.has_css_class("suggested-action"):
                self.btn_next.remove_css_class("suggested-action")
            self.btn_next.set_sensitive(False)

    def __get_network_devices(self):
        devices = self.__nm_client.get_devices()
        eth_devices = 0
        wifi_devices = 0
        for device in devices:
            if device.is_real():
                device_type = device.get_device_type()
                if device_type == NM.DeviceType.ETHERNET:
                    self.__add_ethernet_connection(device)
                    eth_devices += 1
                elif device_type == NM.DeviceType.WIFI:
                    device.connect("state-changed", self.__on_state_changed)
                    self.has_wifi_connection = (
                        device.get_active_connection() is not None
                    )
                    self.__refresh_wifi_list(device)
                    wifi_devices += 1
                else:
                    continue

                self.__devices.append(device)

        self.wired_group.set_visible(eth_devices > 0)
        self.wireless_group.set_visible(wifi_devices > 0)

    def __add_new_device(self, client, device):
        self.__devices.append(device)

    def __remove_device(self, client, device):
        self.__devices.remove(device)

    def __on_state_changed(self, device, new_state, old_state, reason):
        self.has_wifi_connection = device.get_active_connection() is not None
        self.__refresh()

    def __refresh(self):
        for child in self.__wired_children:
            self.wired_group.remove(child)
        self.__wired_children = []

        self.has_eth_connection = False
        for device in self.__devices:
            device_type = device.get_device_type()
            if device_type == NM.DeviceType.ETHERNET:
                self.__add_ethernet_connection(device)
            elif device_type == NM.DeviceType.WIFI:
                self.__scan_wifi(device)

        self.set_btn_next(self.has_eth_connection or self.has_wifi_connection)
        return GLib.SOURCE_REMOVE

    def __start_auto_refresh(self):
        def run_async():
            return time.sleep(10)

        def callback(*args):
            self.__refresh()
            RunAsync(run_async, callback)

        RunAsync(run_async, callback)

    def __device_status(self, conn: NM.Device):
        connected = False
        match conn.get_state():
            case NM.DeviceState.ACTIVATED:
                status = _("Connected")
                connected = True
            case NM.DeviceState.NEED_AUTH:
                status = _("Authentication required")
            case (
                NM.DeviceState.PREPARE
                | NM.DeviceState.CONFIG
                | NM.DeviceState.IP_CONFIG
                | NM.DeviceState.IP_CHECK
                | NM.DeviceState.SECONDARIES
            ):
                status = _("Connecting")
            case NM.DeviceState.DISCONNECTED:
                status = _("Disconnected")
            case NM.DeviceState.DEACTIVATING:
                status = _("Disconnecting")
            case NM.DeviceState.FAILED:
                status = _("Connection Failed")
            case NM.DeviceState.UNKNOWN:
                status = _("Status Unknown")
            case NM.DeviceState.UNMANAGED:
                status = _("Unmanaged")
            case NM.DeviceState.UNAVAILABLE:
                status = _("Unavailable")
            case _:
                status = _("Unknown")

        return status, connected

    def __add_ethernet_connection(self, conn: NM.DeviceEthernet):
        status, connected = self.__device_status(conn)
        if connected:
            status += f" - {conn.get_speed()} Mbps"
            self.has_eth_connection = True

        # Wired devices with no cable plugged in are shown as unavailable
        if conn.get_state() == NM.DeviceState.UNAVAILABLE:
            status = _("Cable Unplugged")

        eth_conn = Adw.ActionRow(title=status)
        self.wired_group.add(eth_conn)
        self.__wired_children.append(eth_conn)

    def __poll_wifi_scan(self, conn: NM.DeviceWifi, last_known_scan: int):
        while conn.get_last_scan() == last_known_scan:
            time.sleep(0.25)

        GLib.idle_add(self.__refresh_wifi_list, conn)

    def __refresh_wifi_list(self, conn: NM.DeviceWifi):
        networks: dict[str, list[NM.AccessPoint]] = {}
        for ap in conn.get_access_points():
            if ap is None:
                continue

            ssid = ap.get_ssid()
            if ssid is None:
                continue

            ssid = ssid.get_data().decode("utf-8")
            if ssid in networks.keys():
                networks[ssid].append(ap)
            else:
                networks[ssid] = [ap]

        self.__wifi_lock.acquire()

        # Invalidate current list
        for ssid, (child, clean) in self.__wireless_children.items():
            self.__wireless_children[ssid] = (child, True)

        for ssid, aps in networks.items():
            max_strength = -1
            best_ap = None
            for ap in aps:
                ap_strength = ap.get_strength()
                if ap_strength > max_strength:
                    max_strength = ap_strength
                    best_ap = ap

            # Try to re-use entries with the same SSID
            if ssid in self.__wireless_children.keys():
                child = self.__wireless_children[ssid][0]
                child.ap = best_ap
                child.refresh_ui()
                self.__wireless_children[ssid] = (child, False)
                continue

            # Create new row if SSID is new
            wifi_network = WirelessRow(self.__window, self.__nm_client, conn, best_ap)
            self.wireless_group.add(wifi_network)
            self.__wireless_children[ssid] = (wifi_network, False)

        # Remove invalid rows
        invalid_ssids = []
        for ssid, (child, clean) in self.__wireless_children.items():
            self.wireless_group.remove(child)
            if clean:
                invalid_ssids.append(ssid)

        for ssid in invalid_ssids:
            del self.__wireless_children[ssid]

        for row in self.__sorted_wireless_children:
            self.wireless_group.add(row)

        self.__wifi_lock.release()

    def __scan_wifi(self, conn: NM.DeviceWifi):
        last_known_scan = conn.get_last_scan()
        conn.request_scan_async()

        t = Timer(1.5, self.__poll_wifi_scan, [conn, last_known_scan])
        t.start()

    @property
    def __sorted_wireless_children(self):
        def multisort(xs, specs):
            for key, reverse in reversed(specs):
                xs.sort(key=attrgetter(key), reverse=reverse)
            return xs

        # 1 - Is connected
        # 2 - Signal strength
        # 3 - Alphabetically
        return multisort(
            [it[0] for it in list(self.__wireless_children.values())],
            (("connected", True), ("signal_strength", True), ("ssid", True)),
        )
