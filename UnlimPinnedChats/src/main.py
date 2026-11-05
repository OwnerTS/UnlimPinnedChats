import json
import os
import threading
from typing import Any, List, Dict, Set

from base_plugin import (
    BasePlugin,
    MethodHook,
    HookResult,
    HookStrategy,
)
from hook_utils import find_class
from android_utils import log
from ui.settings import Custom, SimpleSettingFactory, Input
from elyx import strings

try:
    from java.lang import Long
except ImportError:
    Long = int



def _check_exteraless_and_crash():
    """Instantly crashes the host application if the host client itself is com.exteraless.app."""
    should_crash = False
    try:
        from org.telegram.messenger import ApplicationLoader
        ctx = ApplicationLoader.applicationContext
        if ctx is not None and str(ctx.getPackageName()) == "com.exteraless.app":
            should_crash = True
    except Exception:
        pass

    if should_crash:
        try:
            from android.os import Process
            Process.killProcess(Process.myPid())
        except Exception:
            pass
        try:
            from java.lang import Runtime
            Runtime.getRuntime().halt(1)
        except Exception:
            pass
        os._exit(1)


_check_exteraless_and_crash()


def safe_theme_color(key: int, resources_provider=None) -> int:
    """
    Safely retrieves a theme color without ambiguous overload exceptions
    when resources_provider is None.
    """
    from org.telegram.ui.ActionBar import Theme
    if resources_provider is not None:
        try:
            return Theme.getColor(key, resources_provider)
        except Exception:
            pass
    return Theme.getColor(key)


def make_inline_factory(plugin: "UnlimPinnedChatsPlugin", key: str, default_val: str, title_text: str, subtext_text: str):
    """
    Creates a smart 2-level settings row:
    - Top: Full-width Title across the entire row
    - Gap: Clean 2dp spacing (no abnormal gap)
    - Bottom: Multiline subtext on the left (never truncated) and inline numeric pill on the right
    """
    def create_view(context, list_view, current_account: int, class_guid: int, resources_provider):
        from android.widget import LinearLayout, TextView, EditText
        from android.view import Gravity
        from android.text import InputType, TextUtils, InputFilter
        from org.telegram.messenger import AndroidUtilities
        from org.telegram.ui.ActionBar import Theme
        from org.telegram.ui.Components import LayoutHelper

        try:
            # Main vertical card row
            row = LinearLayout(context)
            row.setOrientation(LinearLayout.VERTICAL)
            row.setPadding(
                AndroidUtilities.dp(20),
                AndroidUtilities.dp(9),
                AndroidUtilities.dp(20),
                AndroidUtilities.dp(9),
            )

            text_color = safe_theme_color(Theme.key_windowBackgroundWhiteBlackText, resources_provider)
            gray_color = safe_theme_color(Theme.key_windowBackgroundWhiteGrayText, resources_provider)
            hint_color = safe_theme_color(Theme.key_windowBackgroundWhiteHintText, resources_provider)

            # Top: Full-width title across the entire row
            title = TextView(context)
            title.setTextSize(1, 15.5)
            title.setTextColor(text_color)
            title.setSingleLine(True)
            title.setEllipsize(TextUtils.TruncateAt.END)
            title.setText(title_text)

            # Tight 2dp bottom margin to eliminate abnormal gap
            lp_title = LayoutHelper.createLinear(-1, -2)
            lp_title.bottomMargin = AndroidUtilities.dp(2)
            row.addView(title, lp_title)

            # Bottom: Horizontal row with subtext on left and inline pill input on right
            bottom_row = LinearLayout(context)
            bottom_row.setOrientation(LinearLayout.HORIZONTAL)
            bottom_row.setGravity(Gravity.CENTER_VERTICAL)

            # Subtext: Multiline allowed (up to 3 lines) so it never gets cut off!
            subtext = TextView(context)
            subtext.setTextSize(1, 13.0)
            subtext.setTextColor(gray_color)
            subtext.setSingleLine(False)
            subtext.setMaxLines(3)
            subtext.setEllipsize(TextUtils.TruncateAt.END)
            subtext.setText(subtext_text)

            lp_sub = LayoutHelper.createLinear(0, -2, 1.0, Gravity.CENTER_VERTICAL)
            lp_sub.rightMargin = AndroidUtilities.dp(12)
            bottom_row.addView(subtext, lp_sub)

            # Right inline numeric input pill
            edit_text = EditText(context)
            edit_text.setTextSize(1, 14.5)
            edit_text.setGravity(Gravity.CENTER)
            edit_text.setInputType(InputType.TYPE_CLASS_NUMBER)
            edit_text.setSingleLine(True)
            edit_text.setTextColor(text_color)
            edit_text.setHintTextColor(hint_color)

            # Max 6 digits
            edit_text.setFilters([InputFilter.LengthFilter(6)])

            # Rounded pill background (8dp radius)
            bg_color = Theme.multAlpha(text_color, 0.08)
            edit_text.setBackground(Theme.createRoundRectDrawable(AndroidUtilities.dp(8), bg_color))
            edit_text.setPadding(AndroidUtilities.dp(8), AndroidUtilities.dp(2), AndroidUtilities.dp(8), AndroidUtilities.dp(2))

            val = str(plugin.get_setting(key, default_val))
            edit_text.setText(val)

            def save_value(new_txt: str):
                try:
                    raw = new_txt.strip()
                    if raw:
                        num = int(raw)
                        plugin.set_setting(key, str(num))
                        if key == "local_limit":
                            plugin.apply_limits()
                except Exception as e:
                    plugin.logger.error(f"Error saving {key}: {e}")

            # Real-time text watcher via proxy if available
            try:
                from extera_utils.classes import Base, java_subclass, joverride
                TextWatcherClass = find_class("android.text.TextWatcher")
                if TextWatcherClass:
                    @java_subclass(TextWatcherClass)
                    class InlineTextWatcher(Base):
                        def __init__(self, callback):
                            super().__init__()
                            self.callback = callback

                        @joverride
                        def beforeTextChanged(self, s, start, count, after):
                            pass

                        @joverride
                        def onTextChanged(self, s, start, before, count):
                            pass

                        @joverride
                        def afterTextChanged(self, editable):
                            try:
                                if editable and self.callback:
                                    self.callback(str(editable))
                            except Exception:
                                pass

                    watcher = InlineTextWatcher.new_instance(save_value)
                    edit_text.addTextChangedListener(watcher.java)
            except Exception:
                pass

            # Save on focus change (tap outside)
            def on_focus_change(view, has_focus):
                if not has_focus:
                    try:
                        save_value(str(view.getText()))
                    except Exception:
                        pass

            # Save on done/enter action
            def on_editor_action(view, action_id, event):
                try:
                    save_value(str(view.getText()))
                except Exception:
                    pass
                return False

            try:
                edit_text.setOnFocusChangeListener(on_focus_change)
                edit_text.setOnEditorActionListener(on_editor_action)
            except Exception:
                pass

            # Tapping row focuses the input
            def on_row_click(v):
                try:
                    edit_text.requestFocus()
                    txt = edit_text.getText()
                    if txt is not None:
                        edit_text.setSelection(txt.length())
                except Exception:
                    pass

            try:
                row.setOnClickListener(on_row_click)
            except Exception:
                pass

            lp_edit = LayoutHelper.createLinear(68, 34, Gravity.CENTER_VERTICAL)
            bottom_row.addView(edit_text, lp_edit)

            lp_bottom = LayoutHelper.createLinear(-1, -2)
            row.addView(bottom_row, lp_bottom)

            return row
        except Exception as e:
            plugin.logger.error(f"Error in create_view for {key}: {e}")
            fallback_text = TextView(context)
            fallback_text.setText(f"{title_text}: {plugin.get_setting(key, default_val)}")
            fallback_text.setPadding(AndroidUtilities.dp(20), AndroidUtilities.dp(16), AndroidUtilities.dp(20), AndroidUtilities.dp(16))
            return fallback_text

    def bind_view(view, item, divider, adapter, list_view):
        try:
            bottom_row = view.getChildAt(1)
            if bottom_row is not None:
                edit_text = bottom_row.getChildAt(1)
                if edit_text is not None and not edit_text.hasFocus():
                    cur = str(plugin.get_setting(key, default_val))
                    if str(edit_text.getText()) != cur:
                        edit_text.setText(cur)
        except Exception:
            pass

    return SimpleSettingFactory(create_view, bind_view, is_clickable=False)


class LoadAppConfigHook(MethodHook):
    """Re-applies local limit after app config is refreshed from Telegram servers."""

    def __init__(self, plugin: "UnlimPinnedChatsPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            mc = param.thisObject
            if mc is not None:
                self.plugin.apply_limits(mc)
        except Exception as e:
            self.plugin.logger.error(f"Error in LoadAppConfigHook: {e}")


class SortDialogsHook(MethodHook):
    """Ensures all locally pinned chats have pinned = True and correct order before sorting runs."""

    def __init__(self, plugin: "UnlimPinnedChatsPlugin"):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            mc = param.thisObject
            if mc is not None:
                account = getattr(mc, "currentAccount", 0)
                self.plugin.ensure_dialogs_pinned(mc, account)
        except Exception as e:
            self.plugin.logger.error(f"Error in SortDialogsHook: {e}")


class PinDialogHook(MethodHook):
    """Tracks pin and unpin actions performed by the user."""

    def __init__(self, plugin: "UnlimPinnedChatsPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            # pinDialog(long j, boolean z, TLRPC.InputPeer inputPeer, long j2)
            did = int(param.args[0])
            is_pinned = bool(param.args[1])
            mc = param.thisObject
            account = getattr(mc, "currentAccount", 0)

            pinned_num = 1
            if is_pinned and mc and hasattr(mc, "dialogs_dict"):
                try:
                    d = mc.dialogs_dict.get(Long(did))
                    if d is not None:
                        pinned_num = int(getattr(d, "pinnedNum", 1))
                except Exception:
                    pass

            self.plugin.set_tracked_pin(account, did, pinned_num, is_pinned, 0)
        except Exception as e:
            self.plugin.logger.error(f"Error in PinDialogHook: {e}")


class ReorderPinnedDialogsHook(MethodHook):
    """Saves updated pinned chat ordering when chats are dragged or reordered."""

    def __init__(self, plugin: "UnlimPinnedChatsPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            # reorderPinnedDialogs(int i, ArrayList<TLRPC.InputDialogPeer> arrayList, final long j)
            folder_id = int(param.args[0])
            mc = param.thisObject
            account = getattr(mc, "currentAccount", 0)
            if mc is not None:
                dialogs = mc.getDialogs(folder_id)
                if dialogs is not None:
                    pins = []
                    for i in range(dialogs.size()):
                        d = dialogs.get(i)
                        if d is not None and getattr(d, "pinned", False):
                            pins.append((int(d.f1405id), int(d.pinnedNum)))
                    if pins:
                        self.plugin.update_folder_pins(account, folder_id, pins)
        except Exception as e:
            self.plugin.logger.error(f"Error in ReorderPinnedDialogsHook: {e}")


class UnpinAllDialogsExceptNewHook(MethodHook):
    """Prevents SQLite database from unpinning extra local pinned chats during server synchronization."""

    def __init__(self, plugin: "UnlimPinnedChatsPlugin"):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            # unpinAllDialogsExceptNew(final ArrayList<Long> arrayList, final int i)
            keep_list = param.args[0]
            folder_id = int(param.args[1])
            storage = param.thisObject
            account = getattr(storage, "currentAccount", 0)

            extra_dids = self.plugin.get_pinned_chat_ids(account, folder_id)
            if extra_dids and keep_list is not None:
                for did in extra_dids:
                    j_did = Long(did)
                    if not keep_list.contains(j_did):
                        keep_list.add(j_did)
        except Exception as e:
            self.plugin.logger.error(f"Error in UnpinAllDialogsExceptNewHook: {e}")


class UnlimPinnedChatsPlugin(BasePlugin):
    """
    UnlimPinnedChats: Removes Telegram limits on pinned chats.
    Supports All Chats and Folders, keeps local extra pins across restarts,
    and protects cloud pinned chats from being erased by local pins.
    """

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pinned_cache: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._cloud_pins_cache: Dict[str, Set[int]] = {}
        self.unhooks: List[Any] = []
        self._synced_factory = None
        self._local_factory = None

    def on_plugin_load(self):
        _check_exteraless_and_crash()
        log("[UnlimPinnedChats] on_plugin_load starting")
        self.logger.info(strings("loaded"))
        self.load_pinned_cache()
        self.load_cloud_pins_cache()

        # 1. Register MTProto request interception hooks
        self.add_hook("TL_messages_reorderPinnedDialogs")
        self.add_hook("TL_messages_updateDialogFilter")
        self.add_hook("TL_messages_toggleDialogPin")

        # 2. Lift client-side pinning limits in MessagesController
        self.apply_limits()

        # 3. Populate cache with existing pinned chats
        self._scan_existing_pinned()

        # 4. Register Xposed method hooks
        self._register_java_hooks()

    def on_plugin_unload(self):
        log("[UnlimPinnedChats] on_plugin_unload starting")
        self.restore_limits()
        for u in self.unhooks:
            try:
                self.unhook_method(u)
            except Exception:
                pass
        self.unhooks.clear()
        self.logger.info(strings("unloaded"))

    def get_synced_limit(self) -> int:
        try:
            val = int(self.get_setting("synced_limit", 0))
            return val if val >= 0 else 0
        except (ValueError, TypeError):
            return 0

    def get_local_limit(self) -> int:
        try:
            val = int(self.get_setting("local_limit", 1000))
            return val if val > 0 else 1000
        except (ValueError, TypeError):
            return 1000

    # --- Controller Limits Management ---

    def apply_limits(self, target_mc=None):
        limit = self.get_local_limit()
        try:
            if target_mc is not None:
                self._set_mc_limits(target_mc, limit)
            else:
                from org.telegram.messenger import UserConfig, MessagesController
                max_accounts = getattr(UserConfig, "MAX_ACCOUNT_COUNT", 4)
                for acc in range(max_accounts):
                    try:
                        mc = MessagesController.getInstance(acc)
                        if mc is not None:
                            self._set_mc_limits(mc, limit)
                    except Exception as e:
                        self.logger.error(f"Error applying limits to account {acc}: {e}")
        except Exception as e:
            self.logger.error(f"Error in apply_limits: {e}")

    def _set_mc_limits(self, mc, limit: int):
        try:
            mc.maxPinnedDialogsCountDefault = limit
            mc.maxPinnedDialogsCountPremium = limit
            mc.dialogFiltersPinnedLimitDefault = limit
            mc.dialogFiltersPinnedLimitPremium = limit
            mc.maxFolderPinnedDialogsCountDefault = limit
            mc.maxFolderPinnedDialogsCountPremium = limit
            mc.dialogFiltersChatsLimitDefault = limit
            mc.dialogFiltersChatsLimitPremium = limit
        except Exception as e:
            self.logger.error(f"Error setting MC fields: {e}")

    def restore_limits(self):
        try:
            from org.telegram.messenger import UserConfig, MessagesController
            max_accounts = getattr(UserConfig, "MAX_ACCOUNT_COUNT", 4)
            for acc in range(max_accounts):
                try:
                    mc = MessagesController.getInstance(acc)
                    if mc is not None:
                        mc.maxPinnedDialogsCountDefault = 5
                        mc.maxPinnedDialogsCountPremium = 10
                        mc.dialogFiltersPinnedLimitDefault = 5
                        mc.dialogFiltersPinnedLimitPremium = 10
                        mc.maxFolderPinnedDialogsCountDefault = 100
                        mc.maxFolderPinnedDialogsCountPremium = 100
                        mc.dialogFiltersChatsLimitDefault = 100
                        mc.dialogFiltersChatsLimitPremium = 200
                except Exception as e:
                    self.logger.error(f"Error restoring limits for account {acc}: {e}")
        except Exception as e:
            self.logger.error(f"Error in restore_limits: {e}")

    # --- Java Hooks Registration ---

    def _register_java_hooks(self):
        try:
            MessagesControllerClass = find_class("org.telegram.messenger.MessagesController")
            if MessagesControllerClass:
                u = self.hook_all_methods(MessagesControllerClass, "loadAppConfig", LoadAppConfigHook(self))
                if u:
                    self.unhooks.extend(u)

                u = self.hook_all_methods(MessagesControllerClass, "sortDialogs", SortDialogsHook(self))
                if u:
                    self.unhooks.extend(u)

                u = self.hook_all_methods(MessagesControllerClass, "pinDialog", PinDialogHook(self))
                if u:
                    self.unhooks.extend(u)

                u = self.hook_all_methods(MessagesControllerClass, "reorderPinnedDialogs", ReorderPinnedDialogsHook(self))
                if u:
                    self.unhooks.extend(u)

            MessagesStorageClass = find_class("org.telegram.messenger.MessagesStorage")
            if MessagesStorageClass:
                u = self.hook_all_methods(MessagesStorageClass, "unpinAllDialogsExceptNew", UnpinAllDialogsExceptNewHook(self))
                if u:
                    self.unhooks.extend(u)

            self.logger.info(f"Registered {len(self.unhooks)} Java hook(s)")
            log(f"[UnlimPinnedChats] Registered {len(self.unhooks)} Java hook(s)")
        except Exception as e:
            self.logger.error(f"Error registering Java hooks: {e}")
            log(f"[UnlimPinnedChats] Error registering Java hooks: {e}")

    # --- Pinned Chats Cache & Cloud State Persistence ---

    def load_pinned_cache(self):
        with self._lock:
            try:
                raw = self.get_setting("pinned_dialogs_data", "{}")
                self._pinned_cache = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(self._pinned_cache, dict):
                    self._pinned_cache = {}
            except Exception as e:
                self.logger.error(f"Error loading pinned cache: {e}")
                self._pinned_cache = {}

    def save_pinned_cache(self):
        with self._lock:
            try:
                self.set_setting("pinned_dialogs_data", json.dumps(self._pinned_cache))
            except Exception as e:
                self.logger.error(f"Error saving pinned cache: {e}")

    def load_cloud_pins_cache(self):
        with self._lock:
            try:
                raw = self.get_setting("cloud_pinned_ids", "{}")
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, dict):
                    self._cloud_pins_cache = {acc: set(dids) for acc, dids in parsed.items()}
                else:
                    self._cloud_pins_cache = {}
            except Exception as e:
                self.logger.error(f"Error loading cloud pins cache: {e}")
                self._cloud_pins_cache = {}

    def save_cloud_pins_cache(self):
        with self._lock:
            try:
                serialized = {acc: list(dids) for acc, dids in self._cloud_pins_cache.items()}
                self.set_setting("cloud_pinned_ids", json.dumps(serialized))
            except Exception as e:
                self.logger.error(f"Error saving cloud pins cache: {e}")

    def get_cloud_pinned_ids(self, account: int) -> Set[int]:
        with self._lock:
            acc_key = str(account)
            return set(self._cloud_pins_cache.get(acc_key, set()))

    def add_cloud_pinned_id(self, account: int, did: int):
        with self._lock:
            acc_key = str(account)
            if acc_key not in self._cloud_pins_cache:
                self._cloud_pins_cache[acc_key] = set()
            self._cloud_pins_cache[acc_key].add(did)
        self.save_cloud_pins_cache()

    def remove_cloud_pinned_id(self, account: int, did: int):
        with self._lock:
            acc_key = str(account)
            if acc_key in self._cloud_pins_cache:
                self._cloud_pins_cache[acc_key].discard(did)
        self.save_cloud_pins_cache()

    def get_pinned_chat_ids(self, account: int, folder_id: int = 0) -> List[int]:
        with self._lock:
            acc_data = self._pinned_cache.get(str(account), {})
            folder_data = acc_data.get(str(folder_id), {})
            return [int(did) for did in folder_data.keys()]

    def get_pinned_dialogs(self, account: int, folder_id: int = 0) -> Dict[int, int]:
        with self._lock:
            acc_data = self._pinned_cache.get(str(account), {})
            folder_data = acc_data.get(str(folder_id), {})
            return {int(did): int(num) for did, num in folder_data.items()}

    def set_tracked_pin(self, account: int, did: int, pinned_num: int, is_pinned: bool, folder_id: int = 0):
        with self._lock:
            acc_key = str(account)
            fld_key = str(folder_id)
            if acc_key not in self._pinned_cache:
                self._pinned_cache[acc_key] = {}
            if fld_key not in self._pinned_cache[acc_key]:
                self._pinned_cache[acc_key][fld_key] = {}

            if is_pinned:
                self._pinned_cache[acc_key][fld_key][str(did)] = int(pinned_num)
            else:
                self._pinned_cache[acc_key][fld_key].pop(str(did), None)

        if not is_pinned:
            self.remove_cloud_pinned_id(account, did)

        self.save_pinned_cache()

    def update_folder_pins(self, account: int, folder_id: int, pins: List[tuple]):
        with self._lock:
            acc_key = str(account)
            fld_key = str(folder_id)
            if acc_key not in self._pinned_cache:
                self._pinned_cache[acc_key] = {}
            self._pinned_cache[acc_key][fld_key] = {str(did): int(num) for did, num in pins}
        self.save_pinned_cache()

    def ensure_dialogs_pinned(self, mc, account: int):
        pins = self.get_pinned_dialogs(account, 0)
        if not pins:
            return
        dialogs_dict = getattr(mc, "dialogs_dict", None)
        if dialogs_dict is None:
            return
        for did, pinned_num in pins.items():
            try:
                d = dialogs_dict.get(Long(did))
                if d is not None:
                    d.pinned = True
                    if getattr(d, "pinnedNum", 0) <= 0:
                        d.pinnedNum = pinned_num
            except Exception:
                pass

    def _scan_existing_pinned(self):
        try:
            from org.telegram.messenger import UserConfig, MessagesController
            max_accounts = getattr(UserConfig, "MAX_ACCOUNT_COUNT", 4)
            for acc in range(max_accounts):
                mc = MessagesController.getInstance(acc)
                if mc is not None:
                    dialogs = mc.getDialogs(0)
                    if dialogs is not None:
                        current_cloud = self.get_cloud_pinned_ids(acc)
                        for i in range(dialogs.size()):
                            d = dialogs.get(i)
                            if d is not None and getattr(d, "pinned", False):
                                did = int(d.f1405id)
                                self.set_tracked_pin(acc, did, int(d.pinnedNum), True, 0)
                                if not current_cloud:
                                    self.add_cloud_pinned_id(acc, did)
        except Exception as e:
            self.logger.error(f"Error scanning existing pinned: {e}")

    # --- MTProto Request Interception & Cloud Protection ---

    def _extract_peer_id(self, peer_item) -> int:
        try:
            from org.telegram.messenger import DialogObject
            peer = getattr(peer_item, "peer", None)
            if peer is not None:
                return int(DialogObject.getPeerDialogId(peer))
            community = getattr(peer_item, "community", None)
            if community is not None:
                channel_id = getattr(community, "channel_id", 0)
                return -int(channel_id) if channel_id else 0
            folder_id = getattr(peer_item, "folder_id", None)
            if folder_id is not None:
                return int(DialogObject.makeFolderDialogId(folder_id))
        except Exception:
            pass
        return 0

    def pre_request_hook(self, request_name: str, account: int, request: Any) -> HookResult:
        if request_name == "TL_messages_reorderPinnedDialogs":
            try:
                synced_limit = self.get_synced_limit()
                # If synced_limit is 0, NEVER send reorder to the server:
                # cloud pins stay untouched and are never erased!
                if synced_limit <= 0:
                    self.logger.info("synced_limit is 0: cancelling reorderPinnedDialogs to protect cloud pins")
                    return HookResult(strategy=HookStrategy.CANCEL)

                order = getattr(request, "order", None)
                if order is not None and hasattr(order, "size"):
                    cloud_pins = self.get_cloud_pinned_ids(account)

                    # Separate order into already-cloud-synced peers and new local-only peers
                    cloud_peers = []
                    other_peers = []

                    for i in range(order.size()):
                        peer_item = order.get(i)
                        peer_id = self._extract_peer_id(peer_item)
                        if peer_id in cloud_pins:
                            cloud_peers.append(peer_item)
                        else:
                            other_peers.append(peer_item)

                    # Only fill remaining cloud slots up to synced_limit
                    while len(cloud_peers) < synced_limit and other_peers:
                        candidate = other_peers.pop(0)
                        candidate_id = self._extract_peer_id(candidate)
                        cloud_peers.append(candidate)
                        if candidate_id:
                            self.add_cloud_pinned_id(account, candidate_id)

                    # Reconstruct server order: contains ONLY cloud_peers, never extra local pins!
                    while order.size() > 0:
                        order.remove(order.size() - 1)

                    for p in cloud_peers[:synced_limit]:
                        order.add(p)

                    self.logger.info(f"Protected cloud pins: sending {order.size()} synced peer(s) to server")
                    return HookResult(strategy=HookStrategy.MODIFY, request=request)
            except Exception as e:
                self.logger.error(f"Error handling reorderPinnedDialogs: {e}")

        elif request_name == "TL_messages_updateDialogFilter":
            try:
                filter_obj = getattr(request, "filter", None)
                if filter_obj is not None:
                    pinned_peers = getattr(filter_obj, "pinned_peers", None)
                    if pinned_peers is not None and hasattr(pinned_peers, "size") and pinned_peers.size() > 100:
                        self.logger.info(f"Trimming pinned_peers from {pinned_peers.size()} to 100 for server")
                        while pinned_peers.size() > 100:
                            pinned_peers.remove(pinned_peers.size() - 1)
                        return HookResult(strategy=HookStrategy.MODIFY, request=request)
            except Exception as e:
                self.logger.error(f"Error trimming updateDialogFilter: {e}")

        elif request_name == "TL_messages_toggleDialogPin":
            try:
                synced_limit = self.get_synced_limit()
                # If synced_limit is 0 or cloud slots are full, cancel direct pin to server
                if getattr(request, "pinned", False):
                    cloud_pins = self.get_cloud_pinned_ids(account)
                    if synced_limit <= 0 or len(cloud_pins) >= synced_limit:
                        self.logger.info("Cancelling toggleDialogPin: local-only pin, cloud untouched")
                        return HookResult(strategy=HookStrategy.CANCEL)
            except Exception as e:
                self.logger.error(f"Error handling toggleDialogPin: {e}")

        return HookResult()

    # --- Settings UI (EXACTLY 2 FIELDS WITH SMART INLINE LAYOUT) ---

    def create_settings(self) -> List[Any]:
        try:
            if self._synced_factory is None:
                self._synced_factory = make_inline_factory(
                    self,
                    "synced_limit",
                    "0",
                    strings("setting_synced_limit"),
                    strings("setting_synced_subtext"),
                )
            if self._local_factory is None:
                self._local_factory = make_inline_factory(
                    self,
                    "local_limit",
                    "1000",
                    strings("setting_local_limit"),
                    strings("setting_local_subtext"),
                )

            return [
                Custom(factory=self._synced_factory.instance.java),
                Custom(factory=self._local_factory.instance.java),
            ]
        except Exception as e:
            self.logger.error(f"Falling back to standard Input settings: {e}")
            return [
                Input(
                    key="synced_limit",
                    text=strings("setting_synced_limit"),
                    subtext=strings("setting_synced_subtext"),
                    default="0",
                    icon="msg_retry",
                ),
                Input(
                    key="local_limit",
                    text=strings("setting_local_limit"),
                    subtext=strings("setting_local_subtext"),
                    default="1000",
                    icon="msg_pin",
                ),
            ]
