from app import db

class InvoiceDetail(db.Model):
    __tablename__ = 'invoice_details'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    service = db.relationship('Service', backref=db.backref('invoice_details', lazy=True))

    def __repr__(self):
        return f'<InvoiceDetail {self.id} - Invoice {self.invoice_id}>'