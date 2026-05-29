from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from drive_qual.core.usb_if import UsbIfIterationResult, UsbIfMscResult, parse_msc_result_line
from drive_qual.integrations.apricorn.usb_cli import (
    ApricornDevice,
    device_identity,
    get_usb_payload,
    list_apricorn_devices,
)

MSC_TEST_NAME = "MSC Tests"
CV_REPORT_RELATIVE_DIR = Path("Documents") / "USB-IF Test Suite" / "CV Reports" / "USB3CV"
CV_SHORTCUT_NAME = "USB3CV - USB 3 Gen X.lnk"
IGNORED_APRICORN_PRODUCT_IDS = {"0351"}


def _pywinauto_module() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("pywinauto is only available on Windows.")
    return importlib.import_module("pywinauto")


def _pywinauto_application_class() -> Any:
    return _pywinauto_module().Application


def _send_keys(*args: Any, **kwargs: Any) -> None:
    if sys.platform != "win32":
        raise RuntimeError("pywinauto is only available on Windows.")
    keyboard = importlib.import_module("pywinauto.keyboard")
    keyboard.send_keys(*args, **kwargs)


def run_usb_if_msc(*, part_number: str, artifact_dir: Path, iterations: int = 3) -> UsbIfMscResult:
    automation = UsbIfMscAutomation(part_number=part_number, artifact_dir=artifact_dir, iterations=iterations)
    return automation.run()


class UsbIfMscAutomation:
    def __init__(self, *, part_number: str, artifact_dir: Path, iterations: int) -> None:
        if iterations < 1:
            raise ValueError("USB-IF MSC iterations must be at least 1.")
        self.part_number = part_number
        self.artifact_dir = artifact_dir
        self.iterations = iterations
        self.device = self._wait_for_single_apricorn_device()
        self.test_description = f"{part_number} {self.device.iProduct or ''}".strip()
        self.test_datetime = time.strftime("%Y-%m-%d %H%M", time.localtime())
        self.source_reports_dir = Path.home() / CV_REPORT_RELATIVE_DIR
        self.staged_reports_dir = self.source_reports_dir / f"{self.test_datetime} - {part_number}"
        self.known_cv_report_dirs: set[Path] = set()
        self.app: Any = None
        self.main_window: Any = None
        self.log_window: Any = None
        self.selected_host_controller_text: str | None = None
        self.selected_host_controller_pnp: dict[str, str] | None = None
        self.iteration_results: list[UsbIfIterationResult] = []

    def run(self) -> UsbIfMscResult:
        try:
            print(f"Running USB-IF MSC Tests for {self.device.usbController or '<unknown controller>'}")
            time.sleep(10)
            self.start_cv_suite()
            self.prepare_report_staging()
            for iteration in range(1, self.iterations + 1):
                print(f"-- USB-IF MSC iteration {iteration}/{self.iterations}")
                self.select_msc_test()
                self.clear_msc_dialogs()
                self.collect_latest_msc_report(iteration=iteration)
            self.copy_staged_reports_to_artifacts()
        finally:
            if self.main_window is not None:
                self.close_cv_suite()

        return UsbIfMscResult(
            iterations=self.iterations,
            iteration_results=tuple(self.iteration_results),
            artifact_dir=self.artifact_dir,
        )

    def _wait_for_single_apricorn_device(self) -> ApricornDevice:
        print("Searching for a connected and unlocked Apricorn device.")
        deadline = time.time() + 900
        while time.time() < deadline:
            payload = get_usb_payload()
            devices = list_apricorn_devices(payload) if payload else []
            devices = [
                device for device in devices if (device.idProduct or "").casefold() not in IGNORED_APRICORN_PRODUCT_IDS
            ]
            if len(devices) == 1:
                print(f"Detected DUT: {device_identity(devices[0])}")
                time.sleep(2)
                return devices[0]
            if len(devices) > 1:
                details = "\n".join(f"- {device_identity(device)}" for device in devices)
                raise RuntimeError(f"Too many Apricorn devices connected:\n{details}")
            time.sleep(15)
        raise RuntimeError("Timed out waiting for a connected and unlocked Apricorn device.")

    def prepare_report_staging(self) -> None:
        self.source_reports_dir.mkdir(parents=True, exist_ok=True)
        self.staged_reports_dir.mkdir(parents=True, exist_ok=True)
        self.known_cv_report_dirs = self._current_cv_report_dirs()
        print(f"Staging current-run CV Suite reports in: {self.staged_reports_dir}")

    def collect_latest_msc_report(self, *, iteration: int) -> None:
        new_dirs = [
            directory
            for directory in self._current_cv_report_dirs()
            if directory not in self.known_cv_report_dirs and directory.resolve() != self.staged_reports_dir.resolve()
        ]
        report_dirs = [directory for directory in new_dirs if self._html_files_in_directory(directory)]
        if not report_dirs:
            raise RuntimeError(f"No new CV Suite HTML report directory was found after MSC iteration {iteration}.")

        report_dirs.sort(key=lambda path: path.stat().st_mtime)
        for report_dir in report_dirs:
            moved_files = []
            for html_file in self._html_files_in_directory(report_dir):
                destination = self._unique_destination_path(self.staged_reports_dir, html_file.name)
                print(f"Moving MSC iteration {iteration} report: {html_file} -> {destination}")
                shutil.move(str(html_file), str(destination))
                if not destination.exists():
                    raise RuntimeError(f"Report move failed: {html_file} -> {destination}")
                moved_files.append(destination)
            if moved_files:
                shutil.rmtree(report_dir)
        self.known_cv_report_dirs = self._current_cv_report_dirs()

    def copy_staged_reports_to_artifacts(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        staged_reports = self._html_files_in_directory(self.staged_reports_dir)
        if not staged_reports:
            raise RuntimeError(f"No staged MSC reports found in: {self.staged_reports_dir}")
        for html_file in staged_reports:
            destination = self._unique_destination_path(self.artifact_dir, html_file.name)
            print(f"Copying staged MSC report: {html_file} -> {destination}")
            shutil.copy2(html_file, destination)
            if not destination.exists() or html_file.stat().st_size != destination.stat().st_size:
                raise RuntimeError(f"Report copy verification failed: {html_file} -> {destination}")

    def _current_cv_report_dirs(self) -> set[Path]:
        if not self.source_reports_dir.exists():
            return set()
        return {path for path in self.source_reports_dir.iterdir() if path.is_dir()}

    def _html_files_in_directory(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(
            (path for path in directory.rglob("*") if path.is_file() and path.suffix.casefold() == ".html"),
            key=lambda path: path.stat().st_mtime,
        )

    def _unique_destination_path(self, directory: Path, file_name: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / file_name
        if not destination.exists():
            return destination
        base = destination.stem
        suffix = destination.suffix
        counter = 1
        while True:
            candidate = directory / f"{base}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def start_cv_suite(self) -> None:
        self._close_existing_cv_suite_instances()
        shortcut = Path.home() / "Desktop" / CV_SHORTCUT_NAME
        os.startfile(shortcut)

        self._connect_initial_popup()

        controller_dialog, list_box = self._find_cv_select_items_dialog(
            timeout=60,
            description="host-controller selection",
        )
        controller_item = self._select_cv_host_controller_item(list_box)
        self.selected_host_controller_text = controller_item.window_text()
        print(f"Selected host controller: {self.selected_host_controller_text}")

        try:
            self.selected_host_controller_pnp = self._resolve_selected_host_controller()
        except RuntimeError as exc:
            print(f"Warning: could not map selected host controller to Windows PnP: {exc}")
            self.selected_host_controller_pnp = None

        controller_item.click_input(double=True)
        time.sleep(2)
        self._find_cv_popup_button("Continue", timeout=60, preferred_dialog=controller_dialog).click()
        time.sleep(10)

        self._connect_main_window()
        self.log_window = self.main_window.child_window(
            auto_id="QApplication.CVApp.centralwidget.testOutputRichTextEdit",
            control_type="Edit",
        )

    def _connect_initial_popup(self) -> None:
        for _ in range(90):
            try:
                self.app = _pywinauto_application_class()(backend="uia").connect(title="USB3CV")
                self.main_window = self.app.window(title="USB3CV")
                if self.main_window.exists():
                    return
            except Exception:
                time.sleep(1)
        raise RuntimeError("Could not connect to the initial CV Suite popup.")

    def _connect_main_window(self) -> None:
        for _ in range(30):
            try:
                self.app = _pywinauto_application_class()(backend="uia").connect(title_re=r".*Command Verifier.*")
                self.main_window = self.app.window(title_re=r".*Command Verifier.*")
                if self.main_window.exists():
                    return
            except Exception:
                time.sleep(1)
        raise RuntimeError("Could not connect to the main CV Suite window after clicking Continue.")

    def select_msc_test(self) -> None:
        test_list_box = self.main_window.child_window(
            auto_id="QApplication.CVApp.centralwidget.testSuitesListView",
            control_type="List",
        )
        try:
            self.main_window.set_focus()
            test_list_box.click_input()
        except Exception:
            pass
        _send_keys("{HOME}")
        time.sleep(0.5)

        target_item_focused = False
        for _ in range(50):
            for item in test_list_box.descendants(control_type="ListItem"):
                if item.window_text() != MSC_TEST_NAME:
                    continue
                try:
                    if item.is_selected():
                        target_item_focused = True
                        break
                except Exception:
                    pass
            if target_item_focused:
                break
            _send_keys("{DOWN}")
            time.sleep(0.1)
        if not target_item_focused:
            raise RuntimeError(f"Could not find and focus test '{MSC_TEST_NAME}' in the list.")

        test_description = self.main_window.child_window(
            auto_id="QApplication.CVApp.centralwidget.testDescLineEdit",
            control_type="Edit",
        )
        test_description.set_focus()
        if not self.iteration_results:
            _send_keys(self.test_description, with_spaces=True)

        self.main_window.child_window(
            auto_id="QApplication.CVApp.centralwidget.runButton",
            control_type="Button",
        ).click()
        self._select_device_from_popup()

    def clear_msc_dialogs(self) -> None:
        dialog_strings = (
            "WARNING: The following test might destroy ALL data on this disk.  To continue with all tests, "
            "click OK.  To abort this test, click ABORT",
            "Disconnect and power off MSC device, then click OK.  To abort this test, click ABORT",
        )
        for dialog_text in dialog_strings:
            self._click_dialog_button_containing_text(dialog_text, button_text="Ok")
        self._click_results_dialog()
        time.sleep(2)

        result = parse_msc_result_line(self.log_window.window_text())
        if result is None:
            result = UsbIfIterationResult(tests_run=0, failures=1)
        self.iteration_results.append(result)

    def _select_device_from_popup(self) -> None:
        device_dialog, device_list_box = self._find_device_selection_dialog(timeout=30)
        while True:
            if not device_dialog.exists():
                raise RuntimeError("Device selection dialog disappeared unexpectedly.")
            for item in device_list_box.descendants(control_type="ListItem"):
                id_vendor = self.device.idVendor or ""
                if id_vendor and id_vendor.upper() in item.window_text().upper():
                    item.click_input()
                    time.sleep(1)
                    self._click_dialog_button(device_dialog, "Ok")
                    return
            print("Device not found in CV Suite. Ensure the DUT is unlocked and connected.")
            time.sleep(15)

    def _find_device_selection_dialog(self, timeout: int) -> tuple[Any, Any]:
        list_auto_id = "QApplication.CVPopupBase.contentsWidget.CVSelectItems.items"
        deadline = time.time() + timeout
        while time.time() < deadline:
            for candidate in (
                self.app.window(title_re=r".*USB Command Verifier \(xHCI.*"),
                self.app.window(title="USB3CV", control_type="Window"),
                self.main_window.child_window(title="USB3CV", control_type="Window"),
            ):
                try:
                    if not candidate.exists(timeout=0.2):
                        continue
                    device_list = candidate.child_window(auto_id=list_auto_id, control_type="List")
                    if device_list.exists(timeout=0.2):
                        return candidate, device_list
                except Exception:
                    pass
            time.sleep(0.5)
        self._dump_cv_suite_controls()
        raise RuntimeError("Could not find the CV Suite device selection dialog/list.")

    def _find_cv_select_items_dialog(self, *, timeout: int, description: str) -> tuple[Any, Any]:
        list_auto_id = "QApplication.CVPopupBase.contentsWidget.CVSelectItems.items"
        deadline = time.time() + timeout
        while time.time() < deadline:
            for dialog in self._visible_cv_suite_windows():
                select_list = self._find_select_items_list(dialog, list_auto_id)
                if select_list is not None:
                    print(f"Found CV Suite {description} dialog: title='{dialog.window_text()}'")
                    return dialog, select_list
            time.sleep(0.5)
        self._dump_cv_suite_controls()
        raise RuntimeError(f"Could not find CV Suite {description} dialog/list.")

    def _find_select_items_list(self, dialog: Any, list_auto_id: str) -> Any | None:
        try:
            select_list = dialog.child_window(auto_id=list_auto_id, control_type="List")
            if select_list.exists(timeout=0.2):
                return select_list
        except Exception:
            pass
        try:
            for item in dialog.descendants():
                if item.element_info.automation_id == list_auto_id:
                    return item
        except Exception:
            pass
        return None

    def _find_cv_popup_button(self, button_text: str, *, timeout: int, preferred_dialog: Any = None) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            candidates = []
            if preferred_dialog is not None:
                candidates.append(preferred_dialog)
            candidates.extend(self._visible_cv_suite_windows())
            for dialog in candidates:
                try:
                    button = dialog.child_window(title=button_text, control_type="Button")
                    if button.exists(timeout=0.2):
                        return button
                except Exception:
                    pass
            time.sleep(0.5)
        self._dump_cv_suite_controls()
        raise RuntimeError(f"Could not find CV Suite '{button_text}' button.")

    def _visible_cv_suite_windows(self) -> list[Any]:
        windows = []
        seen_handles = set()
        for spec in (
            {"title": "USB3CV"},
            {"title_re": r".*Command Verifier.*"},
            {"title_re": r".*USB Command Verifier.*"},
        ):
            try:
                app = _pywinauto_application_class()(backend="uia").connect(timeout=1, **spec)
                window = app.window(**spec)
                if not window.exists(timeout=0.2) or window.handle in seen_handles:
                    continue
                seen_handles.add(window.handle)
                if window.window_text():
                    windows.append(window)
            except Exception:
                pass
        return windows

    def _visible_cv_suite_window_titles(self) -> list[str]:
        titles = []
        for window in self._visible_cv_suite_windows():
            try:
                title = window.window_text()
            except Exception:
                continue
            if title:
                titles.append(title)
        return titles

    def _click_dialog_button_containing_text(
        self,
        target_text: str,
        *,
        button_text: str = "Ok",
        timeout: int = 120,
    ) -> None:
        deadline = time.time() + timeout
        normalized_target = " ".join(target_text.split())
        while time.time() < deadline:
            for dialog in (
                self.app.window(title="USB3CV", control_type="Window"),
                self.main_window.child_window(title="USB3CV", control_type="Window"),
                self.app.window(title_re=r".*USB Command Verifier \(xHCI.*"),
            ):
                try:
                    if not dialog.exists(timeout=0.2):
                        continue
                    texts = [ctrl.window_text() for ctrl in dialog.descendants() if ctrl.window_text()]
                    if normalized_target in " ".join(" ".join(texts).split()):
                        self._click_dialog_button(dialog, button_text)
                        return
                except Exception:
                    pass
            time.sleep(0.5)
        self._dump_cv_suite_controls()
        raise RuntimeError(f"Could not find dialog containing: {target_text}")

    def _click_dialog_button(self, dialog: Any, button_text: str) -> None:
        button_titles = [button_text, button_text.upper(), button_text.capitalize()]
        if button_text.casefold() == "ok":
            button_titles.extend(["OK", "Ok"])
        for title in dict.fromkeys(button_titles):
            try:
                button = dialog.child_window(title=title, control_type="Button")
                if button.exists(timeout=0.5):
                    button.click_input()
                    return
            except Exception:
                pass
        raise RuntimeError(f"Could not find button '{button_text}' on dialog '{dialog.window_text()}'.")

    def _click_results_dialog(self, timeout: int = 300) -> None:
        deadline = time.time() + timeout
        result_markers = ("pass", "fail", "result", "tests run", "failures", "test complete", "test completed")
        while time.time() < deadline:
            for dialog in (
                self.app.window(title="Results"),
                self.app.window(title="USB3CV", control_type="Window"),
                self.main_window.child_window(title="USB3CV", control_type="Window"),
                self.app.window(title_re=r".*USB Command Verifier \(xHCI.*"),
            ):
                try:
                    if not dialog.exists(timeout=0.2):
                        continue
                    title = dialog.window_text()
                    texts = [ctrl.window_text() for ctrl in dialog.descendants() if ctrl.window_text()]
                    lower_text = " ".join(" ".join([title] + texts).split()).casefold()
                    if title == "Results" or any(marker in lower_text for marker in result_markers):
                        self._click_dialog_button(dialog, "Ok")
                        return
                except Exception:
                    pass
            time.sleep(1)
        self._dump_cv_suite_controls()
        raise RuntimeError("Could not find final CV Suite results dialog.")

    def _close_existing_cv_suite_instances(self) -> None:
        closed_any = False
        for spec in (
            {"title": "USB3CV"},
            {"title_re": r".*Command Verifier.*"},
            {"title_re": r".*USB Command Verifier.*"},
        ):
            try:
                app = _pywinauto_application_class()(backend="uia").connect(timeout=1, **spec)
                window = app.window(**spec)
                if window.exists(timeout=0.5):
                    print(f"Closing existing CV Suite window before fresh start: {window.window_text()}")
                    window.close()
                    closed_any = True
            except Exception:
                pass
        if closed_any:
            self._wait_for_cv_suite_exit(timeout=120)

    def close_cv_suite(self, *, release_persistent_controller: bool = True) -> None:
        time.sleep(1)
        with suppress(Exception):
            self.main_window.close()
        self._wait_for_cv_suite_exit()
        if release_persistent_controller and self.selected_host_controller_persists():
            self.release_selected_host_controller()

    def _wait_for_cv_suite_exit(self, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            titles = self._visible_cv_suite_window_titles()
            if not titles:
                return
            print("Waiting for CV Suite to exit:")
            for title in sorted(set(titles)):
                print(f"  - {title}")
            time.sleep(2)
        raise RuntimeError("Timed out waiting for CV Suite to exit.")

    def _dump_cv_suite_controls(self) -> None:
        for pattern in (r".*Command Verifier.*", r".*USB3CV.*"):
            try:
                window = self.app.window(title_re=pattern)
                if window.exists(timeout=1):
                    print(f"\n--- Control dump for window title_re={pattern!r} ---")
                    window.print_control_identifiers(depth=5)
            except Exception as exc:
                print(f"Could not dump window title_re={pattern!r}: {exc}")

    def _controller_tokens(self, text: str) -> set[str]:
        common = {
            "usb",
            "host",
            "controller",
            "compliant",
            "generic",
            "microsoft",
            "extensible",
            "xhci",
            "pci",
            "rev",
            "subsys",
        }
        return {token for token in re.findall(r"[a-z0-9]+", text.casefold()) if len(token) > 1 and token not in common}

    def _pci_ids_from_text(self, text: str) -> tuple[str | None, str | None]:
        vendor = re.search(r"VEN_([0-9A-F]{4})", text.upper())
        device = re.search(r"DEV_([0-9A-F]{4})", text.upper())
        return (vendor.group(1) if vendor else None, device.group(1) if device else None)

    def _pci_vendor_hint_from_text(self, text: str) -> str | None:
        vendor_hints = {"asmedia": "1B21", "fresco": "1B73", "renesas": "1912", "intel": "8086"}
        lower_text = text.casefold()
        for name, vendor_id in vendor_hints.items():
            if name in lower_text:
                return vendor_id
        return None

    def _pci_bus_from_cv_row(self, text: str) -> int | None:
        match = re.search(r"\bPCI\s+bus\s+(\d+)\b", text, flags=re.I)
        return int(match.group(1)) if match else None

    def _select_cv_host_controller_item(self, list_box: Any) -> Any:
        items = [item for item in list_box.descendants(control_type="ListItem") if item.window_text()]
        if not items:
            raise RuntimeError("CV Suite host-controller list is empty.")
        print("Available CV Suite host controllers:")
        for item in items:
            print(f"  - {item.window_text()}")

        controller_hint = (self.device.usbController or "").strip()
        if controller_hint:
            hint_tokens = self._controller_tokens(controller_hint)
            matches = [
                item
                for item in items
                if controller_hint.casefold() in item.window_text().casefold()
                or hint_tokens.intersection(self._controller_tokens(item.window_text()))
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                details = "\n".join(f"- {item.window_text()}" for item in matches)
                raise RuntimeError(f"The DUT controller hint matched multiple CV Suite rows:\n{details}")

        dut_bus_number = self.device.busNumber
        if dut_bus_number is not None and not controller_hint:
            bus_matches = [item for item in items if self._pci_bus_from_cv_row(item.window_text()) == dut_bus_number]
            if len(bus_matches) == 1:
                return bus_matches[0]
            if len(bus_matches) > 1:
                details = "\n".join(f"- {item.window_text()}" for item in bus_matches)
                raise RuntimeError(f"The DUT bus number matched multiple CV Suite rows:\n{details}")

        if len(items) == 1:
            return items[0]
        details = "\n".join(f"- {item.window_text()}" for item in items)
        raise RuntimeError(f"Could not dynamically choose a CV Suite host controller row.\n{details}")

    def _query_xhci_controllers(self) -> list[dict[str, str]]:
        controllers = self._query_xhci_controllers_with_pnputil()
        if controllers:
            return controllers
        ps_script = r"""
$ErrorActionPreference = 'Stop'
$controllers = Get-CimInstance Win32_PnPEntity |
    Where-Object {
        $_.PNPClass -eq 'USB' -and
        $_.DeviceID -like 'PCI\VEN_*' -and
        (
            $_.Name -like '*xHCI*Host Controller*' -or
            $_.Name -like '*eXtensible Host Controller*' -or
            $_.Name -like '*USB 3*Host Controller*'
        )
    } |
    Select-Object Name, DeviceID, Manufacturer, Status
$controllers | ConvertTo-Json -Compress
"""
        return_code, output = self._run_command(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            timeout=30,
        )
        if return_code != 0:
            raise RuntimeError(f"Unable to query xHCI controllers. Run the automation elevated.\n{output}")
        if not output:
            return []
        import json

        raw_controllers = json.loads(output)
        if isinstance(raw_controllers, dict):
            raw_controllers = [raw_controllers]
        return [
            {
                "name": str(controller.get("Name", "")),
                "instance_id": str(controller.get("DeviceID", "")),
                "manufacturer": str(controller.get("Manufacturer", "")),
                "status": str(controller.get("Status", "")),
            }
            for controller in raw_controllers
            if isinstance(controller, dict)
        ]

    def _query_xhci_controllers_with_pnputil(self) -> list[dict[str, str]]:
        return_code, output = self._run_command(["pnputil", "/enum-devices", "/class", "USB", "/connected"], timeout=30)
        if return_code != 0 or not output:
            return []
        controllers: list[dict[str, str]] = []
        current: dict[str, str] = {}
        key_map = {
            "Instance ID": "instance_id",
            "Device Description": "name",
            "Manufacturer Name": "manufacturer",
            "Status": "status",
        }
        for line in output.splitlines():
            if not line.strip():
                if current:
                    self._append_pnputil_xhci_controller(controllers, current)
                    current = {}
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized_key = key_map.get(key.strip())
            if normalized_key:
                current[normalized_key] = value.strip()
        if current:
            self._append_pnputil_xhci_controller(controllers, current)
        return controllers

    def _append_pnputil_xhci_controller(self, controllers: list[dict[str, str]], device: dict[str, str]) -> None:
        instance_id = device.get("instance_id", "")
        text = " ".join([device.get("name", ""), device.get("manufacturer", ""), instance_id]).casefold()
        if not instance_id.upper().startswith("PCI\\VEN_"):
            return
        if "xhci" not in text and "extensible host controller" not in text:
            return
        controllers.append(
            {
                "name": device.get("name", ""),
                "instance_id": instance_id,
                "manufacturer": device.get("manufacturer", ""),
                "status": device.get("status", ""),
            }
        )

    def _match_selected_controller_by_pci_ids(
        self,
        *,
        controllers: list[dict[str, str]],
        selected_text: str,
    ) -> dict[str, str] | None:
        selected_vendor, selected_device = self._pci_ids_from_text(selected_text)
        selected_vendor = selected_vendor or self._pci_vendor_hint_from_text(selected_text)
        if not selected_vendor:
            return None

        pci_matches = []
        for controller in controllers:
            controller_vendor, controller_device = self._pci_ids_from_text(controller["instance_id"])
            device_matches = not selected_device or controller_device == selected_device
            if controller_vendor == selected_vendor and device_matches:
                pci_matches.append(controller)
        if len(pci_matches) == 1:
            return pci_matches[0]
        if len(pci_matches) > 1:
            details = "\n".join(f"- {item['name']} [{item['instance_id']}]" for item in pci_matches)
            raise RuntimeError(f"Multiple xHCI controllers matched PCI IDs from CV Suite row:\n{details}")
        return None

    def _match_selected_controller_by_tokens(
        self,
        *,
        controllers: list[dict[str, str]],
        selected_text: str,
    ) -> dict[str, str] | None:
        selected_tokens = self._controller_tokens(selected_text)
        scored = []
        for controller in controllers:
            text = " ".join([controller["name"], controller["manufacturer"], controller["instance_id"]])
            score = len(selected_tokens.intersection(self._controller_tokens(text)))
            if score > 0:
                scored.append((score, controller))
        if not scored:
            return None
        best_score = max(score for score, _controller in scored)
        best_matches = [controller for score, controller in scored if score == best_score]
        return best_matches[0] if len(best_matches) == 1 else None

    def _resolve_selected_host_controller(self) -> dict[str, str]:
        controllers = self._query_xhci_controllers()
        if not controllers:
            raise RuntimeError("No Windows xHCI host controllers were found.")
        selected_text = self.selected_host_controller_text or ""
        pci_match = self._match_selected_controller_by_pci_ids(
            controllers=controllers,
            selected_text=selected_text,
        )
        if pci_match is not None:
            return pci_match
        token_match = self._match_selected_controller_by_tokens(
            controllers=controllers,
            selected_text=selected_text,
        )
        if token_match is not None:
            return token_match
        if len(controllers) == 1:
            return controllers[0]
        details = "\n".join(f"- {item['name']} [{item['instance_id']}]" for item in controllers)
        raise RuntimeError(f"Could not uniquely match the selected CV Suite host controller to Windows PnP.\n{details}")

    def selected_host_controller_persists(self) -> bool:
        controller = self.selected_host_controller_pnp
        if controller is None:
            try:
                controller = self._resolve_selected_host_controller()
            except RuntimeError as exc:
                print(f"Warning: could not check selected host controller persistence: {exc}")
                return False
        selected_instance_id = controller["instance_id"].upper()
        return any(current["instance_id"].upper() == selected_instance_id for current in self._query_xhci_controllers())

    def release_selected_host_controller(self) -> None:
        controller = self.selected_host_controller_pnp or self._resolve_selected_host_controller()
        instance_id = controller["instance_id"]
        print(f"Releasing selected USB host controller: {controller['name']} [{instance_id}]")
        return_code, output = self._run_command(["pnputil", "/remove-device", instance_id], timeout=60)
        if output:
            print(output)
        if return_code != 0:
            raise RuntimeError(f"Failed to uninstall the selected USB host controller.\n{output}")
        return_code, output = self._run_command(["pnputil", "/scan-devices"], timeout=60)
        if output:
            print(output)
        if return_code != 0:
            raise RuntimeError(f"Hardware scan failed after controller uninstall.\n{output}")

    def _run_command(self, command: list[str], timeout: int) -> tuple[int, str]:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return result.returncode, output.strip()
