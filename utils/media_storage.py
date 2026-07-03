from pathlib import Path


def normalize_media_reference(stored_value, media_type=None):
    """Normalize a stored media reference into a route-relative path."""
    if not stored_value:
        return None

    value = str(stored_value).strip().replace("\\", "/")
    if not value:
        return None

    if value.startswith(("http://", "https://")):
        return value

    if value.startswith("/media/"):
        value = value[len("/media/"):]

    if value.startswith("/"):
        value = value[1:]

    filename = Path(value).name

    if value.startswith("static/uploads/avatars/") or value.startswith("uploads/avatars/"):
        return f"avatars/{filename}"

    if value.startswith("static/uploads/"):
        return f"logos/{filename}" if media_type == "logo" else f"avatars/{filename}" if media_type == "avatar" else filename

    if value.startswith("uploads/"):
        return f"logos/{filename}" if media_type == "logo" else f"avatars/{filename}" if media_type == "avatar" else filename

    if value.startswith("logos/") or value.startswith("avatars/"):
        return value

    if media_type == "logo":
        return f"logos/{filename}"
    if media_type == "avatar":
        return f"avatars/{filename}"
    return value


def legacy_media_relative_path(normalized_path, media_type=None):
    """Map a normalized media path back to the legacy static/uploads layout."""
    if not normalized_path:
        return None

    relative_path = str(normalized_path).strip().replace("\\", "/")
    filename = Path(relative_path).name

    if media_type == "avatar" or relative_path.startswith("avatars/"):
        return f"uploads/avatars/{filename}"

    if media_type == "logo" or relative_path.startswith("logos/"):
        return f"uploads/{filename}"

    return f"uploads/{relative_path}"


def resolve_media_file_path(stored_value, media_type, upload_root, app_root):
    """Return the first existing file path for a stored media reference."""
    normalized_path = normalize_media_reference(stored_value, media_type)
    if not normalized_path or normalized_path.startswith(("http://", "https://")):
        return None

    upload_candidate = Path(upload_root) / normalized_path
    if upload_candidate.is_file():
        return str(upload_candidate)

    legacy_relative_path = legacy_media_relative_path(normalized_path, media_type)
    if legacy_relative_path:
        legacy_candidate = Path(app_root) / "static" / legacy_relative_path
        if legacy_candidate.is_file():
            return str(legacy_candidate)

    return None
