"""Admin management without a database.

Owners come from env (ADMIN_IDS / OWNER_ID) and are permanent.
Extra admins are stored in a JSON file on disk (lost only on redeploy/restart).
"""

import json
import logging
from typing import Set

import config

logger = logging.getLogger(__name__)


def _load_extra() -> Set[int]:
    if not config.ADMINS_FILE.exists():
        return set()
    try:
        data = json.loads(config.ADMINS_FILE.read_text(encoding="utf-8"))
        return {int(x) for x in data if str(x).isdigit() or isinstance(x, int)}
    except Exception as exc:
        logger.warning("Could not load admins file: %s", exc)
        return set()


def _save_extra(ids: Set[int]) -> None:
    try:
        config.ADMINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.ADMINS_FILE.write_text(
            json.dumps(sorted(ids), indent=2),
            encoding="utf-8",
        )
    except Exception as exp:
        logger.error("Could not save admins file: %s", exp)


def get_all_admins() -> Set[int]:
    """Owners + extra admins."""
    return set(config.OWNER_IDS) | _load_extra()


def is_owner(user_id: int) -> bool:
    return user_id in config.OWNER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in get_all_admins()


def add_admin(user_id: int) -> bool:
    """Add an extra admin. Returns True if newly added."""
    if user_id in config.OWNER_IDS:
        return False
    extra = _load_extra()
    if user_id in extra:
        return False
    extra.add(user_id)
    _save_extra(extra)
    return True


def remove_admin(user_id: int) -> bool:
    """Remove an extra admin. Owners cannot be removed."""
    if user_id in config.OWNER_IDS:
        return False
    extra = _load_extra()
    if user_id not in extra:
        return False
    extra.discard(user_id)
    _save_extra(extra)
    return True


def list_admins_text() -> str:
    owners = sorted(config.OWNER_IDS)
    extra = sorted(_load_extra())
    lines = ["👑 *Owners* (from env)"]
    if owners:
        for oid in owners:
            lines.append(f"  • `{oid}`")
    else:
        lines.append("  _(none)_")
    lines.append("")
    lines.append("🛡️ *Extra Admins* (via bot)")
    if extra:
        for aid in extra:
            lines.append(f"  • `{aid}`")
    else:
        lines.append("  _(none)_")
    return "\n".join(lines)
