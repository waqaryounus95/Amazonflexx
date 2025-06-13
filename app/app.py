import json
import logging
from flask import Flask, request, jsonify , abort
from datetime import datetime ,timedelta
import threading
import schedule
import time
import requests
from Amazonflexapi import process_offers, initialize_driver, initial_setup , forfeit_offer ,get_weekday_from_string ,scrape_stations
from models import User, OfferLog, db ,UserPreference , Station
from werkzeug.security import generate_password_hash,check_password_hash
import jwt
import os
from config import Config
from flask_cors import CORS
from flask_migrate import Migrate
from Amazonflexapi import UserScript 
from device_pool import assign_device, release_device
from flask_socketio import SocketIO, emit, join_room


user_scripts = {}
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
CORS(app)
migrate = Migrate(app, db)

with app.app_context():
    db.create_all()


socketio = SocketIO(app, cors_allowed_origins="*",logger=True,
    engineio_logger=True)

@socketio.on('connect')
def handle_connect():
    logging.info('Client connected')
    
@socketio.on('disconnect')
def handle_disconnect():
    logging.info('Client disconnected')

@socketio.on_error()
def error_handler(e):
    logging.error(f'SocketIO error: {str(e)}')
    return False

@socketio.on('error')
def error_handler_client(error):
    logging.error(f'Client error: {error}')
    
from middleware import simple_middleware
simple_middleware(app)

def validate_signup_data(data):
    required_fields = ['email', 'password', 'contact_no']
    for field in required_fields:
        if field not in data or not data[field].strip():
            return f"{field} is required."
    if '@' not in data['email']:
        return "Invalid email format."
    if len(data['password']) < 8:
        return "Password must be at least 8 characters long."
    return None

def validate_login_data(data):
    required_fields = ['email', 'password']
    for field in required_fields:
        if field not in data or not data[field].strip():
            return f"{field} is required."
    return None

def createJWTtoken(payload):
    try:
        # tz=settings.TIME_ZONE
        expiry = datetime.now() + timedelta(days=1)
        refreshExpiry = datetime.now() + timedelta(days=7)

        token = jwt.encode({'email': payload['email'], 'expiry': expiry.timestamp()}, 'secret',  algorithm='HS256')
        refreshToken = jwt.encode({'email': payload['email'],'expiry': refreshExpiry.timestamp()}, str(os.environ.get('REFRESH_SECRETKEY')), algorithm='HS256')
        return {'access_token': token, 'refresh_token': refreshToken}

    except Exception as e:
        raise Exception(str(e))


@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        account_type = data.get('account_type', None)

        # Handle social signup (e.g., Google)
        if account_type in ['Google']:
            access_token = data.get('access_token', None)

            if not access_token:
                return jsonify({"success": False, "statusCode": 400, "message": "Access token is required."}), 400
            
            try:
                email = None
                if account_type == 'Google':
                    decoded_token = jwt.decode(access_token, options={"verify_signature": False}, algorithms="HS256")
                    email = decoded_token.get('email')

                    if not email:
                        return jsonify({"success": False, "statusCode": 400, "message": "Email not found."}), 400

                if User.query.filter_by(email=email).first():
                    return jsonify({"success": False, "statusCode": 400, "message": "User with this email already exists."}), 400

                user_new = User(
                    email=email,
                    account_type=account_type
                )
                db.session.add(user_new)
                db.session.commit()

            except jwt.ExpiredSignatureError:
                return jsonify({"success": False, "statusCode": 400, "message": "The token has expired."}), 400
            except jwt.InvalidTokenError:
                return jsonify({"success": False, "statusCode": 400, "message": "Invalid token."}), 400

            message = "User created successfully with social login."

        # Handle normal signup
        else:
            validation_error = validate_signup_data(data)
            if validation_error:
                return jsonify({"success": False, "statusCode": 400, "message": validation_error}), 400

            if User.query.filter_by(email=data['email'].strip()).first():
                return jsonify({"success": False, "statusCode": 400, "message": "Email already exists."}), 400

            if not data['password'] or len(data['password']) < 8:
                return jsonify({"success": False, "statusCode": 400, "message": "Password too short. It must be at least 8 characters."}), 400

            user_new = User(
                email=data['email'].strip(),
                password=generate_password_hash(data['password']),
                flex_password=data['password'], 
                contact_no=data['contact_no'].strip()
            )
            db.session.add(user_new)
            db.session.commit()

            message = "User created successfully."

        payload = {'email': user_new.email, 'pk': user_new.id}
        tokens = createJWTtoken(payload)

        user_data = {
            '_id': user_new.id,
            'email': user_new.email,
            'active': True,
            'account_type': user_new.account_type,
            'contact_no': user_new.contact_no
        }

        response = jsonify({
            "success": True,
            "statusCode": 200,
            "payload": {
                "token": tokens['access_token'],
                **user_data
            },
            "message": message
        })
        response.set_cookie(
            key="refresh_token",
            value=tokens['refresh_token'],
            httponly=True,
            samesite='Lax',
            secure=True,
            max_age=3600 * 24 * 7  # 7 days
        )
        return response

    except Exception as e:
        print(e)
        return jsonify({"success": False, "statusCode": 500, "message": "Internal server error occurred."}), 500


@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        account_type = data.get('account_type', None)

        # Social login (Google)
        if account_type in ['Google']:
            access_token = data.get('access_token', None)
            if not access_token:
                return jsonify({"success": False, "statusCode": 400, "message": "Access token is required."}), 400
            email = None
            try:
                if account_type == 'Google':
                    decoded_token = jwt.decode(access_token, options={"verify_signature": False}, algorithms="HS256")
                    email = decoded_token.get('email')

                if not email:
                    return jsonify({"success": False, "statusCode": 400, "message": "Email not found in token."}), 400

                user_obj = User.query.filter_by(email=email).first()
                if user_obj and user_obj.account_type != account_type:
                    return jsonify({"success": False, "statusCode": 400, "message": f"Please use {user_obj.account_type} to log in."}), 400

            except jwt.ExpiredSignatureError:
                return jsonify({"success": False, "statusCode": 400, "message": "The token has expired."}), 400
            except jwt.InvalidTokenError:
                return jsonify({"success": False, "statusCode": 400, "message": "Invalid token."}), 400
        
        # Normal login
        else:
            validation_error = validate_login_data(data)
            if validation_error:
                return jsonify({"success": False, "statusCode": 400, "message": validation_error}), 400

            email = data.get('email', None)
            password = data.get('password', None)

            if not email or not password:
                return jsonify({"success": False, "statusCode": 400, "message": "Email and password are required."}), 400

            user_obj = User.query.filter_by(email=email).first()

            if user_obj is None or not check_password_hash(user_obj.password, password):
                return jsonify({"success": False, "statusCode": 401, "message": "Invalid email or password."}), 401

        db.session.commit()

        payload = {'email': user_obj.email, 'pk': user_obj.id}
        tokens = createJWTtoken(payload)
        user_data = {
            'id': user_obj.id,
            'email': user_obj.email,
            'active': True,
            'account_type': user_obj.account_type
        }

        response = jsonify({
            "success": True,
            "statusCode": 200,
            "payload": {
                "token": tokens['access_token'],
                **user_data
            },
            "message": "Login successful."
        })
        response.set_cookie(
            key="refresh_token",
            value=tokens['refresh_token'],
            httponly=True,
            samesite='Lax',
            secure=True,
            max_age=3600 * 24 * 7  # 7 days
        )
        return response

    except Exception as e:
        print(f"Error during login: {e}")
        return jsonify({"success": False, "statusCode": 500, "message": "Internal server error occurred."}), 500

@app.route('/logout', methods=['PATCH'])
def logout():
    try:
        response = jsonify({
            "success": True,
            "statusCode": 200,
            "message": "Logged out successfully"
        })
        response.set_cookie(
            key="refresh_token",
            value="",
            httponly=True,
            samesite='Lax',
            secure=True,
            max_age=0  # Expire the cookie immediately
        )
        return response
    except Exception as e:
        print(f"Error in logout: {e}")
        return jsonify({"success": False, "statusCode": 500, "message": "Internal server error occurred."}), 500

valid_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
datetime_format = "%Y-%m-%d %H:%M"

def get_valid_stations(user_id=None):
    """Get list of valid stations from database"""
    try:
        if user_id:
            station_record = Station.query.filter_by(user_id=user_id).first()
            return station_record.stations if station_record else []
        else:
            # Get all unique stations across all users
            all_stations = set()
            station_records = Station.query.all()
            for record in station_records:
                all_stations.update(record.stations)
            return list(all_stations)
    except Exception as e:
        logging.error(f"Error fetching stations from DB: {e}")
        return []
    
@app.route('/scrape_stations', methods=['POST'])
def scrape_stations_route():
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({"status": "error", "message": "User ID is required"}), 400

    device_config = assign_device()
    if not device_config:
        return jsonify({"status": "error", "message": "No available devices"}), 503

    try:        
        device_name = device_config.get('device_name')
        udid = device_config.get('udid')
        platform_version = device_config.get('platform_version')
        appium_server_url = device_config.get('appium_server_url')
        
        driver = initialize_driver(device_name, udid, platform_version, appium_server_url)        
        user = db.session.get(User, user_id)
        if not user:
            release_device(device_name)
            return jsonify({"status": "error", "message": "User not found"}), 404

        # Login first
        # if not initial_setup(driver, user.email, user.flex_password):
        #     driver.quit()
        #     release_device(device_config['device_name'])
        #     return jsonify({"status": "error", "message": "Failed to login"}), 500

        # Scrape stations
        stations = scrape_stations(driver)
        
        driver.quit()
        release_device(device_name)

        if not stations:
            return jsonify({"status": "error", "message": "No stations found"}), 404

        # Update or create stations record in database
        with app.app_context():
            existing_station_record = Station.query.filter_by(user_id=user_id).first()
            
            if existing_station_record:
                existing_station_record.stations = stations
                existing_station_record.updated_at = datetime.utcnow()
                db.session.commit()
                logging.info(f"Updated stations for user {user_id}")
            else:
                new_station_record = Station(
                    user_id=user_id,
                    stations=stations
                )
                db.session.add(new_station_record)
                db.session.commit()
                logging.info(f"Created new stations record for user {user_id}")

        user_preference = UserPreference.query.filter_by(user_id=user_id).first()
        if user_preference:
            existing_stations = user_preference.stations or []
            updated_stations = []
            
            for station in stations:
                existing = next((s for s in existing_stations if s.get('name') == station), None)
                if existing:
                    updated_stations.append(existing)
                else:
                    updated_stations.append({
                        'name': station,
                        'offer_min_price': 0,
                        'hourly_min_price': 0,
                        'eta': 0
                    })
            
            user_preference.stations = updated_stations
            db.session.commit()

        return jsonify({
            "status": "success", 
            "message": f"Successfully scraped and stored {len(stations)} stations",
            "stations": stations
        }), 200

    except Exception as e:
        logging.error(f"Error in station scraping: {e}")
        release_device(device_config.get('device_name'))
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_stations', methods=['GET'])
def get_stations():
    """Get scraped stations from database for a specific user or all stations"""
    try:
        user_id = request.args.get('user_id')
        
        if user_id:
            # Get stations for specific user
            station_record = Station.query.filter_by(user_id=user_id).first()
            if not station_record:
                return jsonify({
                    "status": "error",
                    "message": "No stations found for this user"
                }), 404
                
            return jsonify({
                "status": "success",
                "user_id": user_id,
                "stations": station_record.stations,
                "created_at": station_record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": station_record.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            }), 200
        else:
            # Get all stations from all users
            station_records = Station.query.all()
            all_stations = []
            
            for record in station_records:
                all_stations.append({
                    "user_id": record.user_id,
                    "stations": record.stations,
                    "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": record.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                })
            
            return jsonify({
                "status": "success",
                "stations": all_stations
            }), 200

    except Exception as e:
        logging.error(f"Error fetching stations: {e}")
        return jsonify({
            "status": "error",
            "message": "Could not fetch stations from database"
        }), 500

@app.route('/set_filters', methods=['POST'])
def set_filters():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        weekly_availability = data.get('weekly_availability', [])
        stations = data.get('stations', [])

        if not user_id:
            return jsonify({"status": "error", "message": "User ID is required"}), 400

        if not isinstance(weekly_availability, list) or len(weekly_availability) == 0:
            return jsonify({"status": "error", "message": "weekly_availability must be a non-empty array"}), 400

        for entry in weekly_availability:
            day = entry.get('day')
            from_str = entry.get('from')
            to_str = entry.get('to')

            if day not in valid_days:
                return jsonify({"status": "error", "message": f"Invalid day: {day}"}), 400
            try:
                datetime.strptime(from_str, datetime_format)
                datetime.strptime(to_str, datetime_format)
            except (ValueError, TypeError):
                return jsonify({"status": "error", 
                                "message": f"Invalid date-time format for {day}. Use {datetime_format}"}), 400


        if not isinstance(stations, list):
            return jsonify({"status": "error", "message": "stations must be an array"}), 400
        valid_stations = get_valid_stations()
        
        for st in stations:
            st_name = st.get('name')
            st_offer = st.get('offer_min_price')
            st_hourly = st.get('hourly_min_price')
            st_eta = st.get('eta')

            if st_name not in valid_stations:
                return jsonify({"status": "error", "message": f"Invalid station name: {st_name}"}), 400
            
        existing_pref = UserPreference.query.filter_by(user_id=user_id).first()

        if existing_pref:
            existing_pref.weekly_availability = weekly_availability
            existing_pref.stations = stations
            db.session.commit()
        else:
            user_preference = UserPreference(
                user_id=user_id,
                weekly_availability=weekly_availability,
                stations=stations
            )
            db.session.add(user_preference)
            db.session.commit()

        return jsonify({"status": "success", "message": "Filters set successfully"}), 200

    except Exception as e:
        print(f"Error setting filters: {e}")
        return jsonify({"status": "error", "message": "Could not set filters"}), 500

@app.route('/get_filters', methods=['GET'])
def get_filters():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "User ID is required"}), 400
    
    try:
        user_preference = UserPreference.query.filter_by(user_id=user_id).first()
        if not user_preference:
            return jsonify({"status": "error", "message": "No preferences found for this user"}), 404

        response_data = {
            "user_id": user_preference.user_id,
            "weekly_availability": user_preference.weekly_availability or [],
            "stations": user_preference.stations or []
        }

        return jsonify({"status": "success", "data": response_data}), 200
    
    except Exception as e:
        print(f"Error fetching filters: {e}")
        return jsonify({"status": "error", "message": "Could not fetch filters"}), 500

@app.route('/delete_station_filter', methods=['DELETE'])
def delete_station_filter():
    """Delete a specific station filter for a user"""
    try:
        user_id = request.args.get('user_id')
        station_name = request.args.get('station_name')
        
        if not user_id or not station_name:
            return jsonify({"status": "error",
                "message": "User ID and station name are required"
            }), 400

        user_preference = UserPreference.query.filter_by(user_id=user_id).first()
        
        if not user_preference:
            return jsonify({"status": "error",
                "message": "No preferences found for this user"
            }), 404

        current_stations = user_preference.stations or []
        updated_stations = [
            station for station in current_stations 
            if station.get('name') != station_name
        ]

        if len(current_stations) == len(updated_stations):
            return jsonify({"status": "error",
                "message": f"Station '{station_name}' not found in user preferences"
            }), 404
        
        user_preference.stations = updated_stations
        db.session.commit()
        
        logging.info(f"Deleted station filter '{station_name}' for user {user_id}")
        
        return jsonify({"status": "success",
            "message": f"Station filter '{station_name}' deleted successfully",
            "remaining_stations": updated_stations
        }), 200

    except Exception as e:
        logging.error(f"Error deleting station filter: {e}")
        return jsonify({"status": "error",
            "message": "Could not delete station filter"
        }), 500

@app.route('/get_offer_action', methods=['GET'])
def get_offer_action():
    user_id = request.args.get('user_id')
    offer_id = request.args.get('offer_id')
    action = request.args.get('action')
    if action in ['schedule', 'forfeit']:
        return jsonify({"status": "success", "action": action}), 200
    return jsonify({"status": "success", "action": "schedule"}), 200

@app.route('/available_offers', methods=['GET'])
def available_offers():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "User ID is required"}), 400

    try:
        offers = OfferLog.query.filter_by(user_id=user_id).all()
        logging.info(f"Total offers fetched for user_id {user_id}: {len(offers)}")

        offer_list = []
        for offer in offers:
            offer_data = {
                'id': offer.id,
                'station': offer.offer_details_station,
                'address': offer.offer_details_station_address,
                'date': offer.offer_date,
                'time_window': offer.offer_time_window,
                'pay': offer.pay_range_with_tips,
                'description': offer.pay_description,
                'status': offer.status,
                'created_at': offer.created_at.strftime("%Y-%m-%d %H:%M")
            }
            offer_list.append(offer_data)                
            
        logging.info(f"Total offers returned: {len(offer_list)}")
        return jsonify({"status": "success", "offers": offer_list}), 200

    except Exception as e:
        logging.error(f"Error fetching available offers: {e}")
        return jsonify({"status": "error", "message": "Could not fetch available offers"}), 500

@app.route('/accept_offer', methods=['POST'])
def accept_offer():
    data = request.json
    user_id = data.get('user_id')
    offer_id = data.get('offer_id')
    offer_details = data.get('offer_details')
    offer_amount = data.get('offer_amount')

    if not user_id or not offer_id:
        return jsonify({"status": "error", "message": "User ID and Offer ID are required"}), 400

    try:
        offer = OfferLog.query.filter_by(id=offer_id).first()
        if not offer:
            offer = OfferLog(
                id=offer_id,
                user_id=user_id,
                offer_details_station=offer_details.split(' ')[0],
                offer_details_station_address=' '.join(offer_details.split(' ')[1:]),
                offer_date=datetime.now().strftime("%Y-%m-%d"),
                offer_time_window="N/A", 
                pay_range_with_tips=offer_amount,
                pay_description="N/A",
                status='accepted'
            )
            db.session.add(offer)
        else:
            offer.status = 'accepted'
        
        db.session.commit()
        
        offer_data = {
            'id': offer.id,
            'station': offer.offer_details_station,
            'address': offer.offer_details_station_address,
            'date': offer.offer_date,
            'time_window': offer.offer_time_window,
            'pay': offer.pay_range_with_tips,
            'description': offer.pay_description,
            'status': offer.status,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M"),
            'user_id': user_id
        }        
        
        socketio.emit('offer_update', {'data': offer_data})
        logging.info(f"Offer update broadcasted for user {user_id}")

        return jsonify({"status": "success", "message": "Offer accepted"}), 200
    except Exception as e:
        print(f"Error accepting offer: {e}")
        return jsonify({"status": "error", "message": "Could not accept offer"}), 500

@app.route('/forfeit_offer', methods=['POST'])
def forfeit_offer_route():
    data = request.json
    user_id = data.get('user_id')
    offer_id = data.get('offer_id')
    day_of_month = data.get("day_of_month")
    
    if not day_of_month:
        return jsonify({"error": "Missing day_of_month"}), 400
    if not user_id or not offer_id:
        return jsonify({"status": "error", "message": "User ID and Offer ID are required"}), 400

    device_config = assign_device()
    if not device_config:
        return jsonify({"status": "error", "message": "No available devices"}), 503

    try:
        device_name = device_config.get('device_name')
        udid = device_config.get('udid')
        platform_version = device_config.get('platform_version')
        appium_server_url = device_config.get('appium_server_url')

        driver = initialize_driver(device_name,udid , platform_version, appium_server_url)
        offer = OfferLog.query.filter_by(id=offer_id, user_id=user_id).first()
        if not offer:
            release_device(device_name)
            return jsonify({"status": "error", "message": "Offer not found"}), 404
        
        
        if forfeit_offer(driver, day_of_month):            
            db.session.delete(offer)
            db.session.commit()
            logging.info(f"Offer {offer_id} forfeited and deleted.")
            release_device(device_name)
            return jsonify({"status": "success", "message": "Offer forfeited and deleted"}), 200
        else:
            release_device(device_name)
            return jsonify({"status": "error", "message": "Failed to forfeit the offer"}), 500      
        

    except Exception as e:
        logging.error(f"Error forfeiting offer: {e}")
        release_device(device_config.get('device_name'))
        return jsonify({"status": "error", "message": "Could not forfeit offer"}), 500

@app.route('/start_script', methods=['POST'])
def start_script():
    data = request.json
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({"status": "error", "message": "User ID is required"}), 400
        
    if user_id in user_scripts and user_scripts[user_id].running:
        return jsonify({"status": "error", "message": "Script is already running for this user"}), 400

    device_config = assign_device()
    if not device_config:
        return jsonify({"status": "error", "message": "No available devices. Please try again later."}), 503

    try:
        user = db.session.get(User, user_id)
        if not user:
            release_device(device_config['device_name'])
            return jsonify({"status": "error", "message": "User not found"}), 404

        user_script = UserScript(device_config, user.email, user.flex_password, user_id)
        script_thread = threading.Thread(target=user_script.start)
        script_thread.daemon = True  
        script_thread.start()
        user_scripts[user_id] = user_script

        return jsonify({
            "status": "success", 
            "message": f"Script started successfully on device {device_config['device_name']}"
        }), 200

    except Exception as e:
        logging.error(f"Error starting script: {e}")
        if device_config:
            release_device(device_config['device_name'])
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stop_script', methods=['POST'])
def stop_script():
    data = request.json
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "User ID is required"}), 400

    if user_id not in user_scripts or not user_scripts[user_id].running:
        return jsonify({"status": "error", "message": "Script is not running for this user"}), 400

    # Stop the user's script.
    user_scripts[user_id].stop()

    # Release the device used by this script.
    device_name = user_scripts[user_id].device_config.get('device_name')
    release_device(device_name)
    
    return jsonify({"status": "success", "message": "Script stopped and device released"}), 200

@app.route('/script_status', methods=['GET'])
def script_status(user_state):
    return jsonify({"status": "running" if user_state.running else "stopped"}), 200

@app.route('/auto_start', methods=['POST'])
def auto_start():
    try:
        data = request.json
        start_time_str = data.get('start_time')
        user_id = data.get('user_id')
        
        if not start_time_str or not user_id:
            return jsonify({'status':'error' , 'message': 'start script and user id not found'}), 400
        
        try:
            start_time = datetime.strptime(start_time_str , "%Y-%m-%d %H:%M:%S")
        except ValueError :
            return jsonify({"status": "error", "message": "Invalid start time format. Use 'YYYY-MM-DD HH:MM:SS'"}), 400
        
        def start_script_job():
            requests.post('http://localhost:5000/start_script', json={'user_id':user_id})
        schedule.every().day.at(start_time.strftime("%H:%M:%S")).do(start_script_job)
        
        return jsonify({'status': ' success' , 'message': 'script auto started'}), 200
    except Exception as e:
        print(f"Error starting script: {e}")
        return jsonify({"status": "error", "message": "Could not start script"}), 500

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    ip = "0.0.0.0"
    port = 5000
    # scheduler_thread = threading.Thread(target=run_scheduler)
    # scheduler_thread.start()
    socketio.run(app , host=ip, port=port)
    