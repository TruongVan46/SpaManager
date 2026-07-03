from extensions import db

class Setting(db.Model):
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Setting {self.key}>'

    @staticmethod
    def get(key, default=None):
        """Get a setting value by key."""
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            return setting.value
        return default

    @staticmethod
    def set(key, value):
        """Set a setting value by key. Creates if not exists."""
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = Setting(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
        return setting

    @staticmethod
    def get_all_spa_info():
        """Get all spa info settings as a dictionary."""
        keys = [
            'spa_name', 'spa_owner', 'spa_phone', 'spa_email',
            'spa_address', 'spa_logo', 'spa_open_time', 'spa_close_time'
        ]
        result = {}
        for key in keys:
            result[key] = Setting.get(key, '')
        return result

    @staticmethod
    def save_spa_info(data):
        """Save all spa info settings from a dictionary."""
        keys = [
            'spa_name', 'spa_owner', 'spa_phone', 'spa_email',
            'spa_address', 'spa_logo', 'spa_open_time', 'spa_close_time'
        ]
        for key in keys:
            if key in data:
                Setting.set(key, data[key])
