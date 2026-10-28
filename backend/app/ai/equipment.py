"""Canonical equipment names and aliases shared by parsing and matching.

Resources store free-form Chinese feature labels, so the AI layer keeps a
small canonical vocabulary and resolves it against real labels at query time.
"""

CANONICAL_EQUIPMENT: tuple[str, ...] = (
    "投影仪",
    "视频会议",
    "白板",
    "电视",
    "隔音",
    "白噪音",
)

EQUIPMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "投影仪": ("投影仪", "投影机", "投影", "投屏", "投景仪", "投景"),
    "视频会议": ("视频会议", "视频会仪", "视频", "videoconference", "video"),
    "白板": ("白板", "白班", "白版"),
    "电视": ("电视", "显示屏", "显示器"),
    "隔音": ("隔音",),
    "白噪音": ("白噪音", "白噪声"),
}


def canonicalize_equipment(text: str) -> list[str]:
    """Return canonical equipment names mentioned in ``text`` in stable order."""
    lowered = text.lower()
    found: list[str] = []
    for name in CANONICAL_EQUIPMENT:
        aliases = EQUIPMENT_ALIASES[name]
        if any(alias.lower() in lowered for alias in aliases):
            found.append(name)
    return found


def feature_matches(required: str, feature: str) -> bool:
    """Whether a stored resource feature satisfies a canonical requirement."""
    aliases = EQUIPMENT_ALIASES.get(required, (required,))
    normalized = feature.strip().lower()
    if not normalized:
        return False
    return any(
        alias.lower() in normalized or normalized in alias.lower() for alias in aliases
    )


def resource_satisfies(features: list[str], required: list[str]) -> bool:
    return all(
        any(feature_matches(item, feature) for feature in features) for item in required
    )
