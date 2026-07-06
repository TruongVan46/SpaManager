from app import db
from utils.timezone_utils import utc_now

class Invoice(db.Model):
    __tablename__ = 'invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    invoice_date = db.Column(db.Date, nullable=True)
    subtotal = db.Column(db.Float, default=0.0)
    discount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.String(100), nullable=True)
    # Workspace isolation — nullable during phase 1 (Task 6.5.2).
    # Task 6.5.5 will enforce workspace-scoped queries.
    workspace_id = db.Column(db.Integer, db.ForeignKey('workspaces.id'), nullable=True, index=True)

    customer = db.relationship('Customer', backref=db.backref('invoices', lazy=True))
    details = db.relationship('InvoiceDetail', backref='invoice', lazy=True)

    def __repr__(self):
        return f'<Invoice {self.id} - {self.total_amount}>'
