from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Float
from sqlalchemy.dialects.postgresql import JSON


db = SQLAlchemy()


class AccountType:
    EMAIL = 'Email'
    GOOGLE = 'Google'

# Models
class User(db.Model):
    __tablename__ = 'Users'
    id = db.Column(Integer, primary_key=True, autoincrement=True)  
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(500))
    flex_password = db.Column(db.String(200), nullable=True) 
    contact_no = db.Column(db.String(15), nullable=True)
    account_type = db.Column(db.String(8), default=AccountType.EMAIL, nullable=False)
    created = db.Column(db.DateTime, default=db.func.now())


class UserPreference(db.Model):
    __tablename__ = 'UserPreferences'

    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    stations = db.Column(db.JSON, nullable=True)  
    weekly_availability = db.Column(db.JSON, nullable=True) 

    user = db.relationship('User', backref='preferences')


class OfferLog(db.Model):
    __tablename__ = 'OfferLogs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    offer_details_station = db.Column(db.String(120), nullable=False)
    offer_details_station_address = db.Column(db.String(120), nullable=False)
    offer_date = db.Column(db.String(120), nullable=False)
    offer_time_window = db.Column(db.String(120), nullable=False)
    pay_range_with_tips = db.Column(db.String(120), nullable=False)
    pay_description = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    user = db.relationship('User', backref='offers')
    

class Station(db.Model):
    __tablename__ = 'Stations'  # Add tablename to match convention
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)  # Changed from 'user.id' to 'Users.id'
    stations = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Add relationship to User model
    user = db.relationship('User', backref='stations')

    def __repr__(self):
        return f'<Station {self.id} for user {self.user_id}>'

