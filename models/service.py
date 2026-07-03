from app import db

class Service(db.Model):
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    duration = db.Column(db.Integer, nullable=True) # duration in minutes
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=True, default='other')
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f'<Service {self.name}>'