from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMessageBox

from mailassist.config import load_settings
from mailassist.gui.bot_activity import (
    event_day_time_label,
    format_bot_log_for_humans,
    is_organizer_action,
    log_action_label,
    organizer_stop_message,
    read_bot_log_events,
    short_duration_label,
    user_facing_failure_message,
)
from mailassist.gui.bot_process import (
    BotActionRequest,
    build_bot_action_args,
    build_bot_process_environment,
)
from mailassist.gui.recent_activity import EMPTY_ACTIVITY_TEXT, RecentActivityPanel


class BotControllerMixin:
    def _append_recent_activity(self, message: str) -> None:
        if not hasattr(self, "recent_activity"):
            return
        if isinstance(self.activity_group, RecentActivityPanel):
            self.activity_group.append_message(message)
        else:
            if self.recent_activity.toPlainText().strip() == EMPTY_ACTIVITY_TEXT:
                self.recent_activity.clear()
            self.recent_activity.appendPlainText(message)
        self.last_activity_summary = message
        self.refresh_dashboard()

    def clear_recent_activity(self) -> None:
        if isinstance(self.activity_group, RecentActivityPanel):
            self.activity_group.clear_messages()
        else:
            self.recent_activity.setPlainText(EMPTY_ACTIVITY_TEXT)
        self.last_activity_summary = "Idle"
        self.refresh_dashboard()
        self._set_banner("Recent Activity cleared.", level="info")

    def _announce_long_action(self, message: str) -> None:
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def _reset_bot_progress(self) -> None:
        self.bot_progress = {
            "total": 0,
            "categorized": 0,
            "checked": 0,
            "drafts": 0,
            "draft_previews": 0,
            "skipped": 0,
            "already_handled": 0,
            "filtered": 0,
            "updated_messages": 0,
            "current_index": 0,
        }
        self.bot_progress["current_detail"] = ""

    def _bot_progress_summary(self) -> str:
        total = self.bot_progress.get("total", 0)
        categorized = self.bot_progress.get("categorized", 0)
        checked = self.bot_progress.get("checked", 0)
        drafts = self.bot_progress.get("drafts", 0)
        draft_previews = self.bot_progress.get("draft_previews", 0)
        skipped = self.bot_progress.get("skipped", 0)
        already_handled = self.bot_progress.get("already_handled", 0)
        filtered = self.bot_progress.get("filtered", 0)
        if self.current_bot_action in {"gmail-populate-labels", "outlook-populate-categories"}:
            current_index = int(self.bot_progress.get("current_index") or categorized or 0)
            if total:
                return f"{current_index}/{total} scanned · {categorized} categorized"
            return f"{categorized} scanned · {categorized} categorized"
        draft_total = drafts + draft_previews
        return f"{checked} scanned / {draft_total} drafts"

    def _start_bot_heartbeat(self, action: str, provider: str, *, dry_run: bool = False) -> None:
        self.bot_action_started_at = time.monotonic()
        self.current_bot_provider = provider
        self.current_bot_dry_run = dry_run
        self.current_bot_phase = "running"
        self.last_live_progress_summary = ""
        self._reset_bot_progress()
        if action in {"watch-once", "watch-loop", "gmail-populate-labels", "outlook-populate-categories"}:
            self._append_bot_heartbeat()
            self.bot_heartbeat_timer.start()
            if action == "watch-once" and dry_run:
                self.bot_timeout_timer.start(120000)

    def _stop_bot_heartbeat(self) -> None:
        self.bot_heartbeat_timer.stop()
        self.bot_timeout_timer.stop()
        self.bot_action_started_at = None

    def _append_bot_heartbeat(self) -> None:
        if self.bot_process is None or self.bot_action_started_at is None:
            self._stop_bot_heartbeat()
            return
        elapsed = short_duration_label(time.monotonic() - self.bot_action_started_at)
        provider = self.current_bot_provider.title() if self.current_bot_provider else "MailAssist"
        if self.current_bot_action == "watch-once":
            message = (
                f"{provider} preview still running after {elapsed}. "
                f"{self._bot_progress_summary()}. "
                "No email will be sent; auto-stops after 2 minutes."
            )
        elif self.current_bot_action == "watch-loop":
            if self.current_bot_phase == "waiting":
                summary = self.last_live_progress_summary or self._bot_progress_summary()
                message = f"{provider} auto-check idle for {elapsed}. Last pass: {summary}."
                self._set_banner(message, level="info")
                return
            else:
                message = f"{provider} auto-check checking after {elapsed}. {self._bot_progress_summary()}."
        else:
            message = f"{provider} action still running after {elapsed}. {self._bot_progress_summary()}."
        self._append_recent_activity(message)
        self._set_banner(message, level="info")

    def _stop_bot_after_timeout(self) -> None:
        if self.bot_process is None:
            self._stop_bot_heartbeat()
            return
        provider = self.current_bot_provider.title() if self.current_bot_provider else "MailAssist"
        self._append_recent_activity(
            f"{provider} preview stopped after 2 minutes. No email was sent."
        )
        self._set_banner(f"{provider} preview stopped after 2 minutes.", level="error")
        self.stop_bot_action()

    def refresh_bot_logs(self) -> None:
        self.bot_log_selector.blockSignals(True)
        self.bot_log_selector.clear()
        log_paths = sorted(
            self.settings.bot_logs_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in log_paths:
            self.bot_log_selector.addItem(self._bot_log_selector_label(path), str(path))
        self.bot_log_selector.blockSignals(False)
        self._refresh_summary_from_logs(log_paths)

        if self.latest_bot_log_path is not None:
            index = self.bot_log_selector.findData(str(self.latest_bot_log_path))
            if index >= 0:
                self.bot_log_selector.setCurrentIndex(index)
                self.load_selected_bot_log()
                return
        if self.bot_log_selector.count():
            self.bot_log_selector.setCurrentIndex(0)
            self.load_selected_bot_log()
        else:
            self.bot_log_viewer.clear()

    def _refresh_summary_from_logs(self, log_paths: list[Path]) -> None:
        latest_pass = ""
        latest_failure = ""
        for path in log_paths:
            events = read_bot_log_events(path)
            if not latest_pass:
                completed = next(
                    (event for event in reversed(events)
                     if event.get("type") == "completed" and "draft_count" in event),
                    None,
                )
                if completed:
                    when = event_day_time_label(completed.get("timestamp"))
                    latest_pass = (
                        f"{when} · {completed.get('draft_count', 0)} drafts · "
                        f"{completed.get('skipped_count', 0)} skipped · "
                        f"{completed.get('already_handled_count', 0)} already handled"
                    )
            if not latest_failure:
                err = next(
                    (event for event in reversed(events) if event.get("type") == "error"),
                    None,
                )
                if err:
                    when = event_day_time_label(err.get("timestamp"))
                    message = user_facing_failure_message(str(err.get("message") or "Bot error.").strip())
                    latest_failure = f"{when} · {message}"
            if latest_pass and latest_failure:
                break
        if latest_pass:
            self.last_pass_summary = latest_pass
        if latest_failure:
            self.last_failure_summary = latest_failure

    def _bot_log_selector_label(self, path: Path) -> str:
        events = read_bot_log_events(path)
        if not events:
            return path.name
        first = events[0]
        completed = next((event for event in reversed(events) if event.get("type") == "completed"), {})
        action = str(first.get("action") or path.name.removeprefix("bot-").split("-", 1)[0])
        pieces = [event_day_time_label(first.get("timestamp")), log_action_label(action)]
        provider = completed.get("provider")
        if provider:
            pieces.append(str(provider).title())
        if action == "watch-once" and completed:
            draft_count = int(completed.get("draft_count") or 0)
            skipped_count = int(completed.get("skipped_count") or 0)
            already_count = int(completed.get("already_handled_count") or 0)
            pieces.append(f"{draft_count} draft{'s' if draft_count != 1 else ''}")
            draft_ready_count = int(completed.get("draft_ready_count") or 0)
            if draft_ready_count:
                pieces.append(f"{draft_ready_count} dry run{'s' if draft_ready_count != 1 else ''}")
            if skipped_count:
                pieces.append(f"{skipped_count} skipped")
            if already_count:
                pieces.append(f"{already_count} already handled")
        elif action == "ollama-check":
            pieces.append("success" if completed else "running")
        elif completed and "message_count" in completed:
            pieces.append(f"{completed.get('message_count')} messages")
        elif completed and "processed_count" in completed:
            pieces.append(f"{completed.get('processed_count')} processed")
        if any(event.get("type") == "error" for event in events):
            pieces.append("error")
        return " - ".join(pieces)

    def run_gmail_draft_test(self) -> None:
        if self._main_bot_action_unavailable():
            return
        self._announce_long_action(
            "Previewing Gmail draft. Dry run only; no Gmail draft will be created. "
            "Heartbeat updates will appear here and the preview auto-stops after 2 minutes."
        )
        self.run_bot_action(
            "watch-once",
            provider="gmail",
            thread_id="thread-008",
            force=True,
            dry_run=True,
        )

    def run_controlled_gmail_draft(self) -> None:
        if self._main_bot_action_unavailable():
            return
        confirmation = self._confirm_action(
            "Create Controlled Gmail Draft",
            (
                "MailAssist will create one real Gmail draft addressed to your own Gmail account "
                "using sanitized mock content. Nothing will be sent. Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Controlled Gmail draft canceled.", level="info")
            return
        self._announce_long_action(
            "Creating one controlled Gmail test draft. This may take a minute; nothing will be sent."
        )
        self.run_bot_action("gmail-controlled-draft", provider="gmail", thread_id="thread-008")

    def run_outlook_draft_preview(self) -> None:
        if self._main_bot_action_unavailable():
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            "Previewing Outlook draft. Dry run only; no Outlook draft will be created. "
            "Heartbeat updates will appear here and the preview auto-stops after 2 minutes."
        )
        self.run_bot_action(
            "watch-once",
            provider="outlook",
            force=True,
            dry_run=True,
            limit=1,
        )

    def run_gmail_label_rescan(self) -> None:
        if self._main_bot_action_unavailable():
            return
        days = int(self.gmail_label_days_input.value()) if hasattr(self, "gmail_label_days_input") else 7
        confirmation = self._confirm_action(
            "Organize Gmail",
            (
                f"MailAssist will reclassify Gmail threads from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist labels.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Gmail label rescan canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            f"Organizing Gmail for the last {days} day{'' if days == 1 else 's'}. "
            "This can take a few minutes while the local model classifies messages."
        )
        self.run_bot_action(
            "gmail-populate-labels",
            provider="gmail",
            days=days,
            limit=500,
            apply_labels=True,
        )

    def run_outlook_category_rescan(self) -> None:
        if self._main_bot_action_unavailable():
            return
        days = (
            int(self.outlook_category_days_input.value())
            if hasattr(self, "outlook_category_days_input")
            else 25
        )
        confirmation = self._confirm_action(
            "Organize Outlook",
            (
                f"MailAssist will classify Outlook messages from the last {days} day"
                f"{'' if days == 1 else 's'} using the current category list. "
                "It may add, replace, or remove MailAssist Outlook categories.\n\n"
                "This can take a few minutes, but you can keep working while it runs. "
                "Continue?"
            ),
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            self._set_banner("Outlook category rescan canceled.", level="info")
            return
        self.save_settings(announce=False)
        self._announce_long_action(
            f"Organizing Outlook for the last {days} day{'' if days == 1 else 's'}. "
            "This can take a few minutes while the local model classifies messages."
        )
        self.run_bot_action(
            "outlook-populate-categories",
            provider="outlook",
            days=days,
            apply_categories=True,
        )

    def run_bot_action(
        self,
        action: str,
        *,
        thread_id: str = "",
        prompt: str = "",
        provider: str = "",
        force: bool = False,
        dry_run: bool = False,
        days: int | None = None,
        limit: int | None = None,
        apply_labels: bool = False,
        apply_categories: bool = False,
    ) -> None:
        if self._bot_action_already_running():
            return
        if action != "ollama-check" and self._bot_action_blocked_by_settings():
            return

        base_url, selected_model = self._current_bot_ollama_settings()
        self.bot_stdout_buffer = ""
        self.current_bot_action = action
        self.current_bot_provider = provider
        self.current_bot_dry_run = dry_run
        self._reset_bot_progress()
        request = BotActionRequest(
            action=action,
            base_url=base_url,
            selected_model=selected_model,
            thread_id=thread_id,
            prompt=prompt,
            provider=provider,
            force=force,
            dry_run=dry_run,
            apply_labels=apply_labels,
            apply_categories=apply_categories,
            days=days,
            limit=limit,
        )
        args = build_bot_action_args(request)

        self.bot_process = QProcess(self)
        self.bot_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.bot_process.setWorkingDirectory(str(self.settings.root_dir))
        self.bot_process.setProcessEnvironment(build_bot_process_environment(request))
        self.bot_process.readyReadStandardOutput.connect(self._handle_bot_stdout)
        self.bot_process.finished.connect(self._handle_bot_finished)

        self._append_bot_console(f"$ {sys.executable} {' '.join(args)}")
        self._set_banner(
            f"Starting bot action: {action}. Ollama work can take 1-2 minutes.",
            level="info",
        )
        self._set_bot_state("running")
        self._refresh_bot_action_controls()
        self._start_bot_heartbeat(action, provider, dry_run=dry_run)
        self.bot_process.start(sys.executable, args)

    def _handle_bot_stdout(self) -> None:
        if self.bot_process is None:
            return
        chunk = bytes(self.bot_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.bot_stdout_buffer += chunk
        while "\n" in self.bot_stdout_buffer:
            line, self.bot_stdout_buffer = self.bot_stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._append_bot_console(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_bot_event(event)

    def _handle_bot_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "log_file":
            self.latest_bot_log_path = Path(str(event.get("path")))
            self.refresh_bot_logs()
        elif event_type == "ollama_result":
            prompt = str(event.get("prompt", "")).strip()
            result = str(event.get("result", "")).strip()
            success = f"Test successful after {self._ollama_test_elapsed_label()}."
            self._stop_ollama_test_countdown()
            self.ollama_result_label.setText(success)
            if prompt:
                self._set_ollama_result_text(f"{success}\n\nPrompt: {prompt}\n\nResponse: {result}")
            else:
                self._set_ollama_result_text(f"{success}\n\nResponse: {result}")
            self._set_banner(success, level="info")
        elif event_type == "draft_created":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["drafts"] = self.bot_progress.get("drafts", 0) + 1
        elif event_type == "draft_ready":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["draft_previews"] = self.bot_progress.get("draft_previews", 0) + 1
        elif event_type == "skipped_email":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["skipped"] = self.bot_progress.get("skipped", 0) + 1
        elif event_type == "already_handled":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["already_handled"] = self.bot_progress.get("already_handled", 0) + 1
        elif event_type == "filtered_out":
            self.bot_progress["checked"] = self.bot_progress.get("checked", 0) + 1
            self.bot_progress["filtered"] = self.bot_progress.get("filtered", 0) + 1
        elif event_type in {
            "gmail_thread_labeled",
            "gmail_thread_label_preview",
            "outlook_thread_categorized",
            "outlook_thread_category_preview",
        }:
            self.bot_progress["categorized"] = self.bot_progress.get("categorized", 0) + 1
            self.bot_progress["updated_messages"] = (
                self.bot_progress.get("updated_messages", 0) + int(event.get("updated_message_count") or 0)
            )
        elif event_type in {
            "organize_phase",
            "gmail_thread_classification_started",
            "outlook_thread_classification_started",
        }:
            if "thread_count" in event:
                self.bot_progress["total"] = int(event.get("thread_count") or 0)
            if "current_index" in event:
                self.bot_progress["current_index"] = int(event.get("current_index") or 0)
            message = str(event.get("message") or "").strip()
            if event_type == "organize_phase":
                detail = message or "Preparing organizer run."
                self.bot_progress["current_detail"] = detail
                self._append_recent_activity(detail)
        elif event_type == "watch_pass_started":
            self.current_bot_phase = "running"
            self._reset_bot_progress()
            provider = str(event.get("provider") or self.current_bot_provider or "provider").title()
            self._append_recent_activity(f"{provider} auto-check pass started.")
        elif event_type == "watch_pass_completed":
            self.current_bot_phase = "waiting"
            self.last_live_progress_summary = self._bot_progress_summary()
            provider = str(event.get("provider") or self.current_bot_provider or "provider").title()
            self._append_recent_activity(
                f"{provider} auto-check pass completed: {self.last_live_progress_summary}. "
                "Idle until next check; Ollama is not drafting."
            )
        elif event_type == "failed_pass":
            self._append_recent_activity(f"Watch pass failed: {event.get('message', 'Unknown error')}")
        elif event_type == "sleeping":
            self.current_bot_phase = "waiting"
        elif event_type == "outlook_readiness":
            ready = bool(event.get("ready"))
            self.current_provider_ready = ready
            self.current_provider_readiness_message = str(event.get("message") or "").strip()
            if not ready:
                message = self.current_provider_readiness_message or "Outlook connection is not ready."
                self._append_recent_activity(f"Outlook connection failed: {message}")
                self.last_failure_summary = message
                self._set_banner(message, level="error")
        elif event_type == "completed":
            self._stop_bot_heartbeat()
            if event.get("action") != "ollama-check":
                self._set_banner(str(event.get("message", "Bot action completed.")), level="info")
            self.settings = load_settings()
            self.refresh_models()
            self.refresh_bot_logs()
            if "draft_count" in event:
                draft_count = event.get("draft_count", 0)
                draft_ready_count = event.get("draft_ready_count", 0)
                skipped_count = event.get("skipped_count", 0)
                already_count = event.get("already_handled_count", 0)
                filtered_count = event.get("filtered_out_count", 0)
                self.last_pass_summary = (
                    f"{draft_count} drafts · {draft_ready_count} dry runs · {skipped_count} skipped · "
                    f"{already_count} already handled · {filtered_count} filtered"
                )
                provider = str(event.get("provider") or "").strip()
                provider_label = provider.title() if provider else "Provider"
                prefix = (
                    f"{provider_label} preview completed"
                    if event.get("dry_run")
                    else f"{provider_label} watch pass completed"
                )
                self._append_recent_activity(f"{prefix}: {self.last_pass_summary}.")
            elif "thread_count" in event:
                provider = str(event.get("provider") or "").strip()
                provider_label = provider.title() if provider else "Provider"
                thread_count = int(event.get("thread_count") or 0)
                applied_count = int(event.get("applied_count") or 0)
                updated_messages = int(event.get("message_update_count") or 0)
                if event.get("ready") is False:
                    reason = str(self.current_provider_readiness_message or event.get("message") or "").strip()
                    if reason:
                        detail = organizer_stop_message(
                            provider_label,
                            reason,
                            categorized=0,
                            stage="before reading mail",
                        )
                    else:
                        detail = f"{provider_label} organize stopped before reading mail because the provider is not connected."
                    self.last_failure_summary = reason or "Provider is not connected."
                elif updated_messages:
                    detail = (
                        f"{provider_label} organize completed: {thread_count} emails categorized · "
                        f"{applied_count} category writes · {updated_messages} messages updated."
                    )
                else:
                    detail = (
                        f"{provider_label} organize completed: {thread_count} emails categorized · "
                        f"{applied_count} updates applied."
                    )
                self._append_recent_activity(detail)
            self.refresh_dashboard()
        elif event_type == "error":
            self._stop_bot_heartbeat()
            failure = user_facing_failure_message(str(event.get("message", "Bot action failed.")))
            provider = str(event.get("provider") or self.current_bot_provider or "").strip()
            provider_label = provider.title() if provider else "MailAssist"
            if self.current_bot_action == "watch-once" and self.current_bot_dry_run:
                self._append_recent_activity(f"{provider_label} preview failed: {failure}")
            elif is_organizer_action(str(event.get("action") or self.current_bot_action or "")):
                categorized = int(self.bot_progress.get("categorized", 0) or 0)
                self._append_recent_activity(
                    organizer_stop_message(provider_label, failure, categorized=categorized)
                )
            else:
                self._append_recent_activity(f"{provider_label} action failed: {failure}")
            if event.get("action") == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error", self._short_bot_error_label(failure, provider=provider))
        elif event_type == "info":
            if "thread_count" in event:
                self.bot_progress["total"] = int(event.get("thread_count") or 0)
            self._set_banner(str(event.get("message", "")), level="info")

    def _handle_bot_finished(self, exit_code: int, _exit_status) -> None:
        if self.bot_stdout_buffer.strip():
            self._append_bot_console(self.bot_stdout_buffer.strip())
            self.bot_stdout_buffer = ""
        self._stop_bot_heartbeat()
        finished_action = self.current_bot_action
        self.bot_process = None
        if hasattr(self, "stop_bot_button"):
            self.stop_bot_button.setEnabled(False)
        if exit_code != 0:
            if finished_action == "ollama-check":
                self._stop_ollama_test_countdown()
                self.ollama_result_label.setText(
                    f"Model test failed after {self._ollama_test_elapsed_label()}."
                )
            failure = f"Bot exited with code {exit_code}."
            self.last_failure_summary = failure
            self._set_banner(failure, level="error")
            self._set_bot_state("error")
        elif self.last_bot_state != "error":
            if finished_action == "ollama-check":
                self._stop_ollama_test_countdown()
            self._set_bot_state("idle")
        self.current_bot_action = ""
        self.current_bot_provider = ""
        self.current_bot_dry_run = False
        self.current_bot_phase = ""
        self.last_live_progress_summary = ""
        self.current_provider_ready = True
        self.current_provider_readiness_message = ""
        self.refresh_dashboard()
        self.refresh_bot_logs()

    def load_selected_bot_log(self, *_args: object) -> None:
        log_path_value = self.bot_log_selector.currentData()
        if not log_path_value:
            self.bot_log_viewer.clear()
            return
        log_path = Path(str(log_path_value))
        if not log_path.exists():
            self.bot_log_viewer.clear()
            self._set_banner("The selected bot log no longer exists.", level="error")
            return
        raw_text = log_path.read_text(encoding="utf-8")
        if self.show_raw_log_checkbox.isChecked():
            self.bot_log_viewer.setPlainText(raw_text)
            return
        self.bot_log_viewer.setPlainText(format_bot_log_for_humans(log_path, raw_text))

    def _format_bot_log_for_humans(self, path: Path, raw_text: str) -> str:
        return format_bot_log_for_humans(path, raw_text)
