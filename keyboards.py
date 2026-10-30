"""Reply and inline keyboards for a premium UI."""

from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)


# Sidebar / Bot menu commands (shown when user types /)
BOT_COMMANDS = [
    BotCommand("start", "🏠 Main menu"),
    BotCommand("split", "✂️ Split video into parts"),
    BotCommand("merge", "🔗 Merge clips"),
    BotCommand("timeline", "🎞 Cut time ranges"),
    BotCommand("download", "⬇️ Download link → MP4"),
    BotCommand("cancel", "❌ Cancel current job"),
    BotCommand("help", "📖 Help & guide"),
    BotCommand("admins", "👥 List admins"),
    BotCommand("addadmin", "➕ Add admin (owner)"),
    BotCommand("removeadmin", "➖ Remove admin (owner)"),
]


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard – always visible at the bottom."""
    keyboard = [
        [KeyboardButton("✂️ Split"), KeyboardButton("🔗 Merge")],
        [KeyboardButton("🎞 Timeline"), KeyboardButton("⬇️ Download")],
        [KeyboardButton("📖 Help"), KeyboardButton("❌ Cancel")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Choose a tool or type a command…",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Cancel")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def timeline_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✂️ Cut Timeline Ranges", callback_data="timeline_cut")],
    ])


def confirm_inline(yes_data: str, no_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=yes_data),
            InlineKeyboardButton("❌ Cancel", callback_data=no_data),
        ]
    ])
