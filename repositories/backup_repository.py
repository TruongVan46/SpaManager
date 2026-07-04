import os
import json

class BackupRepository:
    """Repository class responsible for low-level I/O of backup metadata JSON file."""
    
    @staticmethod
    def get_metadata_path(app):
        backup_dir = app.config.get('BACKUP_FOLDER') or os.path.join(app.root_path, 'backup')
        os.makedirs(backup_dir, exist_ok=True)
        return os.path.join(backup_dir, 'metadata.json')

    @staticmethod
    def get_legacy_metadata_path(app):
        legacy_backup_dir = os.path.join(app.root_path, 'backup')
        primary_backup_dir = app.config.get('BACKUP_FOLDER') or os.path.join(app.root_path, 'backup')
        if os.path.abspath(legacy_backup_dir) == os.path.abspath(primary_backup_dir):
            return None
        return os.path.join(legacy_backup_dir, 'metadata.json')

    @classmethod
    def _metadata_paths(cls, app):
        paths = [cls.get_metadata_path(app)]
        legacy_path = cls.get_legacy_metadata_path(app)
        if legacy_path:
            paths.append(legacy_path)
        return paths

    @classmethod
    def load_all(cls, app):
        """Load all backup metadata. Key is UUID, value is dictionary."""
        merged = {}
        for path in cls._metadata_paths(app):
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    merged.update(loaded)
            except Exception:
                continue
        return merged

    @classmethod
    def save_all(cls, app, data):
        """Save the entire metadata dictionary."""
        path = cls.get_metadata_path(app)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def get_by_id(cls, app, backup_id):
        """Fetch metadata for a single backup ID (UUID)."""
        data = cls.load_all(app)
        return data.get(backup_id)

    @classmethod
    def save(cls, app, backup_id, metadata):
        """Save or update metadata for a backup ID."""
        data = cls.load_all(app)
        data[backup_id] = metadata
        return cls.save_all(app, data)

    @classmethod
    def delete(cls, app, backup_id):
        """Delete metadata entry for a backup ID."""
        data = cls.load_all(app)
        if backup_id in data:
            del data[backup_id]
            return cls.save_all(app, data)
        return False
