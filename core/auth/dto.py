# core/auth/dto.py

class UserDTO:
    def __init__(self, id, username, full_name, role, avatar, last_login, created_at):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.role = role
        self.avatar = avatar
        self.last_login = last_login
        self.created_at = created_at

    @classmethod
    def from_model(cls, user_model):
        """Translate a database User model instance into a UserDTO instance."""
        if not user_model:
            return None
        return cls(
            id=user_model.id,
            username=user_model.username,
            full_name=user_model.full_name,
            role=user_model.role,
            avatar=user_model.avatar,
            last_login=user_model.last_login,
            created_at=user_model.created_at
        )
